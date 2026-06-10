"""
Настройки проекта WB_table.

Загружает переменные окружения из .env файла и предоставляет
централизованный доступ к конфигурации.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_FILE)


def get_env_variable(name: str, required: bool = False, default: str = None) -> str:
    """
    Получить переменную окружения.
    
    Args:
        name: Имя переменной окружения
        required: Если True, переменная обязательна
        default: Значение по умолчанию (если required=False)
    
    Returns:
        Значение переменной окружения
    
    Raises:
        ValueError: Если переменная обязательна, но не найдена
    """
    value = os.getenv(name, default)
    
    if required and not value:
        raise ValueError(f"Переменная окружения {name} не найдена")
    
    return value


# Токены API
WB_TOKEN = get_env_variable("WB_TOKEN", required=False)
WB_ANALYTICS_TOKEN = get_env_variable("WB_ANALYTICS_TOKEN", required=False)
MPSTATS_API_TOKEN = get_env_variable("MPSTATS_API_TOKEN", required=False)
ENV = get_env_variable("ENV", required=False, default="dev")
DATABASE_URL = get_env_variable("DATABASE_URL", required=False)
ALLOW_PROD_DB = get_env_variable("ALLOW_PROD_DB", required=False, default="false")

# Google Sheets (поддержка разных имен переменных)
# Приоритет: GOOGLE_APPLICATION_CREDENTIALS, затем GOOGLE_CREDENTIALS_FILE
GOOGLE_APPLICATION_CREDENTIALS = (
    get_env_variable("GOOGLE_APPLICATION_CREDENTIALS", required=False)
    or get_env_variable("GOOGLE_CREDENTIALS_FILE", required=False)
)
# Приоритет: GOOGLE_SHEET_ID, затем GOOGLE_SPREADSHEET_ID
GOOGLE_SHEET_ID = (
    get_env_variable("GOOGLE_SHEET_ID", required=False)
    or get_env_variable("GOOGLE_SPREADSHEET_ID", required=False)
)

# Пути
DATA_RAW_DIR = BASE_DIR / "data" / "raw"
DATA_PROCESSED_DIR = BASE_DIR / "data" / "processed"

# Создаем директории если их нет
DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


class Settings:
    """Класс настроек проекта."""
    
    def __init__(self):
        self.env = ENV
        self.database_url = DATABASE_URL
        self.allow_prod_db = ALLOW_PROD_DB.lower() in {"1", "true", "yes", "on"}
        self.wb_token = WB_TOKEN
        self.wb_analytics_token = WB_ANALYTICS_TOKEN
        self.mpstats_api_token = MPSTATS_API_TOKEN
        self.google_application_credentials = GOOGLE_APPLICATION_CREDENTIALS
        self.google_sheet_id = GOOGLE_SHEET_ID
        self.data_raw_dir = DATA_RAW_DIR
        self.data_processed_dir = DATA_PROCESSED_DIR


settings = Settings()
