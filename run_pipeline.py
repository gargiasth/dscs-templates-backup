from pipeline import (
    run_setup,
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


def main():
    # Setup
    run_setup()

# Bronze landing
print("\n--- Bronze Landing ---")
default_hits = fetch_default()
run_create_bronze_landing_table(default_hits)
run_bronze_landing()

# Bronze
print("\n--- Bronze ---")
hits = run_bronze_request_api()
run_create_bronze_tables()
run_bronze_cases(hits)
run_bronze_samples(hits)
run_bronze_slides(hits)

# Silver
print("\n--- Silver ---")
run_create_silver_tables()
run_silver_cases()
run_silver_samples()

# Gold
print("\n--- Gold ---")
run_create_gold_tables()
run_gold_mastertable()

print("\nPipeline complete")