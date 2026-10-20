"""Wrapper for stage: bronze — entry-point: get_synpuf_files.py"""
import os, re, subprocess, sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCRIPT = _REPO_ROOT / "src/CMS SynPUF ETL/scripts/get_synpuf_files.py"

env  = dict(os.environ)
args = []
for a in sys.argv[1:]:
    m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", a)
    if m:
        env[m.group(1)] = m.group(2)
    else:
        args.append(a)

subprocess.run([sys.executable, str(_SCRIPT), *args], env=env, check=True)
