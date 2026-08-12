from pipeline import (
    run_setup,
    run_setup_compute,
    run_create_bronze_landing_table,
    run_bronze_landing,
    run_bronze_request_api,
    run_create_bronze_tables,
    run_bronze_cases,
    run_bronze_samples,
    run_bronze_slides,
    run_create_silver_tables,
    run_silver_cases,
    run_silver_samples,
    run_create_gold_tables,
    run_gold_mastertable,
)
from ingestion.fetch import fetch_default


import logging
logger = logging.getLogger(__name__)


def main():
    # Setup
    logger.info("\n--- Run Set Up ---")
    run_setup()

    run_setup_compute() # Runs on when setting/updating images

    # Bronze landing
    logger.info("\n--- Bronze Landing ---")
    default_hits = fetch_default()
    run_create_bronze_landing_table(default_hits)
    run_bronze_landing()

    # Bronze
    logger.info("\n--- Bronze ---")
    hits = run_bronze_request_api()
    run_create_bronze_tables()
    run_bronze_cases(hits)
    run_bronze_samples(hits)
    run_bronze_slides(hits)

    # Silver
    logger.info("\n--- Silver ---")
    run_create_silver_tables()
    run_silver_cases()
    run_silver_samples()

    # Gold
    logger.info("\n--- Gold ---")
    run_create_gold_tables()
    run_gold_mastertable()

    logger.info("\nPipeline complete")

if __name__ == "__main__":
    main()