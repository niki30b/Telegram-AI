from dotenv import load_dotenv
from pathlib import Path
import asyncio, json, logging, traceback, time
from collections import defaultdict, deque
from dataclasses import dataclass

from ai import validate_api_key, generate_response
from aiogram import Router, F, BaseMiddleware, Bot
from aiogram.filters import StateFilter
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


max_txt_size = 20_000 #max txt file size(20KB)
max_prompt_length = 1000 #max symbols in prompt


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
            [KeyboardButton(text="About")],
        ],
        resize_keyboard=True
    )


def setting():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="API Keys", url="https://openrouter.ai/workspaces/default/keys")],
            [InlineKeyboardButton(text="How to get API Keys", callback_data="instructions")],
            [InlineKeyboardButton(text="Rewrite data", callback_data="rewrite")],
            [InlineKeyboardButton(text="Clear history", callback_data="clear_history")],
            [InlineKeyboardButton(text="Start set up", callback_data="start_set_up")],
        ],
    )


def confirm_cancel():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Confirm✅", callback_data="confirm")],
            [InlineKeyboardButton(text="Cancel❌", callback_data="cancel")],
        ],
    )


@router.callback_query(lambda c: c.data == "instructions")
async def proccess_instructions(callback: CallbackQuery):
    await callback.message.answer("""

Visit this link: "<a href="URL">https://openrouter.ai/workspaces/default/keys</a>"

If you don't have an account, create one first. Then, return to the page and create an API key. Copy the key and save it somewhere safe. **You will not be able to view the key again after leaving the page for security reasons.**

Once you've copied the API key, click **"Start Setup"** in the bot and send the key to it.

The bot will then ask you to describe how you want it to behave. Tell it about the personality, behavior, or other instructions you'd like it to follow.

Once the bot receives your instructions, the setup is complete. It will wish you a pleasant conversation and you can start chatting with it.

    """, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.in_(["start_set_up", "rewrite"]))
async def recording_ai_data(callback: CallbackQuery, state: FSMContext):
    logger.info("User %s (@%s) started AI setup", callback.from_user.id, callback.from_user.username)
    await callback.message.answer("Send only your API key, without any additional text.")
    await state.set_state(Form.API_Key)
    await callback.answer()

@router.callback_query(lambda c: c.data == "clear_history")
async def clear_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    save_chat_history(user_id, [])
    logger.info("User %s cleared their chat history", user_id)
    await callback.answer()
    await callback.message.answer("History cleared. Fresh start.")


@router.message(Form.API_Key, F.text)
async def save_api_key(message: Message, state: FSMContext):
    API_Key = message.text
    await state.update_data(API_Key=API_Key)

    try:
        await message.delete()
    except Exception:
        logger.warning("Could not delete API key message for user %s", message.from_user.id)

    await message.answer('Your API Key is correct?', reply_markup=confirm_cancel())


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


@router.message(StateFilter(Form.API_Key, Form.Behavior))
async def wrong_content_during_setup(message: Message):
    await message.answer("Please send plain text or .txt, not a photo/sticker/etc.")


@router.callback_query(lambda c: c.data == "cancel")
async def cancel_proccess(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Okay, let's repeat")
    await state.clear()
    await callback.message.answer("Send only your API key, without any additional text.")
    await state.set_state(Form.API_Key)
    await callback.answer()


@router.callback_query(lambda c: c.data == "confirm")
async def confirm_proccess(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    api_key = data.get("API_Key")
    user_id = callback.from_user.id

    await callback.answer()
    await callback.message.answer("Checking your API key...")

    try:
        is_valid = await asyncio.to_thread(validate_api_key, api_key)
    except ConnectionError:
        await callback.message.answer("Couldn't reach Groq right now. Try again in a bit.")
        return

    if not is_valid:
        await callback.message.answer("This API key is invalid. Send a correct one.")
        return

    await callback.message.answer('''Great, let's set up the AI prompts/behavior.
Whatever you write in the next message will set your AI's prompt.
You can change it later by pressing "Rewrite data".''')

    try:
        user_config = load_user_config(user_id)
    except json.JSONDecodeError:
        await callback.message.answer("Your setting is corrupted, please try again.")
        return

    user_config["api_key"] = api_key
    save_user_config(user_id, user_config)

    await state.set_state(Form.Behavior)


@router.message(F.text.lower().in_(["start", "/start"]))
async def start_bot(message: Message):
    await message.answer(f"Hello, {message.from_user.first_name}", reply_markup=Keyboard())
    await asyncio.sleep(0.5)
    await message.answer('Let\'s start setting up AI Bot. Or, if you have already set up your bot, type "Hi" to start chatting.', reply_markup=setting())


@router.message(F.text == "Info")
async def button_info(message: Message):
    await message.answer("""
    
This bot lets you chat with an AI powered by OpenRouter.

Getting started:
1. Press "Start set up".
2. Create and enter your OpenRouter API key.
3. Describe how you want your AI to behave.
4. Start chatting.

Features:
• AI chat with conversation history
• Custom AI behavior/personality
• Web search support
• .txt file input
• Encrypted user data storage

Limits:
• Up to 10 requests per minute
• 2-second cooldown between requests
• Maximum behavior prompt: 1,000 characters
• Maximum .txt file size: 20 KB
• A maximum of 80 messages (from the AI and from you) in the entire history.
    """)

@router.message(F.text == "About")
async def button_about(message: Message):
    await message.answer("""
AI Bot is a personal Telegram AI assistant powered by OpenRouter.

The bot supports:
• Custom AI behavior
• Conversation history
• Web search
• .txt file processing
• Encrypted local data storage

Your API key and personal configuration are stored locally and encrypted.

Model:
dolphin-mistral-24b-venice-edition

Version:
1.0.1

Made for private AI conversations.
                         """)


async def _run_ai_request(message: Message, user_id: int, text: str):
    limit_result = await request_limiter.check_rate_limit(user_id)
    if not limit_result.allowed:
        wait = round(limit_result.retry_after, 1)
        await message.answer(f"Slow down — try again in {wait}s.")
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
            response = await asyncio.to_thread(generate_response, user_id, text)
            await message.answer(response)
        except ValueError as e:
            logger.warning("Bot configuration error for user %s: %s", user_id, e)
            await message.answer("Bot is not configured yet. Use /start to set up your API key and behavior.")
        except Exception:
            logger.exception("Failed to process bot message for user %s", user_id)
            await message.answer("Bot request failed. Please try again later.")


@router.message(F.document)
async def send_document_to_ai(message: Message, state: FSMContext, bot: Bot):
    current_state = await state.get_state()
    if current_state in {Form.API_Key.state, Form.Behavior.state}:
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
    if current_state in {Form.API_Key.state, Form.Behavior.state}:
        return

    await _run_ai_request(message, message.from_user.id, text)


@router.message()
async def handle_unsupported_content(message: Message):
    await message.answer("I can't accept files of this type. I can only accept .txt")
