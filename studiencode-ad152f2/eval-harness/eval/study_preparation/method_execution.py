"""Z45 continuation plumbing. Importing this module performs no execution.

Full execution needs a separately signed-off, hash-bound start artifact. The
synthetic mode requires an injected worker and permits at most 64 identities.
Unresolved started jobs stop every continuation; they are never retried here.
"""
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import zipfile

import numpy as np
from .cases import catalog, generate, seed, SEED_BASIS
from .intervals import analyze
from .calibration import summarize


PREFIX_GROUPS = ('P/P2','R/S3','R/S7','T1/S3','T2/S3','F/S3','F/S7')
CRITICAL = ('eval-harness/eval/study_preparation/cases.py',
            'eval-harness/eval/study_preparation/intervals.py')
THREAD_KEYS = ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','VECLIB_MAXIMUM_THREADS','MKL_NUM_THREADS')
SPECIAL = {'Infinity': math.inf, '-Infinity': -math.inf, 'NaN': math.nan}
STATUSES = {'ok','denominator_zero','denominator_weak','variance_zero','resample_undefined'}


class MethodStop(RuntimeError):
    """A preserved state needs inspection; no retry or repair is implied."""


def encode(value):
    if isinstance(value, dict):
        return {str(k):encode(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [encode(v) for v in value]
    if isinstance(value, (float,np.floating)) and not np.isfinite(value):
        return 'NaN' if np.isnan(value) else 'Infinity' if value>0 else '-Infinity'
    if isinstance(value,np.generic):
        return value.item()
    return value


def canonical(value):
    return json.dumps(encode(value),sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def digest(path,check_resources=None):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            if check_resources:check_resources()
            h.update(chunk)
    return h.hexdigest()


def object_digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def runtime():
    return dict(python=sys.version,numpy=np.__version__,platform=platform.platform(),executable=sys.executable)


def _json(path):
    return json.loads(Path(path).read_text(),parse_constant=lambda x:(_ for _ in ()).throw(MethodStop('nonstandard JSON constant')))


def _write_new(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:
        f.write(canonical(value)+b'\n');f.flush();os.fsync(f.fileno())


def _checkpoint(output,value):
    temp=Path(output)/'CHECKPOINT.new'
    _write_new(temp,value)
    os.replace(temp,Path(output)/'CHECKPOINT.json')


def _safe_path(root,relative):
    root=Path(root).resolve();path=(root/relative).resolve()
    if not path.is_relative_to(root) or path==root:
        raise MethodStop('path outside bound directory')
    return path


def verify_archive(path,expected_hash,members,*,check_resources=None):
    """Read every archive member in bounded buffers; never extract paths."""
    check=check_resources or (lambda:None)
    check()
    if digest(path,check)!=expected_hash:raise MethodStop('archive hash mismatch')
    with zipfile.ZipFile(path) as z:
        if len(z.namelist())!=len(set(z.namelist())) or set(z.namelist())!=set(members):
            raise MethodStop('archive membership mismatch')
        for name,expected in members.items():
            check()
            h=hashlib.sha256()
            with z.open(name) as f:
                for chunk in iter(lambda:f.read(1024*1024),b''):
                    check();h.update(chunk)
            if h.hexdigest()!=expected:raise MethodStop('archive member mismatch: '+name)
    check()


def decode_record(row):
    """Decode only interval numeric fields, never IDs, labels or arbitrary text."""
    out=deepcopy(row)
    for endpoint in out['result']['endpoints'].values():
        for key in ('estimate','se','lower','upper'):
            if key in endpoint and isinstance(endpoint[key],str):
                if endpoint[key] not in SPECIAL:raise MethodStop('unexpected numeric string')
                endpoint[key]=SPECIAL[endpoint[key]]
    return out


def validate_record(row,spec,seed_function=seed):
    rep=row.get('rep')
    if row.get('group_id')!=spec['id'] or type(rep) is not int or not 0<=rep<spec['repetitions']:
        raise MethodStop('unexpected group/repetition')
    for stream,key in [('data','data_seed'),('bootstrap','bootstrap_seed')]:
        if type(row.get(key)) is not int or row[key]!=seed_function(spec['id'],spec['n'],rep,stream):
            raise MethodStop('seed mismatch')
    result=row['result']
    if type(result.get('n')) is not int or result['n']!=spec['n'] or type(result.get('bootstrap_reps')) is not int or result['bootstrap_reps']!=19999:
        raise MethodStop('changed n/B')
    if set(result['endpoints'])!={e['id'] for e in spec['endpoints']}:
        raise MethodStop('endpoint mismatch')
    for endpoint in result['endpoints'].values():
        if endpoint.get('status') not in STATUSES:raise MethodStop('unknown endpoint status')
        for key in ('estimate','lower','upper'):
            value=endpoint.get(key)
            if type(value) not in (float,int):raise MethodStop('nonnumeric endpoint')
            if key!='estimate' and math.isnan(value):raise MethodStop('NaN bound')
            if endpoint['status']=='ok' and not math.isfinite(value):raise MethodStop('nonfinite informative endpoint')


def identities(contract):
    """Fixed catalog order, then repetition order; independent of completion order."""
    for spec in contract['groups']+contract['controls']:
        for rep in range(spec['repetitions']):yield spec['id'],rep


def planned_counts(contract=None):
    contract=catalog() if contract is None else contract
    total=sum(g['repetitions'] for g in contract['groups']+contract['controls'])
    return dict(groups=len(contract['groups'])+len(contract['controls']),total=total,
                reused=700,remaining=total-700)


def _records(path):
    with Path(path).open('rb') as f:
        for raw in f:
            if not raw.endswith(b'\n'):raise MethodStop('incomplete journal line; preserved')
            try:row=json.loads(raw,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
            except (ValueError,UnicodeError) as exc:raise MethodStop('invalid journal; preserved') from exc
            yield decode_record(row)


def validate_dataset(path,expected,spec):
    if digest(path)!=expected:raise MethodStop('dataset hash mismatch')
    with np.load(path,allow_pickle=False) as z:
        if set(z.files)!={'atoms','counts'}:raise MethodStop('dataset fields')
        atoms,counts=z['atoms'],z['counts']
        if atoms.ndim!=2 or atoms.shape[1]!=len(spec['columns']) or counts.shape!=(len(atoms),):
            raise MethodStop('dataset shape')
        if not np.isfinite(atoms).all() or counts.dtype.kind not in 'iu' or (counts<=0).any() or int(counts.sum())!=spec['n']:
            raise MethodStop('dataset values/counts')


def verify_prefix(binding,contract,current_sources,current_runtime,*,expected_groups=PREFIX_GROUPS,per_group=100):
    """Verify retained provenance and exact identities without interpreting outcomes.

    New reporter/orchestrator hashes intentionally need not equal old hashes.
    The complete old source list remains bound by the old manifest/archive.
    """
    directory=Path(binding['directory']).resolve()
    for name,key in [('EXECUTION.json','execution_sha256'),('ARCHIVE-READBACK.json','readback_sha256'),('results.jsonl','results_sha256')]:
        if digest(directory/name)!=binding[key]:raise MethodStop('prefix evidence changed: '+name)
    old=_json(directory/'EXECUTION.json');readback=_json(directory/'ARCHIVE-READBACK.json')
    if old['groups']!=list(expected_groups) or old['per_group']!=per_group or old['bootstrap_reps']!=19999:
        raise MethodStop('prefix scope changed')
    if old['runtime']!=current_runtime or old['catalog_sha256']!=object_digest(contract):
        raise MethodStop('prefix runtime/catalog mismatch')
    if any(old['sources'].get(path)!=current_sources.get(path) for path in CRITICAL):
        raise MethodStop('result-determining source mismatch')
    if binding['archive_sha256']!=readback['sha256']:raise MethodStop('prefix archive binding mismatch')
    verify_archive(directory/'prefix-evidence.zip',readback['sha256'],readback['member_sha256'])
    old_archives=[(path,sha) for path,sha in old['sources'].items() if path.endswith('.zip')]
    if not old_archives:raise MethodStop('recoverable original source archive missing')
    archived_sources={}
    for relative,expected_hash in old_archives:
        archive=_safe_path(old['project_root'],relative)
        if digest(archive)!=expected_hash:raise MethodStop('original source archive changed')
        with zipfile.ZipFile(archive) as z:
            if len(z.namelist())!=len(set(z.namelist())):raise MethodStop('duplicate original source archive member')
            for name in z.namelist():
                h=hashlib.sha256()
                with z.open(name) as f:
                    for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
                if name in old['sources'] and h.hexdigest()!=old['sources'][name]:
                    raise MethodStop('original archived source differs from prefix binding')
                archived_sources[name]=h.hexdigest()
    if any(archived_sources.get(path)!=expected for path,expected in old['sources'].items() if not path.endswith('.zip')):
        raise MethodStop('original bound source bytes missing')
    # Every retained raw member must still agree with its separately verified archive.
    for relative,expected in readback['member_sha256'].items():
        if digest(_safe_path(directory,relative))!=expected:raise MethodStop('prefix raw member changed')
    report=_json(directory/'RESOURCE-RESULT.json')
    expected={(gid,rep) for gid in expected_groups for rep in range(per_group)}
    if report['status']!='complete' or report['count']!=len(expected):raise MethodStop('incomplete prefix')
    specs={g['id']:g for g in contract['groups']+contract['controls']};seen=set()
    for row in _records(directory/'results.jsonl'):
        key=(row['group_id'],row['rep'])
        if key not in expected or key in seen:raise MethodStop('prefix duplicate/unexpected identity')
        validate_record(row,specs[key[0]])
        validate_dataset(_safe_path(directory/'datasets',row['dataset']),row['dataset_sha256'],specs[key[0]])
        seen.add(key)
    if seen!=expected:raise MethodStop('missing prefix identity')
    return seen


def _source_check(manifest):
    root=Path(manifest['project_root'])
    for relative,expected in manifest['sources'].items():
        if digest(_safe_path(root,relative))!=expected:raise MethodStop('current source changed: '+relative)
    source=manifest['source_archive']
    verify_archive(source['path'],source['sha256'],source['members'])
    if any(source['members'].get(path)!=value for path,value in manifest['sources'].items()):
        raise MethodStop('source archive lacks bound current source')


def validate_manifest(manifest,*,injected_worker=False):
    """All start gates precede prefix reading, worker construction and dispatch."""
    if manifest.get('kind')!='Z45-method-execution':raise MethodStop('wrong execution kind')
    mode=manifest.get('mode')
    contract=manifest['catalog']
    if object_digest(contract)!=manifest['catalog_sha256']:raise MethodStop('catalog hash mismatch')
    total=sum(g['repetitions'] for g in contract['groups']+contract['controls'])
    if mode=='synthetic':
        if not injected_worker or manifest.get('authorized') is not False or not 0<total<=64:
            raise MethodStop('synthetic scope requires injected worker and at most 64 identities')
    elif mode=='full':
        if manifest.get('authorized') is not True or injected_worker:
            raise MethodStop('full start not authorized or substituted worker')
        if object_digest(contract)!=object_digest(catalog()) or total!=400000:
            raise MethodStop('full catalog changed')
        if manifest.get('seed_basis')!=SEED_BASIS or manifest.get('batch_size')!=128:
            raise MethodStop('seed/batch contract changed')
        authorization=manifest.get('authorization')
        if not authorization:raise MethodStop('separate start authorization missing')
        if digest(authorization['path'])!=authorization['sha256']:raise MethodStop('authorization changed')
        approval=_json(authorization['path'])
        core={k:v for k,v in manifest.items() if k!='authorization'}
        if (approval.get('kind')!='full-method-start' or approval.get('approved') is not True
                or approval.get('manifest_sha256')!=object_digest(core)):
            raise MethodStop('authorization does not bind this execution')
        for name in ('temporal_rules','final_assumptions','resource_acceptance','technical_review'):
            proof=manifest.get('prerequisites',{}).get(name)
            if not proof or digest(proof['path'])!=proof['sha256']:
                raise MethodStop('missing/changed prerequisite: '+name)
        if not manifest.get('prefix'):raise MethodStop('700-prefix adoption missing')
        required=set(CRITICAL)|{'eval-harness/eval/study_preparation/method_execution.py',
                               'eval-harness/eval/study_preparation/calibration.py'}
        if not required<=set(manifest['sources']):raise MethodStop('required source bindings missing')
    else:raise MethodStop('unknown execution mode')
    if manifest['runtime']!=runtime():raise MethodStop('runtime mismatch')
    for key in THREAD_KEYS:
        if os.environ.get(key)!='1':raise MethodStop('one library thread required: '+key)
    limits=manifest['resources']
    if type(limits['workers']) is not int or not 1<=limits['workers']<=4:
        raise MethodStop('one to four workers required')
    for key in ('max_working_bytes','max_backup_bytes','max_wall_seconds','max_rss_bytes','max_job_output_bytes'):
        if type(limits[key]) not in (int,float) or not math.isfinite(limits[key]) or limits[key]<=0:
            raise MethodStop('positive finite resource bound required')
    if limits['max_rss_bytes']>8*1024**3:raise MethodStop('8 GiB shared limit exceeded')
    if mode=='full' and limits.get('disk_buffer_bytes',0)<10*1024**3:
        raise MethodStop('10 GiB disk buffer required')
    if mode=='full' and (type(limits.get('deadline_unix')) not in (int,float) or not math.isfinite(limits['deadline_unix'])):
        raise MethodStop('fixed finite execution deadline required')
    _source_check(manifest)


def process_memory_bytes():
    """Sample current RSS of this coordinator and every descendant process."""
    rows=subprocess.check_output(['ps','-axo','pid=,ppid=,rss='],text=True)
    table=[tuple(map(int,line.split())) for line in rows.splitlines() if line.strip()]
    included={os.getpid()}
    while True:
        more={pid for pid,ppid,rss in table if ppid in included}
        if more<=included:break
        included|=more
    return sum(rss*1024 for pid,ppid,rss in table if pid in included)


class ResourceGuard:
    """One initial inventory, then linear accounting; no per-job tree scans."""
    def __init__(self,output,limits,memory_reader=process_memory_bytes,clock=time.monotonic):
        self.output=Path(output);self.limits=limits;self.memory_reader=memory_reader
        self.clock=clock;self.started=clock();self.peak=0;self.reserved=0
        self.bytes=sum(p.stat().st_size for p in self.output.rglob('*') if p.is_file() and p!=self.output/'evidence.zip')
        self.backup_bytes=(self.output/'evidence.zip').stat().st_size if (self.output/'evidence.zip').exists() else 0

    def add(self,count):self.bytes+=count

    def check(self):
        memory=self.memory_reader();self.peak=max(self.peak,memory)
        if memory>self.limits['max_rss_bytes']:raise MethodStop('aggregate memory limit')
        if self.clock()-self.started>=self.limits['max_wall_seconds']:raise MethodStop('wall time limit')
        if time.time()>=self.limits.get('deadline_unix',math.inf):raise MethodStop('fixed execution deadline')
        if self.bytes+self.reserved>self.limits['max_working_bytes']:raise MethodStop('working output limit')
        if self.backup_bytes>self.limits['max_backup_bytes']:raise MethodStop('backup output limit')
        remaining=max(0,self.limits['max_working_bytes']-self.bytes)
        required=remaining+max(0,self.limits['max_backup_bytes']-self.backup_bytes)+self.limits.get('disk_buffer_bytes',0)
        if shutil.disk_usage(self.output).free<required:raise MethodStop('working + backup + buffer disk limit')


@contextmanager
def _lock(output):
    with (Path(output)/'LOCK').open('a+b') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise MethodStop('another coordinator owns this execution') from exc
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def _job_paths(gid,rep):
    token=gid.replace('/','-')+'/'+str(rep//1000).zfill(2)+'/'+str(rep).zfill(5)
    return 'datasets/'+token+'.npz','records/'+token+'.json'


def inspect_journal(output,manifest,adopted):
    """Reconstruct from immutable evidence, not from the replaceable checkpoint."""
    output=Path(output);specs={g['id']:g for g in manifest['catalog']['groups']+manifest['catalog']['controls']}
    states={};last='0'*64;sequence=0;paths=[]
    if (output/'CHECKPOINT.new').exists():raise MethodStop('unfinished checkpoint write; preserved')
    checkpoint=output/'CHECKPOINT.json';cp=_json(checkpoint) if checkpoint.exists() else None
    def check_cp():
        if cp is not None and cp['sequence']==sequence and (cp['last']!=last or cp['completed']!=len(paths)):
            raise MethodStop('checkpoint disagrees with journal')
    check_cp()
    journal=output/'journal.jsonl'
    if journal.exists():
        with journal.open('rb') as f:
            for raw in f:
                if not raw.endswith(b'\n'):raise MethodStop('partial journal line; no repair')
                try:event=json.loads(raw)
                except ValueError as exc:raise MethodStop('invalid journal; no repair') from exc
                checksum=event.pop('sha256')
                if event['sequence']!=sequence or event['previous']!=last or object_digest(event)!=checksum:
                    raise MethodStop('journal chain mismatch')
                last=checksum;sequence+=1
                key=(event['group_id'],event['rep'])
                if key[0] not in specs or type(key[1]) is not int or not 0<=key[1]<specs[key[0]]['repetitions'] or key in adopted:
                    raise MethodStop('journal identity outside pending plan')
                if event['type']=='started':
                    if key in states:raise MethodStop('duplicate job start')
                    states[key]='started'
                elif event['type']=='completed':
                    if states.get(key)!='started':raise MethodStop('completion without exactly one start')
                    dataset,resultfile=_job_paths(*key)
                    path=_safe_path(output,resultfile)
                    if digest(path)!=event['result_sha256']:raise MethodStop('result hash mismatch')
                    row=decode_record(_json(path));validate_record(row,specs[key[0]])
                    if (row['group_id'],row['rep'])!=key or row['dataset']!=dataset:
                        raise MethodStop('result identity/path mismatch')
                    validate_dataset(_safe_path(output,dataset),row['dataset_sha256'],specs[key[0]])
                    states[key]='completed';paths.append(resultfile)
                elif event['type']=='failed':
                    if states.get(key)!='started':raise MethodStop('failure without start')
                    states[key]='failed'
                else:raise MethodStop('unknown journal event')
                check_cp()
    if any(state!='completed' for state in states.values()):
        raise MethodStop('unresolved started/failed job; no automatic repair or redraw')
    if cp is not None and (cp['sequence']>sequence or cp['completed']>len(paths)):
        raise MethodStop('checkpoint exceeds verified journal')
    return set(states),paths,sequence,last


def save_dataset(job,atoms,counts):
    """Used by the genuine worker and artificial injected test workers."""
    path=Path(job['output'])/job['dataset'];path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:
        np.savez_compressed(f,atoms=atoms,counts=counts);f.flush();os.fsync(f.fileno())
    return digest(path)


def compute(job):
    spec=job['spec'];n=spec['n'];ds=job['data_seed'];bs=job['bootstrap_seed']
    rows=generate(spec['id'],n,np.random.Generator(np.random.PCG64(ds)))
    atoms,counts=np.unique(rows,axis=0,return_counts=True)
    dataset_hash=save_dataset(job,atoms,counts)
    answer=analyze(atoms,counts,spec['endpoints'],rng=np.random.Generator(np.random.PCG64(bs)),
                   bootstrap_reps=19999,batch_size=job['batch_size'])
    return dict(group_id=spec['id'],rep=job['rep'],data_seed=ds,bootstrap_seed=bs,
                dataset=job['dataset'],dataset_sha256=dataset_hash,atoms=len(atoms),result=answer)


def _archive(output,manifest,guard):
    started=time.monotonic()
    guard.check()
    output=Path(output);archive=output/'evidence.zip'
    files={str(p.relative_to(output)):p for p in output.rglob('*') if p.is_file() and p.name not in ('LOCK','evidence.zip','ARCHIVE.json')}
    files['bound/source.zip']=Path(manifest['source_archive']['path'])
    if manifest.get('prefix'):files['bound/prefix-evidence.zip']=Path(manifest['prefix']['directory'])/'prefix-evidence.zip'
    hashes={}
    for name,path in files.items():
        guard.check();hashes[name]=digest(path,guard.check)
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for name,path in files.items():
            guard.check()
            with path.open('rb') as source,z.open(name,'w') as target:
                for chunk in iter(lambda:source.read(1024*1024),b''):
                    guard.check();target.write(chunk)
                    guard.backup_bytes=z.fp.tell();guard.check()
            guard.backup_bytes=z.fp.tell();guard.check()
    guard.backup_bytes=archive.stat().st_size;guard.check()
    expected=digest(archive,guard.check)
    verify_archive(archive,expected,hashes,check_resources=guard.check)
    _write_new(output/'ARCHIVE.json',dict(sha256=expected,members=hashes,fully_read_back=True,
                                      seconds=time.monotonic()-started,bytes=archive.stat().st_size))
    guard.add((output/'ARCHIVE.json').stat().st_size);guard.check()


def execute(manifest,*,worker=None,memory_reader=process_memory_bytes,executor_factory=None):
    """Run only an explicitly bound execution or a <=64-job injected fixture."""
    validate_manifest(manifest,injected_worker=worker is not None)
    if executor_factory is not None and manifest['mode']!='synthetic':raise MethodStop('executor substitution forbidden')
    if memory_reader is not process_memory_bytes and manifest['mode']!='synthetic':raise MethodStop('memory monitor substitution forbidden')
    output=Path(manifest['output']).resolve();output.mkdir(parents=True,exist_ok=True)
    with _lock(output):
        if (output/'FINAL-STOP.json').exists():raise MethodStop('unresolved finalization stop; no automatic repair')
        binding=output/'BINDING.json'
        if binding.exists():
            if object_digest(_json(binding))!=object_digest(manifest):raise MethodStop('execution binding changed')
        else:_write_new(binding,manifest)
        adopted=set()
        if manifest.get('prefix'):
            adopted=verify_prefix(manifest['prefix'],manifest['catalog'],manifest['sources'],manifest['runtime'])
        completed,paths,sequence,last=inspect_journal(output,manifest,adopted)
        guard=ResourceGuard(output,manifest['resources'],memory_reader)
        guard.check()
        if (output/'COMPLETE.json').exists():
            if len(completed|adopted)!=sum(g['repetitions'] for g in manifest['catalog']['groups']+manifest['catalog']['controls']):
                raise MethodStop('completion marker with missing identities')
            if not (output/'ARCHIVE.json').exists():raise MethodStop('incomplete final archive; no automatic repair')
            archival=_json(output/'ARCHIVE.json')
            verify_archive(output/'evidence.zip',archival['sha256'],archival['members'],check_resources=guard.check)
            for name in ('COMPLETE.json','SUMMARY.json'):
                if name not in archival['members'] or digest(output/name,guard.check)!=archival['members'][name]:
                    raise MethodStop('live final evidence differs from archive: '+name)
            raw=(output/'COMPLETE.json').read_bytes()
            if hashlib.sha256(raw).hexdigest()!=archival['members']['COMPLETE.json']:
                raise MethodStop('completion changed during readback')
            guard.check()
            return json.loads(raw)
        specs={g['id']:g for g in manifest['catalog']['groups']+manifest['catalog']['controls']}
        pending=(key for key in identities(manifest['catalog']) if key not in adopted and key not in completed)
        active={};failure=None;start=time.monotonic()
        def append(kind,key,**extra):
            nonlocal sequence,last
            event=dict(sequence=sequence,previous=last,type=kind,group_id=key[0],rep=key[1],**extra)
            last=object_digest(event);event['sha256']=last;raw=canonical(event)+b'\n'
            with (output/'journal.jsonl').open('ab') as f:f.write(raw);f.flush();os.fsync(f.fileno())
            guard.add(len(raw));sequence+=1
        factory=executor_factory or (lambda n:ProcessPoolExecutor(max_workers=n,mp_context=multiprocessing.get_context('spawn')))
        with factory(manifest['resources']['workers']) as pool:
            exhausted=False
            while active or not exhausted:
                try:guard.check()
                except BaseException as exc:failure=exc;exhausted=True
                while not exhausted and failure is None and len(active)<manifest['resources']['workers']:
                    key=next(pending,None)
                    if key is None:exhausted=True;break
                    guard.reserved+=manifest['resources']['max_job_output_bytes']
                    try:guard.check()
                    except BaseException as exc:
                        guard.reserved-=manifest['resources']['max_job_output_bytes'];failure=exc;exhausted=True;break
                    dataset,resultfile=_job_paths(*key)
                    job=dict(spec=specs[key[0]],rep=key[1],output=str(output),dataset=dataset,batch_size=manifest['batch_size'],
                             data_seed=seed(key[0],specs[key[0]]['n'],key[1],'data'),
                             bootstrap_seed=seed(key[0],specs[key[0]]['n'],key[1],'bootstrap'))
                    append('started',key)
                    active[pool.submit(worker or compute,job)]=(key,resultfile)
                if not active:break
                done,_=wait(active,timeout=.25,return_when=FIRST_COMPLETED)
                for future in done:
                    key,resultfile=active.pop(future)
                    guard.reserved-=manifest['resources']['max_job_output_bytes']
                    try:
                        row=decode_record(future.result());validate_record(row,specs[key[0]])
                        dataset,_=_job_paths(*key)
                        if (row['group_id'],row['rep'])!=key or row['dataset']!=dataset:raise MethodStop('worker identity/path mismatch')
                        datafile=_safe_path(output,dataset)
                        validate_dataset(datafile,row['dataset_sha256'],specs[key[0]])
                        if datafile.stat().st_size+len(canonical(row))+1>manifest['resources']['max_job_output_bytes']:
                            raise MethodStop('job output reservation exceeded')
                        resultpath=_safe_path(output,resultfile);_write_new(resultpath,row)
                        guard.add(datafile.stat().st_size+resultpath.stat().st_size)
                        append('completed',key,result_sha256=digest(resultpath))
                        completed.add(key);paths.append(resultfile)
                        previous_size=(output/'CHECKPOINT.json').stat().st_size if (output/'CHECKPOINT.json').exists() else 0
                        _checkpoint(output,dict(sequence=sequence,last=last,completed=len(completed),adopted=len(adopted)))
                        guard.add((output/'CHECKPOINT.json').stat().st_size-previous_size)
                    except BaseException as exc:
                        append('failed',key,error=type(exc).__name__+': '+str(exc));failure=exc;exhausted=True
        if failure is not None:
            name='STOP-'+str(time.time_ns())+'.json'
            _write_new(output/name,dict(error=type(failure).__name__+': '+str(failure),completed=len(completed),adopted=len(adopted)))
            raise MethodStop('execution stopped; evidence retained') from failure
        try:
            guard.check();_source_check(manifest);guard.check()
            def all_records():
                if manifest.get('prefix'):yield from _records(Path(manifest['prefix']['directory'])/'results.jsonl')
                for relative in paths:yield decode_record(_json(_safe_path(output,relative)))
            summary=summarize(manifest['catalog'],all_records(),check_resources=guard.check)
            guard.check();_write_new(output/'SUMMARY.json',summary)
            guard.add((output/'SUMMARY.json').stat().st_size);guard.check()
            result=dict(status='complete',completed=len(completed),adopted=len(adopted),
                        total=len(completed|adopted),seconds=time.monotonic()-start,peak_sampled_rss_bytes=guard.peak,
                        synthetic=manifest['mode']=='synthetic',study_release=False)
            _write_new(output/'COMPLETE.json',result)
            guard.add((output/'COMPLETE.json').stat().st_size);guard.check()
            _archive(output,manifest,guard);guard.check()
            return result
        except BaseException as exc:
            _write_new(output/'FINAL-STOP.json',dict(error=type(exc).__name__+': '+str(exc),
                       completed=len(completed),adopted=len(adopted),stage='summary_archive_readback'))
            raise MethodStop('finalization stopped; evidence retained') from exc
