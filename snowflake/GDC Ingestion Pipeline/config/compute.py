# config/compute.py
## Active compute configuration
### Reads ACTIVE_COMPUTE from environment and exposes a deploy() function
### deploy() enforces the correct order of operations for each compute target
### Supported compute targets: local, docker, spcs


import os
import logging
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()

ACTIVE_COMPUTE = os.getenv("ACTIVE_COMPUTE", "local")  # local | docker | spcs

def setup_compute() -> None:
    logger.info("\n--- Setting Up Compute ---")
    if ACTIVE_COMPUTE == "local":
        logger.info("Used local")

        # pass  # no extra setup needed

    elif ACTIVE_COMPUTE == "docker":
        from docker.deploy import run_local
        run_local()
        logger.info("Compute setup complete — images deployed to docker")
        # expose whatever docker-specific helpers make sense

    elif ACTIVE_COMPUTE == "spcs":
        from docker.deploy import build_images
        from spcs.deploy import tag_images, push_images
        

        def deploy() -> None:
            """Builds Docker images, then tags and pushes to Snowflake registry."""
            build_images()   # prerequisite — must run before tag/push
            tag_images()
            push_images()
            logger.info("Compute setup complete — images deployed to Snowflake registry")
        deploy()
    else:
        raise ValueError(f"Unknown ACTIVE_COMPUTE: '{ACTIVE_COMPUTE}'.")
