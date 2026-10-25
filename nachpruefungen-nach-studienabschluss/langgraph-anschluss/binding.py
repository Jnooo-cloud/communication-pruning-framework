"""Source binding written at the start of each V3 run (hashes of the V3 code actually executed)."""
from hashlib import sha256
from pathlib import Path
import json
import sys
import time

V3 = Path(__file__).resolve().parent
CORE = ("netguard.py", "common.py", "lg_adapter.py", "backends.py", "binding.py", "tests/test_v3_adapter.py")


def bind(folder, *extra):
    names = list(CORE) + [e for e in extra if e not in CORE]
    record = {"epoch": time.time(), "python": sys.version, "executable": sys.executable,
              "files": {n: sha256((V3 / n).read_bytes()).hexdigest() for n in names}}
    path = Path(folder) / "SOURCES.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as out:
        json.dump(record, out, indent=1)
        out.write("\n")
    return record
