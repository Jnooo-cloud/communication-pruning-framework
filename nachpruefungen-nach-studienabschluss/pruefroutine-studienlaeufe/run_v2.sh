#!/bin/bash
# Z56 V2 (one run): V2a manifest first (create-only), then V2b-V2f audit over the manifest.
# Offline: network guard (sitecustomize from v1/netguard) and PATH shims; no model calls.
set -u
EVAL="/Users/jannikhiller/Desktop/ai operations/Studium OS/Masterarbeit/eval-harness/eval"
ROOT="/Users/jannikhiller/Desktop/ai operations/Studium OS/Masterarbeit"
RUN="$EVAL/runs/Z56-FRAMEWORK-VALIDIERUNG-001"
V2="$RUN/v2"
OUT="$V2/run-001"
SP="/private/tmp/claude-501/-Users-jannikhiller-Desktop-ai-operations-Studium-OS-Masterarbeit/5fb77503-5008-4c71-b140-0aa1fa8bbab2/scratchpad/z56-v1"
SYS_PY="/opt/anaconda3/bin/python3"
GUARD="$RUN/v1/netguard"
[ -e "$V2/MANIFEST.json" ] && { echo "manifest exists, refusing"; exit 2; }
[ -e "$OUT" ] && { echo "run folder exists, refusing"; exit 2; }
touch "$SP/marker-v2-start"
cd "$EVAL" || exit 2
export PATH="$GUARD/bin:$PATH"
export PYTHONPATH="$GUARD"
export Z56_NETGUARD_ANNOUNCE=1
export PYTHONPYCACHEPREFIX="$SP/pycache-v2-run"
stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }
LOG="$V2/run-v2.log"
{
  echo "start $(stamp)"
  echo "commit $(git rev-parse HEAD)"
  echo "sys_py $("$SYS_PY" -c 'import sys;print(sys.executable, sys.version.split()[0])')"
  echo "build_manifest_sha256 $(shasum -a 256 "$V2/build_manifest.py" | cut -d' ' -f1)"
  echo "audit_v2_sha256 $(shasum -a 256 "$V2/audit_v2.py" | cut -d' ' -f1)"
  echo "sitecustomize_sha256 $(shasum -a 256 "$GUARD/sitecustomize.py" | cut -d' ' -f1)"
  echo "git_status_framework_begin"
  git status --porcelain --untracked-files=all -- communication_pruning study_preparation tests
  echo "git_status_framework_end"
} > "$LOG" 2>&1

"$SYS_PY" -B -I - "$EVAL" "$RUN/manifest/framework-vorher.json" "$V2/framework-check-before.json" <<'PY'
import hashlib, json, sys
from pathlib import Path
root, manifest, out = Path(sys.argv[1]), json.load(open(sys.argv[2])), sys.argv[3]
diff = {k: "missing" if not (root / k).is_file() else "changed"
        for k, v in manifest.items()
        if not (root / k).is_file() or hashlib.sha256((root / k).read_bytes()).hexdigest() != v}
json.dump({"files": len(manifest), "differences": diff}, open(out, "w"), indent=1)
PY

echo "V2a_cmd: cd eval && PYTHONPATH=<guard> $SYS_PY runs/Z56-FRAMEWORK-VALIDIERUNG-001/v2/build_manifest.py" >> "$LOG"
echo "V2a_start $(stamp)" >> "$LOG"
Z56_NETGUARD_LOG="$V2/netguard-build.jsonl" "$SYS_PY" "$V2/build_manifest.py" > "$V2/build-stdout.txt" 2> "$V2/build-stderr.txt"
rc=$?
echo "V2a_rc $rc" >> "$LOG"
echo "V2a_end $(stamp)" >> "$LOG"
[ $rc -ne 0 ] && { echo "manifest build failed" >> "$LOG"; exit 3; }
echo "MANIFEST_sha256 $(shasum -a 256 "$V2/MANIFEST.json" | cut -d' ' -f1)" >> "$LOG"

echo "V2b_cmd: cd eval && PYTHONPATH=<guard> $SYS_PY runs/Z56-FRAMEWORK-VALIDIERUNG-001/v2/audit_v2.py run-001" >> "$LOG"
echo "V2b_start $(stamp)" >> "$LOG"
Z56_NETGUARD_LOG="$V2/netguard-audit.jsonl" "$SYS_PY" "$V2/audit_v2.py" run-001 > "$V2/audit-stdout.txt" 2> "$V2/audit-stderr.txt"
echo "V2b_rc $?" >> "$LOG"
echo "V2b_end $(stamp)" >> "$LOG"

"$SYS_PY" -B -I - "$EVAL" "$RUN/manifest/framework-vorher.json" "$V2/framework-check-after.json" <<'PY'
import hashlib, json, sys
from pathlib import Path
root, manifest, out = Path(sys.argv[1]), json.load(open(sys.argv[2])), sys.argv[3]
diff = {k: "missing" if not (root / k).is_file() else "changed"
        for k, v in manifest.items()
        if not (root / k).is_file() or hashlib.sha256((root / k).read_bytes()).hexdigest() != v}
json.dump({"files": len(manifest), "differences": diff}, open(out, "w"), indent=1)
PY
find "$EVAL" -newer "$SP/marker-v2-start" -type f -not -path "$RUN/*" 2>/dev/null > "$V2/modified-outside-z56.txt"
{
  echo "git_status_framework_after_begin"
  git status --porcelain --untracked-files=all -- communication_pruning study_preparation tests
  echo "git_status_framework_after_end"
  echo "end $(stamp)"
} >> "$LOG" 2>&1
echo done > "$V2/DONE"
