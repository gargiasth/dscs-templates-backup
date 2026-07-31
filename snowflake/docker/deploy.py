# setup.py
## Docker compute setup
### Builds Docker images for the pipeline stack


import subprocess
import os
import logging
logger = logging.getLogger(__name__)

DOCKER_DIR = os.path.dirname(os.path.abspath(__file__))




def build_images() -> None:
    """Builds Docker images defined in docker-compose.yml."""
    try:
        result = subprocess.run(
            ["docker-compose", "build"],
            cwd=DOCKER_DIR,
            capture_output=True,
            text=True,
            check=True
        )
        logger.info(result.stdout)
    except Exception as e:
        logger.error(f"build_images failed: {e}")
        raise


def run_local() -> None:
    """Builds images and starts the full Docker Compose stack."""
    build_images()
    try:
        result = subprocess.run(
            ["docker-compose", "up", "-d"],
            cwd=DOCKER_DIR,
            capture_output=True,
            text=True,
            check=True
        )
        logger.info(result.stdout)
    except Exception as e:
        logger.error(f"run_local failed: {e}")
        raise