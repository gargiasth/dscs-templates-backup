"""
run_etl.py

Sets the environment variables CMS_SynPuf_ETL_CDM_v5.py needs, then
runs it unchanged. Replaces the hardcoded
dotenv.load_dotenv("/Volumes/...") that used to live inside the ETL
script itself — that line made the script Databricks-specific, which
broke the "upstream code stays untouched" rule. This wrapper is where
platform-specific configuration belongs instead.

Usage:
    python run_etl.py <sample_number> <synpuf_dir> <vocab_dir> <control_dir> <output_dir>
"""
import os
import subprocess
import sys

sample_number, synpuf_dir, vocab_dir, control_dir, output_dir = sys.argv[1:6]

etl_env = os.environ.copy()
etl_env["BASE_SYNPUF_INPUT_DIRECTORY"] = synpuf_dir
etl_env["BASE_OMOP_INPUT_DIRECTORY"] = vocab_dir
etl_env["BASE_ETL_CONTROL_DIRECTORY"] = control_dir
etl_env["BASE_OUTPUT_DIRECTORY"] = output_dir
etl_env["SYNPUF_DIR_FORMAT"] = "DE_{0}"

_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0]))))
etl_script = os.path.join(_repo_root, "src", "python_etl", "CMS_SynPuf_ETL_CDM_v5.py")

subprocess.run([sys.executable, etl_script, sample_number], env=etl_env, check=True)