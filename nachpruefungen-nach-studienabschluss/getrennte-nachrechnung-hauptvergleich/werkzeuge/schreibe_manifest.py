"""Schreibt eingang/MANIFEST.sha256 über alle Dateien in eingang/ außer sich selbst."""
import hashlib
from pathlib import Path

EINGANG = Path(__file__).resolve().parent.parent / "eingang"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


dateien = sorted(p.relative_to(EINGANG).as_posix() for p in EINGANG.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256")
with open(EINGANG / "MANIFEST.sha256", "w", encoding="utf-8", newline="\n") as f:
    for rel in dateien:
        f.write(f"{sha(EINGANG / rel)}  {rel}\n")
print(len(dateien), "Dateien; MANIFEST.sha256", sha(EINGANG / "MANIFEST.sha256"))
