FROM python:3.11-slim
WORKDIR /app
COPY docker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY ["snowflake/CMS SynPUF ETL/", "/app/"]
COPY ["src/CMS SynPUF ETL/python_etl/", "/app/src/python_etl/"]
ENTRYPOINT ["python"]