"""Z45 short, hand-built orchestration fixtures. No simulation is performed."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from study_preparation import method_execution as m
from study_preparation.cases import catalog, group, seed, SEED_BASIS


ROOT=Path(__file__).resolve().parents[3]


def artificial_worker(job):
    """One hand-built atom; returned intervals are prescribed, not estimated."""
    spec=job['spec']
    sha=m.save_dataset(job,np.zeros((1,len(spec['columns']))),np.array([spec['n']],dtype=np.int64))
    return dict(group_id=spec['id'],rep=job['rep'],data_seed=job['data_seed'],bootstrap_seed=job['bootstrap_seed'],
                dataset=job['dataset'],dataset_sha256=sha,worker_pid=os.getpid(),
                threads={k:os.environ.get(k) for k in m.THREAD_KEYS},
                result=dict(n=spec['n'],bootstrap_reps=19999,endpoints={e['id']:
                dict(estimate=e['truth'],se=.01,lower=e['truth']-e['h']/2,upper=e['truth']+e['h']/2,
                     status='ok',undefined_resamples=0) for e in spec['endpoints']}))


def failed_worker(job):
    m.save_dataset(job,np.zeros((1,len(job['spec']['columns']))),np.array([job['spec']['n']],dtype=np.int64))
    raise RuntimeError('prescribed artificial worker failure')


def archive(path,files):
    members={name:m.digest(source) for name,source in files.items()}
    with zipfile.ZipFile(path,'x',zipfile.ZIP_DEFLATED) as z:
        for name,source in files.items():z.write(source,name)
    return dict(path=str(path),sha256=m.digest(path),members=members)


class MethodExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.env=patch.dict(os.environ,{k:'1' for k in m.THREAD_KEYS});self.env.start();self.addCleanup(self.env.stop)
        self.sources={p:m.digest(ROOT/p) for p in m.CRITICAL}
        paths={p:ROOT/p for p in m.CRITICAL}
        self.source_archive=archive(self.base/'current-source.zip',paths)

    def manifest(self,name='run',workers=1,repetitions=3):
        spec=group('P/R1');spec['n']=20;spec['repetitions']=repetitions
        contract=dict(groups=[spec],controls=[],events=[e for e in catalog()['events'] if e['group_id']==spec['id']])
        return dict(kind='Z45-method-execution',mode='synthetic',authorized=False,project_root=str(ROOT),
                    output=str(self.base/name),catalog=contract,catalog_sha256=m.object_digest(contract),
                    runtime=m.runtime(),sources=deepcopy(self.sources),source_archive=deepcopy(self.source_archive),
                    seed_basis=SEED_BASIS,batch_size=128,
                    resources=dict(workers=workers,max_working_bytes=8*1024**2,max_backup_bytes=8*1024**2,
                                   max_rss_bytes=8*1024**3,max_wall_seconds=60,max_job_output_bytes=65536,
                                   disk_buffer_bytes=0,deadline_unix=time.time()+120))

    def execute(self,manifest,worker=artificial_worker,processes=False):
        return m.execute(manifest,worker=worker,memory_reader=lambda:1024,
                         executor_factory=None if processes else lambda n:ThreadPoolExecutor(max_workers=n))

    def test_full_start_gates_precede_any_computation(self):
        manifest=self.manifest();manifest.update(mode='full',catalog=catalog(),authorized=False)
        manifest['catalog_sha256']=m.object_digest(manifest['catalog'])
        with patch.object(m,'generate') as generator,patch.object(m,'analyze') as analyze:
            with self.assertRaises(m.MethodStop):m.execute(manifest)
            generator.assert_not_called();analyze.assert_not_called()
        manifest['authorized']=True
        with self.assertRaisesRegex(m.MethodStop,'authorization'):m.execute(manifest)
        self.assertFalse(Path(manifest['output']).exists())

    def test_complete_once_and_four_process_identity_parity(self):
        outputs=[]
        for workers in (1,4):
            manifest=self.manifest('workers-'+str(workers),workers=workers,repetitions=4)
            result=self.execute(manifest,processes=True)
            self.assertEqual(result['total'],4);self.assertTrue(result['synthetic'])
            self.assertFalse(result['study_release'])
            folder=Path(manifest['output'])
            records=[m.decode_record(m._json(p)) for p in sorted((folder/'records').rglob('*.json'))]
            self.assertEqual(len(records),4)
            for row in records:
                self.assertEqual(set(row['threads'].values()),{'1'})
                row.pop('worker_pid');row.pop('threads')
            outputs.append(records)
            before=m.digest(folder/'journal.jsonl')
            with patch.object(m,'compute',side_effect=AssertionError('must not repeat')):
                self.assertEqual(self.execute(manifest)['total'],4)
            self.assertEqual(m.digest(folder/'journal.jsonl'),before)
            self.assertTrue(m._json(folder/'ARCHIVE.json')['fully_read_back'])
        self.assertEqual(outputs[0],outputs[1])

    def seal_first(self,manifest):
        output=Path(manifest['output']);output.mkdir();m._write_new(output/'BINDING.json',manifest)
        spec=manifest['catalog']['groups'][0];dataset,resultfile=m._job_paths(spec['id'],0)
        job=dict(spec=spec,rep=0,output=str(output),dataset=dataset,batch_size=128,
                 data_seed=seed(spec['id'],spec['n'],0,'data'),bootstrap_seed=seed(spec['id'],spec['n'],0,'bootstrap'))
        row=artificial_worker(job);m._write_new(output/resultfile,row)
        previous='0'*64;events=[]
        for sequence,kind in enumerate(('started','completed')):
            event=dict(sequence=sequence,previous=previous,type=kind,group_id=spec['id'],rep=0)
            if kind=='completed':event['result_sha256']=m.digest(output/resultfile)
            previous=m.object_digest(event);event['sha256']=previous;events.append(event)
        (output/'journal.jsonl').write_bytes(b''.join(m.canonical(x)+b'\n' for x in events))
        return events

    def test_resume_from_verified_completed_evidence_not_checkpoint_authority(self):
        manifest=self.manifest();events=self.seal_first(manifest);calls=[]
        output=Path(manifest['output'])
        # A stale but correct checkpoint is checked against its actual journal position.
        m._write_new(output/'CHECKPOINT.json',dict(sequence=1,last=events[0]['sha256'],completed=0,adopted=0))
        def worker(job):calls.append(job['rep']);return artificial_worker(job)
        self.assertEqual(self.execute(manifest,worker)['total'],3)
        self.assertEqual(calls,[1,2])

    def test_failed_started_job_and_partial_journal_remain_blocked(self):
        manifest=self.manifest()
        with self.assertRaises(m.MethodStop):self.execute(manifest,failed_worker)
        output=Path(manifest['output']);before=m.digest(output/'journal.jsonl')
        self.assertTrue(list(output.glob('STOP-*.json')))
        self.assertEqual(len(list((output/'datasets').rglob('*.npz'))),1)
        with self.assertRaisesRegex(m.MethodStop,'unresolved'):self.execute(manifest)
        self.assertEqual(m.digest(output/'journal.jsonl'),before)
        other=self.manifest('partial');self.seal_first(other)
        with (Path(other['output'])/'journal.jsonl').open('ab') as f:f.write(b'{"unfinished":')
        with self.assertRaisesRegex(m.MethodStop,'partial journal'):self.execute(other)

    def test_hash_seed_record_and_checkpoint_tampering_stops(self):
        for category in ('result','dataset','checkpoint','binding'):
            manifest=self.manifest(category);self.seal_first(manifest);output=Path(manifest['output'])
            if category=='result':
                path=next((output/'records').rglob('*.json'));row=m._json(path);row['data_seed']+=1;path.write_bytes(m.canonical(row))
            elif category=='dataset':next((output/'datasets').rglob('*.npz')).write_bytes(b'changed')
            elif category=='checkpoint':m._write_new(output/'CHECKPOINT.json',dict(sequence=2,last='f'*64,completed=1,adopted=0))
            else:manifest['batch_size']=64
            with self.assertRaises(m.MethodStop):self.execute(manifest)

    def test_source_catalog_runtime_and_worker_limits_before_dispatch(self):
        for field in ('source','catalog','runtime','workers'):
            manifest=self.manifest(field)
            if field=='source':manifest['sources'][m.CRITICAL[0]]='0'*64
            elif field=='catalog':manifest['catalog_sha256']='0'*64
            elif field=='runtime':manifest['runtime']['numpy']='wrong'
            else:manifest['resources']['workers']=5
            with self.assertRaises(m.MethodStop):self.execute(manifest)
            self.assertFalse(Path(manifest['output']).exists())

    def test_typed_infinities_preserve_ids_and_undefined_estimates(self):
        row=dict(group_id='Infinity',note='NaN',result=dict(endpoints={'NaN':
            dict(estimate='NaN',se='Infinity',lower='-Infinity',upper='Infinity',status='variance_zero')}))
        decoded=m.decode_record(row);ep=decoded['result']['endpoints']['NaN']
        self.assertEqual(decoded['group_id'],'Infinity');self.assertEqual(decoded['note'],'NaN')
        self.assertTrue(math.isnan(ep['estimate']));self.assertEqual(ep['lower'],-math.inf)
        self.assertEqual(ep['upper'],math.inf)
        row['result']['endpoints']['NaN']['upper']='1.5'
        with self.assertRaises(m.MethodStop):m.decode_record(row)

    def test_resource_limits_stop_before_dispatch_and_use_one_inventory(self):
        manifest=self.manifest();manifest['resources']['max_working_bytes']=1
        calls=[]
        with self.assertRaises(m.MethodStop):self.execute(manifest,lambda job:calls.append(job))
        self.assertEqual(calls,[])
        output=self.base/'guard';output.mkdir()
        limits=self.manifest('unused')['resources'];guard=m.ResourceGuard(output,limits,memory_reader=lambda:1024)
        with patch.object(Path,'rglob',side_effect=AssertionError('no repeated tree scan')):
            guard.check();guard.add(100);guard.check()
        guard.reserved=limits['max_working_bytes']
        with self.assertRaises(m.MethodStop):guard.check()

    def build_prefix(self,name,duplicate=False):
        output=self.base/name;output.mkdir();(output/'datasets').mkdir()
        contract=catalog();sources=dict(self.sources)
        old_reporter=output/'old-reporter.py';old_reporter.write_text('# preserved old reporter fixture\n')
        old_source=archive(output/'legacy-source.zip',{**{p:ROOT/p for p in m.CRITICAL},'old-reporter.py':old_reporter})
        sources['legacy-source.zip']=old_source['sha256']
        sources['old-reporter.py']=m.digest(old_reporter)
        old=dict(project_root=str(output),groups=list(m.PREFIX_GROUPS),per_group=100,bootstrap_reps=19999,
                 runtime=m.runtime(),catalog_sha256=m.object_digest(contract),sources=sources)
        m._write_new(output/'EXECUTION.json',old)
        records=[]
        for gid in m.PREFIX_GROUPS:
            spec=group(gid)
            for rep in range(100):
                dataset=gid.replace('/','-')+'-'+str(rep).zfill(5)+'.npz'
                job=dict(spec=spec,rep=rep,output=str(output/'datasets'),dataset=dataset,
                         data_seed=seed(gid,spec['n'],rep,'data'),bootstrap_seed=seed(gid,spec['n'],rep,'bootstrap'))
                records.append(artificial_worker(job))
        if duplicate:records[-1]=deepcopy(records[0])
        (output/'results.jsonl').write_bytes(b''.join(m.canonical(row)+b'\n' for row in records))
        m._write_new(output/'RESOURCE-RESULT.json',dict(status='complete',count=700))
        files={str(p.relative_to(output)):p for p in output.rglob('*') if p.is_file() and p.name!='legacy-source.zip'}
        archived=archive(output/'prefix-evidence.zip',files)
        m._write_new(output/'ARCHIVE-READBACK.json',dict(sha256=archived['sha256'],member_sha256=archived['members']))
        binding=dict(directory=str(output),execution_sha256=m.digest(output/'EXECUTION.json'),
                     readback_sha256=m.digest(output/'ARCHIVE-READBACK.json'),results_sha256=m.digest(output/'results.jsonl'),
                     archive_sha256=archived['sha256'])
        return binding,contract

    def test_exact_700_adoption_and_399300_pending_without_generating(self):
        binding,contract=self.build_prefix('prefix')
        sources={**self.sources,'new-reporter.py':'b'*64,'new-orchestrator.py':'c'*64}
        with patch.object(m,'generate') as generator,patch.object(m,'analyze') as analyze:
            adopted=m.verify_prefix(binding,contract,sources,m.runtime())
            generator.assert_not_called();analyze.assert_not_called()
        self.assertEqual(len(adopted),700)
        self.assertEqual(m.planned_counts(),dict(groups=44,total=400000,reused=700,remaining=399300))
        self.assertEqual(sum(key not in adopted for key in m.identities(contract)),399300)
        changed=dict(sources);changed[m.CRITICAL[1]]='0'*64
        with self.assertRaisesRegex(m.MethodStop,'result-determining'):m.verify_prefix(binding,contract,changed,m.runtime())
        invalid=deepcopy(binding);invalid['archive_sha256']='0'*64
        with self.assertRaises(m.MethodStop):m.verify_prefix(invalid,contract,sources,m.runtime())

    def test_duplicate_prefix_identity_is_not_silently_reused(self):
        binding,contract=self.build_prefix('duplicate',duplicate=True)
        with self.assertRaisesRegex(m.MethodStop,'duplicate'):m.verify_prefix(binding,contract,self.sources,m.runtime())

    def test_live_final_documents_must_match_the_verified_archive(self):
        for name in ('COMPLETE.json','SUMMARY.json'):
            manifest=self.manifest('tamper-'+name,repetitions=1);self.execute(manifest)
            output=Path(manifest['output']);path=output/name;value=m._json(path)
            if name=='COMPLETE.json':value.update(total=999,study_release=True)
            else:value['accepted']=True
            path.write_bytes(m.canonical(value))
            with self.assertRaisesRegex(m.MethodStop,'differs from archive'):
                self.execute(manifest,lambda job:(_ for _ in ()).throw(AssertionError('no new worker')))

    def test_rss_limit_after_summary_is_checked_and_failure_is_retained(self):
        manifest=self.manifest('post-summary',repetitions=1);output=Path(manifest['output'])
        def memory():return 9*1024**3 if (output/'SUMMARY.json').exists() else 1024
        with self.assertRaisesRegex(m.MethodStop,'finalization stopped'):
            m.execute(manifest,worker=artificial_worker,memory_reader=memory,
                      executor_factory=lambda n:ThreadPoolExecutor(max_workers=n))
        self.assertTrue((output/'FINAL-STOP.json').exists())
        self.assertTrue((output/'SUMMARY.json').exists())
        self.assertFalse((output/'ARCHIVE.json').exists())
        with self.assertRaisesRegex(m.MethodStop,'unresolved finalization'):
            self.execute(manifest)

    def test_resource_stop_during_summary_archive_and_readback(self):
        original_summary=m.summarize;original_verify=m.verify_archive
        for stage in ('summary','archive','readback'):
            manifest=self.manifest('during-'+stage,repetitions=1);output=Path(manifest['output']);over=[False]
            def memory():
                if stage=='archive' and (output/'evidence.zip').exists():over[0]=True
                return 9*1024**3 if over[0] else 1024
            def summary(contract,records,*,check_resources=None):
                def marked():
                    for row in records:
                        if stage=='summary':over[0]=True
                        yield row
                return original_summary(contract,marked(),check_resources=check_resources)
            def verify(path,*args,**kwargs):
                if stage=='readback' and Path(path).name=='evidence.zip':over[0]=True
                return original_verify(path,*args,**kwargs)
            with patch.object(m,'summarize',side_effect=summary),patch.object(m,'verify_archive',side_effect=verify):
                with self.assertRaisesRegex(m.MethodStop,'finalization stopped'):
                    m.execute(manifest,worker=artificial_worker,memory_reader=memory,
                              executor_factory=lambda n:ThreadPoolExecutor(max_workers=n))
            self.assertTrue(over[0]);self.assertTrue((output/'FINAL-STOP.json').exists())
            self.assertFalse((output/'ARCHIVE.json').exists())
            self.assertEqual(len(list((output/'records').rglob('*.json'))),1)
            if stage!='summary':self.assertTrue((output/'evidence.zip').exists())

    def test_separate_backup_bytes_and_final_resource_accounting(self):
        output=self.base/'byte-accounting';output.mkdir()
        (output/'SUMMARY.json').write_bytes(b'a'*100)
        (output/'evidence.zip').write_bytes(b'b'*200)
        limits=self.manifest('not-run')['resources'];guard=m.ResourceGuard(output,limits,memory_reader=lambda:1024)
        self.assertEqual(guard.bytes,100);self.assertEqual(guard.backup_bytes,200)
        guard.add(50);self.assertEqual(guard.bytes,150)
        guard.limits['max_backup_bytes']=199
        with self.assertRaisesRegex(m.MethodStop,'backup output limit'):guard.check()


if __name__=='__main__':unittest.main()
