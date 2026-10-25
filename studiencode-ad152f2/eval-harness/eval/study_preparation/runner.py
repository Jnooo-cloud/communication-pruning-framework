"""Offline fixed-prefix runner. Requires a prewritten, hash-bound execution file.

Only artificial case generation is reachable; no model/data/provider imports.
The complete calibration is deliberately not launched by this preparation CLI.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import sys
import time
import zipfile
import numpy as np
from .cases import catalog, group, generate, seed
from .intervals import analyze


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def jsonable(value):
    if isinstance(value,dict):return {str(k):jsonable(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [jsonable(v) for v in value]
    if isinstance(value,(float,np.floating)) and not np.isfinite(value):
        return 'NaN' if np.isnan(value) else 'Infinity' if value>0 else '-Infinity'
    if isinstance(value,np.generic):return value.item()
    return value


def write_json(path,value):
    with Path(path).open('x') as f:
        json.dump(jsonable(value),f,ensure_ascii=False,indent=2,allow_nan=False)
        f.write('\n')


def prefix(manifest_path):
    """Exactly the bound prefix; resource failure leaves a preserved partial run."""
    manifest_path=Path(manifest_path).resolve()
    manifest=json.loads(manifest_path.read_text())
    if manifest['kind']!='Z44-resource-prefix' or manifest['bootstrap_reps']!=19999 or manifest['per_group']!=100:
        raise ValueError('not the accepted prefix contract')
    if manifest['full_calibration_authorized'] is not False or manifest['model_calls_authorized'] is not False:
        raise ValueError('this runner is offline preparation only')
    root=Path(manifest['project_root']).resolve()
    output=Path(manifest['output']).resolve()
    required=root/'eval-harness/eval/runs/Z44-VORBEREITUNG-001'
    if not output.is_relative_to(required) or output.exists():
        raise ValueError('new bounded run directory required; no overwrites/restarts')
    for rel,sha in manifest['sources'].items():
        if digest(root/rel)!=sha:raise ValueError('source/contract/review changed: '+rel)
    if not manifest['technical_review_accepted']:raise ValueError('technical review missing')
    expected_runtime=manifest['runtime']
    if sys.version!=expected_runtime['python'] or np.__version__!=expected_runtime['numpy']:
        raise ValueError('runtime changed')
    for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','VECLIB_MAXIMUM_THREADS','MKL_NUM_THREADS'):
        if os.environ.get(key)!='1':raise ValueError('single library thread required: '+key)
    catalog_bytes=json.dumps(jsonable(catalog()),sort_keys=True,separators=(',',':')).encode()
    if hashlib.sha256(catalog_bytes).hexdigest()!=manifest['catalog_sha256']:
        raise ValueError('catalog changed')
    if len(manifest['groups'])!=len(set(manifest['groups'])):
        raise ValueError('duplicate prefix groups')
    for gid in manifest['groups']:
        if group(gid)['n'] not in (9040,2952):raise ValueError('changed sample size')
    output.mkdir(parents=True)
    (output/'datasets').mkdir()
    shutil.copyfile(manifest_path,output/'EXECUTION.json')
    started=time.time();wall=time.monotonic();cpu=time.process_time()
    count=0;status='incomplete';reason=None;timings={g:[] for g in manifest['groups']}
    def rss():
        val=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(val if sys.platform=='darwin' else val*1024)
    def check_resources():
        if time.monotonic()-wall>=manifest['max_wall_seconds']:raise RuntimeError('wall_time_limit')
        if rss()>manifest['max_rss_bytes']:raise RuntimeError('memory_limit')
        if shutil.disk_usage(output).free<manifest['min_free_bytes']:raise RuntimeError('disk_limit')
        if sum(p.stat().st_size for p in output.rglob('*') if p.is_file())>manifest['max_working_bytes']:
            raise RuntimeError('working_output_limit')
    try:
        with (output/'results.jsonl').open('x') as results:
            # Fixed interleaving covers all computation paths before their next replicate.
            for rep in range(100):
                for gid in manifest['groups']:
                    check_resources();spec=group(gid);n=spec['n'];begin=time.monotonic()
                    ds=seed(gid,n,rep,'data');bs=seed(gid,n,rep,'bootstrap')
                    rows=generate(gid,n,np.random.Generator(np.random.PCG64(ds)))
                    atoms,counts=np.unique(rows,axis=0,return_counts=True)
                    name=gid.replace('/','-')+'-'+str(rep).zfill(5)+'.npz'
                    datafile=output/'datasets'/name
                    np.savez_compressed(datafile,atoms=atoms,counts=counts)
                    answer=analyze(atoms,counts,spec['endpoints'],
                         rng=np.random.Generator(np.random.PCG64(bs)),
                         bootstrap_reps=19999,batch_size=manifest['batch_size'])
                    elapsed=time.monotonic()-begin
                    timings[gid].append(elapsed)
                    row=dict(group_id=gid,rep=rep,data_seed=ds,bootstrap_seed=bs,
                             dataset=name,dataset_sha256=digest(datafile),atoms=len(atoms),
                             seconds=elapsed,max_rss_bytes=rss(),result=answer)
                    results.write(json.dumps(jsonable(row),separators=(',',':'),allow_nan=False)+'\n')
                    results.flush();os.fsync(results.fileno());count+=1
                    print(json.dumps(dict(completed=count,group=gid,rep=rep,seconds=elapsed,rss_bytes=rss())),flush=True)
                    check_resources()
        status='complete'
    except BaseException as exc:
        reason=type(exc).__name__+': '+str(exc)
        raise
    finally:
        report=dict(status=status,reason=reason,count=count,planned=100*len(manifest['groups']),
                    started_unix=started,seconds=time.monotonic()-wall,cpu_seconds=time.process_time()-cpu,
                    max_rss_bytes=rss(),timings=timings,method_accepted=False,
                    note='Resource prefix only. Preserve datasets; never redraw them in a later full check.')
        write_json(output/'RESOURCE-RESULT.json',report)
    # Verification is a separate measured stage and does not change statistical records.
    archival_start=time.monotonic()
    files=sorted(p for p in output.rglob('*') if p.is_file())
    archive=output/'prefix-evidence.zip'
    hashes={str(p.relative_to(output)):digest(p) for p in files}
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(p,p.relative_to(output))
    with zipfile.ZipFile(archive) as z:
        if set(z.namelist())!=set(hashes):raise ValueError('archive membership changed')
        for name,sha in hashes.items():
            if hashlib.sha256(z.read(name)).hexdigest()!=sha:raise ValueError('archive readback mismatch')
    write_json(output/'ARCHIVE-READBACK.json',dict(members=len(hashes),sha256=digest(archive),
               member_sha256=hashes,seconds=time.monotonic()-archival_start,
               raw_output_bytes=sum(p.stat().st_size for p in files),archive_bytes=archive.stat().st_size))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('execution_manifest')
    args=parser.parse_args()
    prefix(args.execution_manifest)
