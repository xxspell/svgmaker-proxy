from __future__ import annotations

import logging

import structlog

NOISY_LOGGERS: dict[str, int] = {
    "aiogoogle": logging.WARNING,
    "asyncio": logging.WARNING,
    "asyncpg": logging.WARNING,
    "httpcore": logging.WARNING,
    "httpx": logging.WARNING,
    "sqlalchemy": logging.WARNING,
    "sqlalchemy.engine": logging.WARNING,
    "sqlalchemy.pool": logging.WARNING,
    "watchfiles": logging.WARNING,
    "uvicorn.access": logging.INFO,
    "uvicorn.error": logging.INFO,
}


def configure_logging(log_level: str = "INFO") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )

    for logger_name, logger_level in NOISY_LOGGERS.items():
        logger = logging.getLogger(logger_name)
        logger.setLevel(logger_level)
        logger.propagate = True

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
