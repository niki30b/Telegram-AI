import asyncio, logging, sys
from datetime import datetime
from os import getenv
from pathlib import Path
from aiogram import Bot, Dispatcher
from dotenv import load_dotenv
from route import router


load_dotenv()


base_dir = Path(__file__).resolve().parent

logs_dir = base_dir / "logs"
crash_logs_dir = logs_dir / "crash_logs"

logs_dir.mkdir(parents=True, exist_ok=True)
crash_logs_dir.mkdir(parents=True, exist_ok=True)


start_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

log_file = logs_dir / f"{start_time}.log"
crash_log_file = crash_logs_dir / f"{start_time}_crash.log"

formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)




console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

file_handler = logging.FileHandler(
    log_file,
    encoding="utf-8"
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)


crash_handler = logging.FileHandler(
    crash_log_file,
    encoding="utf-8"
)
crash_handler.setLevel(logging.ERROR)
crash_handler.setFormatter(formatter)


logging.basicConfig(
    level=logging.INFO,
    handlers=[
        console_handler,
        file_handler,
        crash_handler
    ]
)

logger = logging.getLogger("Main") #name in logs




TOKEN = getenv("TOKEN_BOT")

dp = Dispatcher()
dp.include_router(router)


async def main():

    if not TOKEN:
        logger.critical("TOKEN_BOT is not set")
        raise RuntimeError("TOKEN_BOT is missing")

    bot = Bot(token=TOKEN)

    logger.info("Bot is starting...")
    logger.info("Bot token loaded: %s", bool(TOKEN))

    try:
        await dp.start_polling(bot)

    except Exception as e:
        logger.exception("Bot crashed\nReason: %s", e)
        raise

    finally:
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
