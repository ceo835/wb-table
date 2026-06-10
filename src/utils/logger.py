"""
Модуль логгирования проекта WB_table.

Предоставляет централизованную настройку логгера для всего проекта.
"""
import logging
import sys
from pathlib import Path
from datetime import datetime


def setup_logger(
    name: str = "wb_table",
    level: int = logging.INFO,
    log_file: str = None,
) -> logging.Logger:
    """
    Настроить и вернуть логгер.
    
    Args:
        name: Имя логгера
        level: Уровень логгирования
        log_file: Путь к файлу лога (опционально)
    
    Returns:
        Настроенный логгер
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Если логгер уже настроен, возвращаем его
    if logger.handlers:
        return logger
    
    # Формат сообщений
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Консольный обработчик
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Файловый обработчик (если указан файл)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


# Логгер по умолчанию
default_logger = setup_logger()


def get_logger(name: str) -> logging.Logger:
    """
    Получить логгер с указанным именем.
    
    Args:
        name: Имя логгера (обычно __name__ модуля)
    
    Returns:
        Логгер
    """
    return setup_logger(name=name)
