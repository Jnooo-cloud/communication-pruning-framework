"""Capture recoverable public inputs and unchanged instrument before its run."""
from pathlib import Path
import hashlib
import json
import platform
import sys
import zipfile

here = Path(__file__).resolve().parent
run = here.parent
root = run.parents[3]
code = root / 'eval-harness/eval/communication_pruning'
files = [here / 'run_instrument.py', Path(__file__), run / 'contract.md',
         root / 'project/dsr/Z37-MESSABNAHME-PLAN.md']
files += [code / name for name in ('__init__.py', 'audit.py', 'journal.py',
                                   'contracts.py', 'failure_policy.py')]
for folder in ('view1', 'view2'):
    files += sorted(p for p in (run / folder).rglob('*') if p.is_file())
if len(list((run / 'view1').glob('*/case.json'))) != 12:
    raise RuntimeError('public case set not complete')
archive_path = here / 'source-001.zip'
with zipfile.ZipFile(archive_path, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for path in files:
        archive.write(path, str(path.relative_to(root)))
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
manifest = {'archive': archive_path.name, 'archive_sha256': digest(archive_path),
            'files': [{'path': str(p.relative_to(root)), 'sha256': digest(p)} for p in files],
            'python': sys.version, 'executable': sys.executable, 'platform': platform.platform(),
            'before_instrument_execution': True, 'no_private_expectations_read': True}
with (here / 'source-manifest.json').open('x') as out:
    json.dump(manifest, out, indent=2, ensure_ascii=False)
    out.write('\n')
print(json.dumps({'bound_files': len(files), 'archive_sha256': manifest['archive_sha256']}))
