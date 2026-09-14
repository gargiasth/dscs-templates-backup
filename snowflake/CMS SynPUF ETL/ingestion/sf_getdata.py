"""
download_and_stage_synpuf.py

Downloads SynPUF files from CMS and stages them on Snowflake — entirely
in memory, nothing ever written to disk. Runs either locally (using
.env credentials) or inside an SPCS container (using the auto-provisioned
OAuth token) — get_connection() detects which and picks the right one.

Usage:
    python download_and_stage_synpuf.py <sample_number> [sample_number ...]
    python download_and_stage_synpuf.py all
"""
import io
import os
import sys
import urllib.request
import zipfile

from dotenv import load_dotenv

_snowflake_root = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0])))
sys.path.insert(0, _snowflake_root)

from utils_snowflake.connection import get_connection, get_snowpark_session

URL_WWW_CMS_GOV = "www.cms.gov/Research-Statistics-Data-and-Systems/Downloadable-Public-Use-Files/SynPUFs/Downloads"
URL_DOWNLOADS_CMS_GOV = "downloads.cms.gov/files"

SYNPUF_FILES = [
    [URL_WWW_CMS_GOV,       "DE1_0_2008_Beneficiary_Summary_File_Sample_~~.zip"],
    [URL_DOWNLOADS_CMS_GOV, "DE1_0_2008_to_2010_Carrier_Claims_Sample_~~A.zip"],
    [URL_DOWNLOADS_CMS_GOV, "DE1_0_2008_to_2010_Carrier_Claims_Sample_~~B.zip"],
    [URL_WWW_CMS_GOV,       "DE1_0_2008_to_2010_Inpatient_Claims_Sample_~~.zip"],
    [URL_WWW_CMS_GOV,       "DE1_0_2008_to_2010_Outpatient_Claims_Sample_~~.zip"],
    [URL_DOWNLOADS_CMS_GOV, "DE1_0_2008_to_2010_Prescription_Drug_Events_Sample_~~.zip"],
    [URL_WWW_CMS_GOV,       "DE1_0_2009_Beneficiary_Summary_File_Sample_~~.zip"],
    [URL_WWW_CMS_GOV,       "DE1_0_2010_Beneficiary_Summary_File_Sample_~~.zip"],
]
# Beneficiary years and Carrier parts both stage as separate raw files,
# uncombined — FileControl.py (the OHDSI ETL) builds the combined
# versions itself, on demand, when it actually runs.


def build_file_url(base_url, sp_file, sample_number):
    sp_file = sp_file.replace("~~", str(sample_number))
    if sp_file == "DE1_0_2008_to_2010_Carrier_Claims_Sample_11A.zip":
        sp_file = "DE1_0_2008_to_2010_Carrier_Claims_Sample_11A.csv.zip"
    if base_url == URL_DOWNLOADS_CMS_GOV:
        file_url = f"http://{base_url}/{sp_file}"
    else:
        file_url = f"https://{base_url}/{sp_file}"
    if sp_file == "DE1_0_2010_Beneficiary_Summary_File_Sample_1.zip":
        file_url = "https://www.cms.gov/Research-Statistics-Data-and-Systems/Statistics-Trends-and-Reports/SynPUFs/Downloads/DE1_0_2010_Beneficiary_Summary_File_Sample_20.zip"
    if ".csv.zip" in sp_file:
        sp_file = sp_file.replace(".csv.zip", ".zip")
    return file_url, sp_file


def run(session, sample_number, schema_name, stage_name):
    files_staged = 0

    for base_url, sp_file in SYNPUF_FILES:
        file_url, sp_file = build_file_url(base_url, sp_file, sample_number)

        with urllib.request.urlopen(file_url) as response:
            zip_bytes = response.read()

        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        for name in zf.namelist():
            data = zf.read(name)
            clean_name = name.replace(" - Copy.csv", ".csv")

            stage_location = f"@{schema_name}.{stage_name}/DE_{sample_number}/{clean_name}"
            session.file.put_stream(io.BytesIO(data), stage_location, auto_compress=False, overwrite=False)
            files_staged += 1

    return f"Sample {sample_number}: staged {files_staged} files"


def parse_sample_range():
    if len(sys.argv) < 2:
        print("Usage: python download_and_stage_synpuf.py <sample_number> [sample_number ...] | all")
        sys.exit(1)
    if "all" in sys.argv[1:]:
        return list(range(1, 21))
    samples = []
    for arg in sys.argv[1:]:
        n = int(arg)
        if n < 1 or n > 20:
            raise ValueError(f"Invalid sample number: {n}. Must be 1..20.")
        samples.append(n)
    return samples


if __name__ == "__main__":
    load_dotenv()  # no-op inside SPCS (no .env file there); still needed for local runs
    sample_range = parse_sample_range()
    print(f"Sample range: {sample_range}")

    database = os.environ["SNOWFLAKE_DATABASE"]
    schema = os.environ["SNOWFLAKE_BRONZE_SCHEMA"]
    stage = os.environ["SNOWFLAKE_RAW_SYNPUF_STAGE"]

    conn = get_connection()
    try:
        session = get_snowpark_session(conn)
        session.sql(f"USE DATABASE {database}").collect()
        session.sql(f"USE SCHEMA {schema}").collect()

        for sample_number in sample_range:
            result = run(session, sample_number, schema, stage)
            print(result)

        session.close()
    finally:
        conn.close()

    print("Done.")