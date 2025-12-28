"""
Structured logging configuration for telegram-assistant.
"""
import logging
import sys
from typing import Optional


def setup_logging(level: int = logging.INFO, name: str = 'telegram-assistant') -> logging.Logger:
    """
    Set up structured logging for the application.

    Args:
        level: Logging level (default: INFO)
        name: Logger name

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    # Console handler with formatting
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    formatter = logging.Formatter(
        fmt='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    return logger


# Create default logger
logger = setup_logging()


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger instance.

    Args:
        name: Optional sub-logger name (will be appended to 'telegram-assistant')

    Returns:
        Logger instance
    """
    if name:
        return logging.getLogger(f'telegram-assistant.{name}')
    return logger
