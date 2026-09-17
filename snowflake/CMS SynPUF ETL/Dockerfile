FROM python:3.11-slim

WORKDIR /app

COPY docker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app/
COPY --from=shared_src src/python_etl/ /app/python_etl/

ENTRYPOINT ["python"]