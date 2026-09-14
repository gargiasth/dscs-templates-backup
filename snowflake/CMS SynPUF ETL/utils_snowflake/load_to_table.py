"""
Loads staged files into Snowflake tables via COPY INTO — entirely
server-side, no data pulled through local memory. The counterpart to
upload_to_stage.py, which moves data the other direction.
"""


def ensure_file_format(conn, schema: str, format_name: str, file_type: str = "CSV", **options) -> None:
    """
    Creates a reusable file format if it doesn't already exist.
    file_type: "CSV", "JSON", "PARQUET", "AVRO", "ORC", "XML"
    options: any FILE FORMAT parameters valid for that type, e.g.
             field_delimiter=',', skip_header=1, null_if=['']
    """
    option_lines = []
    for key, value in options.items():
        if isinstance(value, list):
            formatted = "(" + ", ".join(f"'{v}'" for v in value) + ")"
        elif isinstance(value, str):
            formatted = f"'{value}'"
        else:
            formatted = str(value)
        option_lines.append(f"{key.upper()} = {formatted}")

    options_sql = "\n  ".join(option_lines)
    cur = conn.cursor()
    cur.execute(f"""
        CREATE FILE FORMAT IF NOT EXISTS {schema}.{format_name}
          TYPE = {file_type}
          {options_sql}
    """)


def copy_into_table(conn, stage_path: str, target_schema: str, target_table: str,
                     file_format_schema: str, file_format_name: str,
                     on_error: str = "ABORT_STATEMENT") -> list:
    """
    Loads one staged file into one table. Works for any file type,
    provided file_format_name refers to a format already created via
    ensure_file_format() with the matching TYPE.
    stage_path: full reference, e.g. "@silver_schema.stage_name/output/person_1.csv"
    """
    cur = conn.cursor()
    cur.execute(f"""
        COPY INTO {target_schema}.{target_table}
        FROM {stage_path}
        FILE_FORMAT = (FORMAT_NAME = {file_format_schema}.{file_format_name})
        ON_ERROR = '{on_error}'
    """)
    return cur.fetchall()