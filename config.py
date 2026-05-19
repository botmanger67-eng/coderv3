import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
    DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
    DEEPSEEK_CODER_MODEL = "deepseek-coder"
    DEEPSEEK_FLASH_MODEL = "deepseek-chat"
    MAX_TOKENS_CODER = 4000
    MAX_TOKENS_FLASH = 4000
    TEMPERATURE_CODER = 0.1
    TEMPERATURE_FLASH = 0.5
    DATABASE_PATH = "bot_sessions.db"
    MAX_PROJECTS_PER_HOUR = 5
    SELF_REVIEW_CODE = True
    AUTO_FIX_MISSING_FILES = True

config = Config()