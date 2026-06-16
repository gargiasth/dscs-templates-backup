# dscs_templates

A config-driven GDC (Genomic Data Commons) data pipeline template built for the Data Science Client Services team at Orion Workspaces. Designed to be reusable across GDC programs and projects by editing a single configuration file.

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



## Stack

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
└── database.py  ← set ACTIVE_DATABASE env variable to switch backends


**3. Set environment variables**

Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

**4. Run the pipeline**
```bash
python run_pipeline.py
```

Or run step by step via `testing_script.py`.

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

