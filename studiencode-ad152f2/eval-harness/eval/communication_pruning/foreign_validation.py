"""Create-only Z15 external demonstration and preserved regression evidence."""

import argparse
from contextlib import redirect_stdout, redirect_stderr
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch
import zipfile
import autogen_core
import autogen_agentchat
from .foreign_demo import run_case
from .foreign_audit import audit

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / 'eval-harness/eval'
ORIENTATION = Path('/private/tmp/z15-orientation')
CASES = ('fresh_a', 'fresh_b', 'history_control', 'unknown_prices', 'failed_known', 'failed_unknown')


def bundle(folder):
    files = sorted(set((ARTIFACT / 'communication_pruning').glob('*.py')) | set((ARTIFACT / 'tests').glob('*.py')) |
                   {ROOT / 'project/dsr/Z15-PLAN.md', ROOT / 'project/dsr/Z14-ERGEBNIS.md', ARTIFACT / 'README.md'})
    hashes = {}; package_hashes = {}; install = json.loads((ORIENTATION / 'install-report.json').read_text())
    requirements = ''.join(f"{r['metadata']['name']}=={r['metadata']['version']}\n" for r in sorted(install['install'], key=lambda r: r['metadata']['name']))
    with zipfile.ZipFile(folder / 'source.zip', 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            data = path.read_bytes(); name = str(path.relative_to(ROOT)); hashes[name] = sha256(data).hexdigest(); archive.writestr(name, data)
        archive.writestr('Z15-requirements.txt', requirements)
        archive.writestr('Z15-install-report.json', json.dumps(install, indent=2))
    # Preserve official wheels with their MIT license texts, and bind installed code.
    external = folder / 'external'; external.mkdir()
    for module in (autogen_core, autogen_agentchat):
        name = module.__name__; version = metadata.version(name.replace('_', '-'))
        if version != '0.7.5': raise ValueError('unexpected AutoGen version')
        wheel = ORIENTATION / f'{name}-0.7.5-py3-none-any.whl'
        shutil.copyfile(wheel, external / wheel.name)
        with zipfile.ZipFile(wheel) as archive:
            licensed = False
            for entry in archive.namelist():
                if entry.endswith('LICENSE-CODE') and b'MIT License' in archive.read(entry): licensed = True
                if entry.startswith(name + '/') and entry.endswith('.py'):
                    data = (Path(module.__file__).parent.parent / entry).read_bytes()
                    if data != archive.read(entry): raise ValueError('installed external code differs from wheel')
                    package_hashes[entry] = sha256(data).hexdigest()
            if not licensed: raise ValueError('missing MIT code license')
    return hashes, package_hashes, requirements


async def demonstrate(folder):
    results = []
    for name in CASES:
        result = await run_case(folder, name)
        if not name.startswith('failed_'):
            published = [m['content'] for stage in result['stages'] for m in stage['messages'] if m['source'] in ('solver', 'critic')]
            returned = [r['response']['content'] for r in result['audit']['terminal']]
            if published != returned: raise ValueError('native team output does not match observed client output')
        with (folder / f'{name}-result.json').open('x') as out: json.dump(result, out, indent=2); out.write('\n')
        results.append(dict(case=name, passed=result['passed'], **{k: result['audit'][k] for k in ('attempts','completed','failed','unresolved','unknown_cost_attempts','known_cost_subtotal_usd','total_cost_usd')}))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('run'); args = parser.parse_args()
    if not args.run.isdigit(): parser.error('numeric run ID required')
    folder = ARTIFACT / 'runs' / ('Z15-EXT-' + args.run); folder.mkdir(mode=0o700, exist_ok=False)
    now = lambda: datetime.now(timezone.utc).isoformat()
    receipt = dict(run_id=folder.name, started_at=now(), status='running', executable=sys.executable, python=sys.version,
                   command=sys.argv, pythonpath=os.environ.get('PYTHONPATH',''), model_cost_usd='0', tests=[], results=[], network_attempts=0)
    hashes = {}
    try:
        hashes, package_hashes, requirements = bundle(folder)
        receipt.update(files_sha256=hashes, external_python_sha256=package_hashes,
                       source_bundle_sha256=sha256((folder / 'source.zip').read_bytes()).hexdigest(), requirements=requirements)
        for command in ([sys.executable,'-m','unittest','discover','-s','tests','-v'],
                        [sys.executable,'-m','communication_pruning'], [sys.executable,'-m','communication_pruning.demo']):
            run = subprocess.run(command, cwd=ARTIFACT, capture_output=True, text=True, timeout=180)
            receipt['tests'].append(dict(command=command, returncode=run.returncode, stdout=run.stdout, stderr=run.stderr))
        if any(t['returncode'] for t in receipt['tests']): raise RuntimeError('regression failed; retained outputs')
        def deny_network(*args, **kwargs):
            receipt['network_attempts'] += 1
            raise RuntimeError('network forbidden in external synthetic demonstration')
        with (folder / 'external-stdout.log').open('x') as stdout, (folder / 'external-stderr.log').open('x') as stderr:
            with redirect_stdout(stdout), redirect_stderr(stderr), patch('socket.socket.connect', deny_network), patch('socket.create_connection', deny_network):
                receipt['results'] = asyncio.run(demonstrate(folder))
        if sum(r['attempts'] for r in receipt['results']) != 28 or receipt['network_attempts']:
            raise ValueError('unexpected total attempts or network access')
        receipt['status'] = 'passed'
    except BaseException as error:
        receipt.update(status='failed', error_type=type(error).__name__, error=str(error)); raise
    finally:
        receipt['source_unchanged'] = all(sha256((ROOT / p).read_bytes()).hexdigest() == h for p,h in hashes.items())
        if not receipt['source_unchanged']: receipt['status'] = 'failed_source_changed'
        receipt['evidence_sha256'] = {str(p.relative_to(folder)):sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob('*')) if p.is_file()}
        receipt['finished_at'] = now()
        with (folder / 'receipt.json').open('x') as out: json.dump(receipt, out, indent=2); out.write('\n')
    print(json.dumps({k:receipt[k] for k in ('run_id','status','network_attempts','results')}))


if __name__ == '__main__': main()
