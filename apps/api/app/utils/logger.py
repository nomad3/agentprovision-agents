"""Logging utility for AgentProvision API"""

import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger instance

    Args:
        name: Logger name (typically __name__ of the module)

    Returns:
        Configured logger
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger
