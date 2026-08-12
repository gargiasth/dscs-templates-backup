# deploy.py
## SPCS deployment
## ensure to change IMAGES dict based on ;pcal docker images
### Tags Docker images, pushes them to Snowflake registry,
### and creates SPCS services from spec yaml files

import os
import subprocess

import logging
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()

IMAGES = {
    "docker-webserver:latest": "webserver",
    "docker-daemon:latest":    "daemon",
    "postgres:15":             "postgres",
}



def _registry_path(image: str) -> str:
    return (
        f"{os.getenv('SNOWFLAKE_REGISTRY_URL')}/"
        f"{os.getenv('SNOWFLAKE_DATABASE')}/"
        f"{os.getenv('SNOWFLAKE_SCHEMA')}/"
        f"{os.getenv('SNOWFLAKE_IMAGE_REPO')}/"
        f"{image}:latest"
    ).lower()


def tag_images() -> None:
    """Tags local Docker images for the Snowflake registry."""
    for src, image in IMAGES.items():
        dst = _registry_path(image)
        logger.info(f"Tagging {src} → {dst}")
        try:
            result = subprocess.run(["docker", "tag", src, dst], capture_output=True, text=True, check=True)
            logger.info(result.stdout)
        except Exception as e:
            logger.error(f"Failed to tag {src} → {dst}: {e}")
            raise



def push_images() -> None:
    """Pushes tagged images to the Snowflake registry."""
    for image in IMAGES.values():
        dst = _registry_path(image)
        logger.info(f"Pushing {dst}")
        try:
            result = subprocess.run(["docker", "push", dst], capture_output=True, text=True, check=True)
            logger.info(result.stdout)
        except Exception as e:
            logger.error(f"Failed to push {dst}: {e}")
            raise


def run_services() -> None:
    """Creates SPCS services from yaml spec files."""
    from sqlalchemy import text
    from config.database import ACTIVE_ENGINE

    compute_pool = os.getenv("SNOWFLAKE_COMPUTE_POOL")
    spcs_dir     = os.path.dirname(os.path.abspath(__file__))
    services     = ["daemon", "webserver"]  # add services being used manually eg. postgres

    try:
        with ACTIVE_ENGINE.connect() as conn:
            for service in services:
                with open(os.path.join(spcs_dir, f"{service}.yaml"), "r") as f:
                    spec = f.read()
                sql = f"CREATE SERVICE IF NOT EXISTS {service} IN COMPUTE POOL {compute_pool} FROM SPECIFICATION $${spec}$$"
                conn.execute(text(sql))
                logger.info(f"Service {service} created")
    except Exception as e:
        logger.error(f"run_services failed: {e}")
        raise