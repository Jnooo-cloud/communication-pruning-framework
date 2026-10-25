from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import zipfile

run = Path(__file__).resolve().parents[1]
root = Path(__file__).resolve().parents[5]
folder = run / 'coordinator'
files = sorted(p for p in run.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
files += sorted((root / 'eval-harness/eval/communication_pruning').glob('*.py'))
files += [root / 'project/dsr/Z37-MESSABNAHME-PLAN.md']
rows = []
with zipfile.ZipFile(folder / 'source-001.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
    for path in files:
        member = str(path.relative_to(root))
        archive.write(path, member)
        rows.append({'path': member, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
record = {'before_reconciliation': True, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
          'first_coordinator_private_read': 'After final S3 handoff; S3 frozen at 09:13:52 UTC, 2026-09-13',
          'archive': 'source-001.zip', 'files': rows,
          'archive_sha256': hashlib.sha256((folder / 'source-001.zip').read_bytes()).hexdigest()}
with (folder / 'source-manifest.json').open('x') as f:
    json.dump(record, f, ensure_ascii=False, indent=2)
    f.write('\n')
print({'files': len(rows), 'archive_sha256': record['archive_sha256']})
