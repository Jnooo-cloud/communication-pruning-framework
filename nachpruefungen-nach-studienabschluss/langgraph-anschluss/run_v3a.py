"""V3a: installed LangGraph/langchain-core files and framework files after all V3 runs vs. manifests."""
import sys

sys.dont_write_bytecode = True

from hashlib import sha256  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402
import time  # noqa: E402

V3 = Path(__file__).resolve().parent
RUN = V3.parent
EVAL = RUN.parents[1]


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def main():
    lg_manifest = json.loads((RUN / "manifest/langgraph-vorher.json").read_text())
    site = Path(lg_manifest["site"])
    lg_now = {k: digest(site / k) for k in lg_manifest["files"]}
    py_now = sorted(str(p.relative_to(site)) for pkg in ("langgraph", "langchain_core") for p in (site / pkg).rglob("*.py"))
    reference = V3 / "netguard.py"                      # first V3 file, created before any V3 run
    newer_site = sorted(str(p.relative_to(site)) for pkg in ("langgraph", "langchain_core")
                        for p in (site / pkg).rglob("*") if p.is_file() and p.stat().st_mtime > reference.stat().st_mtime)
    fw_manifest = json.loads((RUN / "manifest/framework-vorher.json").read_text())
    fw_now = {k: digest(EVAL / k) for k in fw_manifest}
    newer_framework = sorted(str(p.relative_to(EVAL)) for d in ("communication_pruning", "study_preparation", "tests")
                             for p in (EVAL / d).rglob("*") if p.is_file() and p.stat().st_mtime > reference.stat().st_mtime)
    result = {
        "epoch": time.time(), "site": str(site), "reference_file_mtime": reference.stat().st_mtime,
        "langgraph": {"files_in_manifest": len(lg_manifest["files"]),
                      "changed": sorted(k for k in lg_manifest["files"] if lg_now[k] != lg_manifest["files"][k]),
                      "py_files_now": len(py_now), "new_py_files": sorted(set(py_now) - set(lg_manifest["files"])),
                      "files_modified_since_v3_start": newer_site},
        "framework": {"files_in_manifest": len(fw_manifest),
                      "changed": sorted(k for k in fw_manifest if fw_now[k] != fw_manifest[k]),
                      "files_modified_since_v3_start": newer_framework},
        "langgraph_version_files": {name: digest(p) for name, p in (
            ("langgraph/graph/state.py", site / "langgraph/graph/state.py"),
            ("langgraph/pregel/_runner.py", site / "langgraph/pregel/_runner.py"))},
    }
    result["langgraph_unchanged"] = not result["langgraph"]["changed"] and not result["langgraph"]["new_py_files"] \
        and not newer_site
    result["framework_unchanged"] = not result["framework"]["changed"]
    out = V3 / "out/v3a/RESULT.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x") as handle:
        json.dump(result, handle, indent=1)
        handle.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "langgraph_version_files"}, indent=1))
    return result


if __name__ == "__main__":
    os.chdir(EVAL)
    main()
