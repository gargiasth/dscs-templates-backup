FROM python:3.11-slim

WORKDIR /app

COPY docker/requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the whole snowflake/ folder — the script's sys.path.insert() needs
# utils_snowflake/ sitting right next to ingestion/, same relative
# layout as it has locally.
COPY snowflake/CMS SynPUF ETL/ /app/
COPY src/CMS SynPUF ETL/python_etl/ /app/python_etl/
ENTRYPOINT ["python"]