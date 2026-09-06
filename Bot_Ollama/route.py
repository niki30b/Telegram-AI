from dotenv import load_dotenv
import asyncio, json, logging, traceback, time
from collections import defaultdict, deque
from dataclasses import dataclass

from ai import generate_response, AVAILABLE_MODELS, web_search
from aiogram import Router, F, BaseMiddleware, Bot
from aiogram.filters import StateFilter, Command, CommandObject
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ErrorEvent
)
from storage import (
    data_path,
    config,
    load_data,
    load_user_config,
    save_user_config,
    save_chat_history,
)

from Forms.User_form import Form
from aiogram.fsm.context import FSMContext

router = Router()
logger = logging.getLogger("Route")

env = data_path / ".env"
load_dotenv(env)


MAX_REQUESTS_PER_MINUTE = 10
COOLDOWN_SECONDS = 2.0
GLOBAL_CONCURRENCY = 3
MAX_QUEUE_WAITERS = 20
QUEUE_TIMEOUT = 15.0
PER_USER_CONCURRENCY = 1

HOURLY_QUOTA_LIMIT = 30       # queries per hour per user
HOURLY_QUOTA_WINDOW = 3600.0


@dataclass
class RateLimitResult:
    allowed: bool
    reason: str = ""
    retry_after: float = 0.0


class RequestLimiter:
    def __init__(self):
        self._timestamps = defaultdict(deque)
        self._last_request = {}
        self._user_locks = defaultdict(lambda: asyncio.Semaphore(PER_USER_CONCURRENCY))
        self._global_semaphore = asyncio.Semaphore(GLOBAL_CONCURRENCY)
        self._queue_waiters = 0
        self._queue_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()

    async def check_rate_limit(self, user_id: int) -> RateLimitResult:
        now = time.monotonic()
        async with self._state_lock:
            timestamps = self._timestamps[user_id]
            while timestamps and now - timestamps[0] >= 60:
                timestamps.popleft()

            last = self._last_request.get(user_id)
            if last is not None:
                elapsed = now - last
                if elapsed < COOLDOWN_SECONDS:
                    return RateLimitResult(False, "cooldown", COOLDOWN_SECONDS - elapsed)

            if len(timestamps) >= MAX_REQUESTS_PER_MINUTE:
                retry_after = 60 - (now - timestamps[0])
                return RateLimitResult(False, "rate_limit", max(0.1, retry_after))

            timestamps.append(now)
            self._last_request[user_id] = now
            return RateLimitResult(True)

    async def acquire(self, user_id: int):
        user_lock = self._user_locks[user_id]
        await user_lock.acquire()

        global_acquired = False
        try:
            async with self._queue_lock:
                if self._queue_waiters >= MAX_QUEUE_WAITERS:
                    raise asyncio.QueueFull
                self._queue_waiters += 1

            try:
                await asyncio.wait_for(self._global_semaphore.acquire(), timeout=QUEUE_TIMEOUT)
                global_acquired = True
            finally:
                async with self._queue_lock:
                    self._queue_waiters -= 1

            if not global_acquired:
                raise asyncio.TimeoutError
        except Exception:
            user_lock.release()
            raise

        return _RequestSlot(self, user_lock)


class _RequestSlot:
    def __init__(self, limiter, user_lock):
        self._limiter = limiter
        self._user_lock = user_lock
        self._released = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._released:
            return
        self._released = True
        self._limiter._global_semaphore.release()
        self._user_lock.release()


request_limiter = RequestLimiter()


class HourlyQuota:
    def __init__(self):
        self._timestamps = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, user_id: int) -> RateLimitResult:
        now = time.monotonic()
        async with self._lock:
            timestamps = self._timestamps[user_id]
            while timestamps and now - timestamps[0] >= HOURLY_QUOTA_WINDOW:
                timestamps.popleft()

            if len(timestamps) >= HOURLY_QUOTA_LIMIT:
                retry_after = HOURLY_QUOTA_WINDOW - (now - timestamps[0])
                return RateLimitResult(False, "hourly_quota", max(0.1, retry_after))

            timestamps.append(now)
            return RateLimitResult(True)


hourly_quota = HourlyQuota()


try:
    _startup_data = load_data()
except json.JSONDecodeError:
    logger.critical(f"{config} is corrupted on startup — access denied for everyone, fix the file manually")
    _startup_data = {}

allowed_id = set(_startup_data.get("allowed_ids", []))


class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = event.from_user.id

        try:
            current_data = load_data()
        except json.JSONDecodeError:
            logger.critical("config.json corrupted — denying access to everyone")
            return

        current_allowed = set(current_data.get("allowed_ids", []))
        if user_id not in current_allowed:
            logger.warning(f"Access denied: user_id={user_id}")
            if hasattr(event, "answer"):
                await event.answer("Your ID is not on the whitelist.")
            elif hasattr(event, "message"):
                await event.message.answer("Your ID is not on the whitelist.")
            return

        return await handler(event, data)

router.message.outer_middleware(AccessMiddleware())
router.callback_query.outer_middleware(AccessMiddleware())


max_txt_size = 20_000
max_prompt_length = 1000


async def extract_txt_text(bot: Bot, document) -> str | None:
    if not document.file_name or not document.file_name.lower().endswith(".txt"):
        return None
    if document.file_size and document.file_size > max_txt_size:
        return None
    buffer = await bot.download(document)
    try:
        return buffer.read().decode("utf-8").strip()
    except UnicodeDecodeError:
        return None


def format_wait_time(seconds: float) -> str:
    total_seconds = max(1, round(seconds))
    minutes, secs = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


@router.error()
async def error_handler(event: ErrorEvent):
    logger.error(
        "Handler crashed:\n%s",
        "".join(traceback.format_exception(
            type(event.exception), event.exception, event.exception.__traceback__
        ))
    )
    update = event.update
    if update.message:
        await update.message.answer('Something went wrong. Please try again, or press "Rewrite data" to reset your setup.')
    elif update.callback_query:
        await update.callback_query.message.answer('Something went wrong. Please try again, or press "Rewrite data" to reset your setup.')


load_dotenv(env)
print(f"Allowed id: {allowed_id}\n.env and config.json path: {data_path}\n")


def Keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Info")],
            [KeyboardButton(text="About"), KeyboardButton(text="Help")],
        ],
        resize_keyboard=True
    )


def setting():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Start set up", callback_data="start_set_up")],
            [InlineKeyboardButton(text="Rewrite data", callback_data="rewrite")],
            [InlineKeyboardButton(text="Clear history", callback_data="clear_history")],
        ],
    )


def model_selection_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Gemma3 12B (abliterated)", callback_data="model_gemma3")],
            [InlineKeyboardButton(text="Qwen3 8B (abliterated)", callback_data="model_qwen3")],
            [InlineKeyboardButton(text="Dolphin3 8B", callback_data="model_dolphin3")],
            [InlineKeyboardButton(text="Dolphin-Mixtral", callback_data="model_dolphin-mixtral")],
        ],
    )


@router.callback_query(F.data.in_(["start_set_up", "rewrite"]))
async def recording_ai_data(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    logger.info("User %s (@%s) started AI setup", user_id, callback.from_user.username)

    await callback.answer()
    await callback.message.answer("Choose a model:", reply_markup=model_selection_keyboard())
    await state.set_state(Form.SelectModel)


@router.callback_query(lambda c: c.data == "clear_history")
async def clear_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    save_chat_history(user_id, [])
    logger.info("User %s cleared their chat history", user_id)
    await callback.answer()
    await callback.message.answer("History cleared. Fresh start.")


@router.callback_query(Form.SelectModel, F.data.startswith("model_"))
async def select_model(callback: CallbackQuery, state: FSMContext):
    key = callback.data.removeprefix("model_")
    model_name = AVAILABLE_MODELS.get(key)

    if model_name is None:
        await callback.answer("Unknown model", show_alert=True)
        return

    user_id = callback.from_user.id
    try:
        user_config = load_user_config(user_id)
    except json.JSONDecodeError:
        await callback.message.answer("Your setting is corrupted, please try again.")
        await callback.answer()
        return

    user_config["model"] = model_name
    save_user_config(user_id, user_config)

    await callback.answer()
    await callback.message.answer(
        f"Model set to: {model_name}\n\n"
        "Now tell me how you want the AI to behave (send text or a .txt file)."
    )
    await state.set_state(Form.Behavior)


@router.message(StateFilter(Form.SelectModel))
async def wrong_input_during_model_select(message: Message):
    await message.answer("Please choose a model using the buttons above, not text.")

@router.message(Command("search"))
async def search_command(message: Message, state: FSMContext, command: CommandObject):
    current_state = await state.get_state()
    if current_state in {Form.SelectModel.state, Form.Behavior.state}:
        return

    query = command.args
    if not query:
        await message.answer("Usage: /search <your query>")
        return

    try:
        results = await asyncio.to_thread(web_search, query)
    except ConnectionError:
        await message.answer("Web search is unavailable right now. Try again later.")
        return

    if not results:
        await message.answer("No search results found.")
        return

    await _run_ai_request(message, message.from_user.id, query, extra_context=results)

@router.message(Form.Behavior, F.text)
async def save_behavior(message: Message, state: FSMContext):
    Behavior = message.text

    if Behavior.startswith("/"):
        await message.answer("That looks like a command, not a behavior prompt. Please send plain text.")
        return

    if len(Behavior) > max_prompt_length:
        await message.answer(f"Behavior text is too long (max {max_prompt_length} characters).")
        return

    user_id = message.from_user.id
    try:
        user_config = load_user_config(user_id)
    except json.JSONDecodeError:
        await message.answer("Your setting is corrupted, please try again.")
        return

    user_config["prompt"] = Behavior
    save_user_config(user_id, user_config)

    await message.answer("Behavior saved")
    await state.clear()

@router.message(F.text == "Info")
async def button_info(message: Message):
    await message.answer("""
This bot lets you chat with a locally-hosted, uncensored AI model — no external cloud API, no content filtering beyond what you set yourself.

Use /start to pick a model and describe how you want it to behave.

<b>Available models:</b>
- Gemma3 12B (abliterated)
- Qwen3 8B (abliterated)
- Dolphin3 8B
- Dolphin-Mixtral

<b>Note:</b> these models have no built-in safety guardrails. You are responsible for what you ask them to generate.
    """, parse_mode='HTML')


@router.message(F.text == "About")
async def button_about(message: Message):
    await message.answer("""
<b>About this bot</b>

A personal Telegram bot for chatting with locally-hosted AI models via Ollama. Open-source — the code is on GitHub if you want to run your own instance.

Everyone's chat history and settings are encrypted and stored separately — no one else can see them.
    """, parse_mode='HTML')


@router.message(F.text == "Help")
async def button_help(message: Message):
    await message.answer("""
<b>Commands</b>
/start — set up or reset your model and behavior
/search &lt;query&gt; — search the web and get an answer grounded in real results

<b>Buttons</b>
Rewrite data — pick a new model and re-enter your behavior prompt
Clear history — wipe your conversation history, keep your settings

<b>Limits</b>
Up to 30 messages per hour, with a short cooldown between messages, to keep the bot responsive for everyone.

The maximum chat history size is 120 messages, 60 messages from the bot and 60 from the user.
    """, parse_mode='HTML')

@router.message(Form.Behavior, F.document)
async def save_behavior_file(message: Message, state: FSMContext, bot: Bot):
    text = await extract_txt_text(bot, message.document)

    if text is None:
        await message.answer("I can't accept files of this type. I can only accept .txt")
        return
    if not text:
        await message.answer("The file is empty.")
        return
    if len(text) > max_prompt_length:
        await message.answer(f"Behavior text is too long (max {max_prompt_length} characters).")
        return

    user_id = message.from_user.id
    try:
        user_config = load_user_config(user_id)
    except json.JSONDecodeError:
        await message.answer("Your setting is corrupted, please try again.")
        return

    user_config["prompt"] = text
    save_user_config(user_id, user_config)

    await message.answer("Behavior saved")
    await state.clear()


@router.message(StateFilter(Form.Behavior))
async def wrong_content_during_behavior(message: Message):
    await message.answer("Please send plain text or .txt, not a photo/sticker/etc.")


@router.message(F.text.lower().in_(["start", "/start"]))
async def start_bot(message: Message):
    await message.answer(f"Hello, {message.from_user.first_name}", reply_markup=Keyboard())
    await asyncio.sleep(0.5)
    await message.answer("Let's start setting up your AI Bot", reply_markup=setting())


async def _run_ai_request(message: Message, user_id: int, text: str, extra_context: str | None = None):
    quota_result = await hourly_quota.check(user_id)
    if not quota_result.allowed:
        await message.answer(
            f"You've hit your hourly limit ({HOURLY_QUOTA_LIMIT} requests/hour). "
            f"You can continue in {format_wait_time(quota_result.retry_after)}."
        )
        return

    limit_result = await request_limiter.check_rate_limit(user_id)
    if not limit_result.allowed:
        await message.answer(f"Slow down — you can continue in {format_wait_time(limit_result.retry_after)}.")
        return

    try:
        slot = await request_limiter.acquire(user_id)
    except asyncio.QueueFull:
        await message.answer("The bot is overloaded right now. Please try again in a bit.")
        return
    except asyncio.TimeoutError:
        await message.answer("Server is busy, please try again.")
        return

    async with slot:
        try:
            response = await asyncio.to_thread(generate_response, user_id, text, extra_context)
            await message.answer(response)
        except ValueError as e:
            logger.warning("Bot configuration error for user %s: %s", user_id, e)
            await message.answer("Bot is not configured yet. Use /start to set up your model and behavior.")
        except Exception:
            logger.exception("Failed to process bot message for user %s", user_id)
            await message.answer("Bot request failed. Please try again later.")


@router.message(F.document)
async def send_document_to_ai(message: Message, state: FSMContext, bot: Bot):
    current_state = await state.get_state()
    if current_state in {Form.SelectModel.state, Form.Behavior.state}:
        return

    text = await extract_txt_text(bot, message.document)
    if text is None:
        await message.answer("I can't accept files of this type. I can only accept .txt")
        return
    if not text:
        await message.answer("The file is empty.")
        return

    await _run_ai_request(message, message.from_user.id, text)


@router.message(F.text)
async def send_message_to_ai(message: Message, state: FSMContext):
    text = message.text
    if not text or text.startswith("/"):
        return

    current_state = await state.get_state()
    if current_state in {Form.SelectModel.state, Form.Behavior.state}:
        return

    await _run_ai_request(message, message.from_user.id, text)


@router.message()
async def handle_unsupported_content(message: Message):
    await message.answer("I can't accept files of this type. I can only accept .txt")
