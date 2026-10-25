"""Bind creator sources and the installed stdlib runtime before case generation.

Archive operation only. Does not import or run the artifact or the generator.
The macOS system libraries remain a declared platform dependency.
"""
from pathlib import Path
import hashlib
import json
import os
import platform
import sys
import sysconfig
import zipfile

HERE = Path(__file__).resolve().parent
RUN = HERE.parent
EVAL = RUN.parents[1]
ROOT = EVAL.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x') as out:
        json.dump(value, out, indent=2, ensure_ascii=False, allow_nan=False)
        out.write('\n')


def main():
    runtime = {
        'executable': sys.executable, 'executable_resolved': str(Path(sys.executable).resolve()),
        'version': sys.version, 'prefix': sys.prefix, 'base_prefix': sys.base_prefix,
        'platform': platform.platform(), 'machine': platform.machine(),
        'stdlib': sysconfig.get_path('stdlib'),
        'constraint': 'Installed macOS arm64 runtime; OS dynamic libraries are not redistributed. Restore recorded paths or provide equivalent framework loading. No cross-platform portability claim.',
        'external_packages_used': [], 'PYTHONDONTWRITEBYTECODE': '1',
    }
    save(HERE / 'runtime.json', runtime)
    runtime_files = [Path(sys.executable).resolve(), Path(sys.prefix) / 'Python']
    stdlib = Path(sysconfig.get_path('stdlib'))
    runtime_files += sorted(p for p in stdlib.rglob('*') if p.is_file()
                            and not {'site-packages', '__pycache__'} & set(p.relative_to(stdlib).parts)
                            and p.suffix not in ('.pyc', '.pyo'))
    runtime_rows = []
    with zipfile.ZipFile(HERE / 'runtime-001.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in dict.fromkeys(runtime_files):
            name = str(path).lstrip('/')
            archive.write(path, name)
            runtime_rows.append({'path': str(path), 'member': name, 'sha256': sha(path), 'bytes': path.stat().st_size})
    save(HERE / 'runtime-manifest.json', {
        'archive': 'runtime-001.zip', 'archive_sha256': sha(HERE / 'runtime-001.zip'),
        'files': runtime_rows, 'runtime': runtime,
    })
    modules = ['__init__.py', 'contracts.py', 'execution.py', 'journal.py', 'audit.py',
               'failure_policy.py', 'openrouter.py']
    sources = [EVAL / 'communication_pruning' / name for name in modules]
    sources += [HERE / 'package.py', HERE / 'generate.py', RUN / 'contract.md',
                HERE / 'runtime.json', HERE / 'runtime-manifest.json']
    sources += [ROOT / relative for relative in (
        'project/dsr/Z37-MESSABNAHME-PLAN.md', 'project/DSR-ENTWICKLUNGSRAHMEN.md',
        'project/ENTWICKLUNGSSTEUERUNG.md', 'project/ENTWICKLUNGSSTEUERUNG.json',
        'project/dsr/ZYKLENREGISTER.md', 'project/history/state/active.json')]
    rows = []
    with zipfile.ZipFile(HERE / 'source-001.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in sources:
            relative = str(path.relative_to(ROOT))
            archive.write(path, relative)
            rows.append({'path': relative, 'sha256': sha(path), 'bytes': path.stat().st_size})
    save(HERE / 'source-manifest.json', {
        'archive': 'source-001.zip', 'archive_sha256': sha(HERE / 'source-001.zip'),
        'files': rows, 'runtime_archive_sha256': sha(HERE / 'runtime-001.zip'),
        'package': 'A-20260913T083542Z-d276aa', 'plan_commit': 'a8d09f569a9a',
        'stage': 'Before all decisive case generation and overhead measurement',
    })
    print(json.dumps({'source_bound': True, 'source_files': len(rows),
                      'runtime_files': len(runtime_rows), 'case_generation_run': False}))


if __name__ == '__main__':
    main()
