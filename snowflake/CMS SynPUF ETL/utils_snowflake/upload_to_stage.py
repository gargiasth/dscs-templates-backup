"""
Uploads every file in a local directory (recursively) to a Snowflake
stage via PUT. Snowflake's PUT defaults to OVERWRITE=FALSE — files
already staged are skipped, not re-uploaded — so this is safe to
call repeatedly without duplicating work.
"""
import os
import io

def upload_directory_to_stage(session, schema: str, stage: str, local_dir: str, prefix: str = "") -> int:
    count = 0
    for root, dirs, files in os.walk(local_dir):
        for filename in files:
            local_path = os.path.join(root, filename)
            with open(local_path, "rb") as f:
                data = f.read()
            stage_path = f"{prefix}/{filename}" if prefix else filename
            upload_bytes_to_stage(session, schema, stage, stage_path, data)
            count += 1
    return count




def upload_bytes_to_stage(session, schema: str, stage: str, stage_path: str, data: bytes) -> None:
    """
    Uploads in-memory bytes directly to a stage via Snowpark's
    put_stream — no local file at any point.
    """
    buffer = io.BytesIO(data)
    stage_location = f"@{schema}.{stage}/{stage_path}"
    result = session.file.put_stream(buffer, stage_location, auto_compress=False, overwrite=False)
    print(f"  staged {stage_path}: {result}")