import logging


def get_logger(prefix: str) -> logging.Logger:
    logger = logging.getLogger(prefix)
    if not logger.handlers:
        handler = logging.StreamHandler()
        fmt = logging.Formatter(
            f"%(asctime)s [{prefix}] %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger
