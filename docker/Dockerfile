FROM python:3.11-slim

WORKDIR /app

COPY docker/requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the whole spcs/ folder — the script's sys.path.insert() needs
# utils_snowflake/ sitting right next to ingestion/, same relative
# layout as it has locally.
COPY spcs/ /app/spcs/
COPY src/python_etl/ /app/python_etl/
ENTRYPOINT ["python"]