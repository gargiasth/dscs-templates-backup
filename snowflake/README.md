
# dscs_templates

A collection of configurable pipeline templates for Orion Workspaces designed to help teams quickly configure, modernize, and migrate existing data pipelines across platforms.
The repository provides reusable patterns for ingestion, validation, transformation, orchestration, and deployment so that data science and data engineering teams can move pipelines between local development, cloud platforms, data warehouses, lakehouse environments, and client-specific research systems with minimal refactoring.

(The initial reference implementation includes a config-driven GDC Genomic Data Commons pipeline using a TCGA-BRCA example.)


## Overview

This template implements a medallion architecture (Bronze → Silver → Gold) for ingesting and transforming clinical data from the GDC REST API. It ships with a working TCGA-BRCA example that scientists can use as a reference when configuring their own pipelines.

## Architecture

GDC REST API

↓

Bronze Landing  ← raw GDC default response, schema inferred

↓

Bronze          ← explicit field mappings, no constraints

↓

Silver          ← cleaned, deduplicated, pk enforced

↓

Gold            ← joined mastertable, ready for analysis



## Current Stack

- **Orchestration** — Dagster
- **Databases** — DuckDB (local), PostgreSQL, Snowflake (interchangeable)
- **Transforms** — pandas
- **Validation** — pandera
- **Visualization** — Streamlit

## Getting Started

**1. Install dependencies**
```bash
pip install -r requirements.txt
pip install -e .
```

**2. Configure your pipeline**

All configuration lives in one place:


config/

├── api.py       ← GDC API endpoints

├── fields.py    ← field mappings, pk, fk per entity — edit this

├── schemas.py   ← derived automatically from fields.py

├── database.py  ← set ACTIVE_DATABASE to switch backends

└── compute.py   ← set ACTIVE_COMPUTE to switch deployment targets

Runtime configuration (credentials, switches) lives in `.env`:

```
cp .env.example .env
```
**3. Set environment variables**

Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```
All runtime configuration is done in `.env`. The two key switches:

| Variable | Options | Description |
|----------|---------|-------------|
| `ACTIVE_DATABASE` | `duckdb` \| `postgres` \| `snowflake` | Where pipeline data is stored |
| `ACTIVE_COMPUTE` | `local` \| `docker` \| `spcs` | Where the pipeline runs |

**4. Run the pipeline**
```bash
python run_pipeline.py
```


**5. Start the Dagster UI**
```bash
dagster dev
```

Open http://localhost:3000 to monitor pipeline runs.

## Project Structure
├── config/          ← field mappings, schemas, database setup

├── ingestion/       ← GDC API fetch and response parsing

├── transforms/      ← silver cleaning, gold joining

├── utils/           ← helper functions

├── validation/      ← pandera data validation

├── dagster/         ← orchestration layer (assets, definitions)

├── docker/          ← Dockerfile, dagster.yaml

├── snowflake/       ← Snowflake deployment config

├── streamlit/       ← data explorer UI

├── pipeline.py      ← orchestration-agnostic pipeline logic

└── run_pipeline.py  ← entry point for local runs

