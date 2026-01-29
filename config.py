import os
import sys
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
DEFAULT_TIMEZONE: str = os.getenv("DEFAULT_TIMEZONE", "Europe/Moscow")
DB_PATH: str = os.getenv("DB_PATH", "bot.db")
LOG_FILE: str = os.getenv("LOG_FILE", "bot.log")

if not TELEGRAM_BOT_TOKEN:
    print("TELEGRAM_BOT_TOKEN is not set. Exiting.")
    sys.exit(1)
