"""
generate_procedures.py

Reads a job's config YAML and generates the CREATE OR REPLACE
PROCEDURE statement for it — one generator, every hard-won fix from
this project baked in, so no future job can silently reintroduce a
bug already found and fixed once.
"""
import yaml


def build_procedure_sql(yaml_path: str) -> str:
    with open(yaml_path, "r") as f:
        config = yaml.safe_load(f)

    procedure_name = config["procedure_name"]
    compute_pool = config["compute_pool"]
    is_async = config.get("async", False)
    eai_list = config.get("external_access_integrations", [])

    spec_yaml = yaml.dump({"spec": config["spec"]}, default_flow_style=False, sort_keys=False)

    async_clause = "ASYNC = TRUE" if is_async else ""
    eai_clause = f"EXTERNAL_ACCESS_INTEGRATIONS = ({', '.join(eai_list)})" if eai_list else ""

    return f'''CREATE OR REPLACE PROCEDURE {procedure_name}(sample_number NUMBER)


RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.10'
HANDLER = 'run'
PACKAGES = ('snowflake-snowpark-python')
AS
$$
import time

def run(session, sample_number):
    spec = f"""
{spec_yaml.replace("<SAMPLE_NUMBER>", "{sample_number}")}
"""
    job_name = f"{procedure_name}_{{sample_number}}_{{int(time.time())}}"
    escaped_spec = spec.replace("'", "''")
    sql = f"""
        EXECUTE JOB SERVICE
          IN COMPUTE POOL {compute_pool}
          NAME = {{job_name}}
          {async_clause}
          {eai_clause}
          FROM SPECIFICATION '{{escaped_spec}}'
    """
    session.sql(sql).collect()
    return f"Started {{job_name}} for sample {{sample_number}}"
$$;'''


if __name__ == "__main__":
    import sys
    sql = build_procedure_sql(sys.argv[1])
    print(sql)