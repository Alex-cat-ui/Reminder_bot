import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
DEFAULT_TIMEZONE: str = os.getenv("DEFAULT_TIMEZONE", "Europe/Moscow")
DB_PATH: str = os.getenv("DB_PATH", "bot.db")
LOG_FILE: str = os.getenv("LOG_FILE", "bot.log")
REDIS_DSN: str = os.getenv("REDIS_DSN", "")
FSM_TTL_SECONDS: int = int(os.getenv("FSM_TTL_SECONDS", "172800"))
ADMIN_USER_IDS: set[int] = {
    int(x.strip())
    for x in os.getenv("ADMIN_USER_IDS", "").split(",")
    if x.strip().isdigit()
}
