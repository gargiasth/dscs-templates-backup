"""Wrapper for stage: bronze — entry-point: get_synpuf_files.py"""
import subprocess, sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCRIPT = _REPO_ROOT / "src/CMS SynPUF ETL/scripts/get_synpuf_files.py"

subprocess.run([sys.executable, str(_SCRIPT), *sys.argv[1:]], check=True)
