"""Preserve exact own/original source and run all preplanned Z31 checks."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import zipfile

base = Path(__file__).resolve().parent
root = base.parents[1]
project = root.parents[1]
folder = base / sys.argv[1]
folder.mkdir()
cache = base / "cache"
cache.mkdir(exist_ok=True)

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(name, value):
    with (folder / name).open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")

original_manifest = json.loads((base / "original-manifest.json").read_text())
for name, metadata in original_manifest["files"].items():
    assert sha(base / "original" / name) == metadata["sha256"], name
files = sorted([p for section in ("communication_pruning", "tests") for p in (root / section).rglob("*")
                if p.is_file() and "__pycache__" not in p.parts])
files += [root / "README.md", project / "project/dsr/Z31-PRUNING-PLAN.md", project / "project/ENTWICKLUNGSSTEUERUNG.json",
          project / "project/FORSCHUNGSDESIGN-KONSOLIDIERT-2026-09-05.md"]
files += [p for p in base.iterdir() if p.is_file() and p.suffix in (".py", ".json", ".txt")]
manifest = {str(p.relative_to(project)): {"bytes": p.stat().st_size, "sha256": sha(p)} for p in files}
with zipfile.ZipFile(folder / "own-source.zip", "x", zipfile.ZIP_DEFLATED) as archive:
    for p in files: archive.write(p, str(p.relative_to(project)))
save("own-source-manifest.json", manifest)
save("started.json", {"utc": datetime.now(timezone.utc).isoformat(), "python": sys.version, "executable": sys.executable,
    "source_archive_sha256": sha(folder / "own-source.zip"), "original_archive_sha256": sha(base / "original-source.zip"),
    "wheel_manifest_sha256": sha(base / "wheel-download-receipt.json"),
    "run_scope": "three synthetic original-framework cases; separate stdlib verification; regression tests"})
env = {key: os.environ[key] for key in ("PATH", "TMPDIR", "LANG") if key in os.environ}
env.update(PYTHONPATH=os.pathsep.join((str(root), str(base / "original"), str(base / "runtime"), "/private/tmp/masterarbeit-z15-runtime")),
    PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTHONHASHSEED="0", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
    MPLBACKEND="Agg", MPLCONFIGDIR=str(cache))
commands = [[sys.executable, str(base / "case.py"), str(folder / case), case] for case in ("dense", "pruned", "failed_b")]
commands += [[sys.executable, str(base / "verify.py"), str(folder), str(base / "original")],
             [sys.executable, str(base / "tests.py")]]
runs = []
for number, command in enumerate(commands, 1):
    with (folder / f"{number}-stdout.log").open("x") as out, (folder / f"{number}-stderr.log").open("x") as err:
        result = subprocess.run(command, cwd=root, env=env, stdout=out, stderr=err)
    runs.append({"command": command, "exit_code": result.returncode})
    if result.returncode: break
own_unchanged = all(sha(p) == manifest[str(p.relative_to(project))]["sha256"] for p in files)
original_unchanged = all(sha(base / "original" / name) == meta["sha256"] for name, meta in original_manifest["files"].items())
save("receipt.json", {"finished_utc": datetime.now(timezone.utc).isoformat(), "runs": runs,
    "own_sources_unchanged": own_unchanged, "original_sources_unchanged": original_unchanged,
    "outputs": {str(p.relative_to(folder)): sha(p) for p in sorted(folder.rglob("*")) if p.is_file()}})
print(json.dumps({"folder": str(folder), "runs": runs, "own_sources_unchanged": own_unchanged, "original_sources_unchanged": original_unchanged}))
assert own_unchanged and original_unchanged and len(runs) == 5 and all(row["exit_code"] == 0 for row in runs)
