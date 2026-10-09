# logger.py
## Centralized logging configuration
### Import setup_logging() once at the entry point of your pipeline
### All modules get a logger via logging.getLogger(__name__)

import logging

def setup_logging(level: int = logging.INFO) -> None:
    """Configures the root logger with a consistent format across the pipeline."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )