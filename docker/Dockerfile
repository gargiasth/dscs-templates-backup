# Dockerfile
## Builds a single image shared by webserver, daemon and streamlit services
### Dependencies installed before code copy to maximize layer caching

FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN pip install -e .
ENV DAGSTER_HOME=/opt/dagster/dagster_home
RUN mkdir -p $DAGSTER_HOME
COPY docker/dagster.yaml $DAGSTER_HOME/dagster.yaml
COPY docker/workspace.yaml $DAGSTER_HOME/workspace.yaml