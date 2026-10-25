"""D-054: one explicit recovery segment, bound to the unchanged stopped phase.

No recovery of a second technical failure. Exact bytes and local cooperative
locks protect against accidental changes, not malicious or distributed writers.
"""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import json

from .configurations import bank
from .data import digest, load_task
from .evaluation import read_result
from .execution import execute
from .failure_policy import F01
from .openrouter import RESERVE, encoded, now, save_new, validate_endpoint
from .phase_budget import PhaseBudget
from .spatial_plan import validate_plan
from .study import FileGuard, StudyAdapter, StudyStop, file_hash
from .study_resume import (execution_binding, inspect_records, phase_lock,
                           read_json, result_dict)

PLAN = '2ed2c15684874722d398f0679adae88b1adb28096a8cc2c5f763d02715fe6b0b'
OLD_MANIFEST = '5649d45f84dcdeba0f14b61043ca15d6711f5bb9cba98f86038783fb3ed8a672'
OLD_CLAIM = '5019273370b20a5c6a613803bbd05cb027350d8b24ccd0075ce47c364bf4b6b8'
OLD_SOURCE = 'd936b7c296b8e937cf7892ea9a7ab8ab9f2cc765a5f3ccdb1d7f30d7aa268e6b'


def inventory(folder):
    folder = Path(folder)
    return {str(p.relative_to(folder)): file_hash(p)
            for p in sorted(folder.rglob('*')) if p.is_file()}


def contract(plan, old_folder, old_manifest, control, *, synthetic=False):
    """Create a candidate only; live constants encode the specific D-054 case."""
    old_folder, old_manifest, control = map(Path, (old_folder, old_manifest, control))
    claim = control / f"{plan['sha256']}.claim.json"
    if not synthetic and (plan['sha256'] != PLAN or file_hash(old_manifest) != OLD_MANIFEST
                          or file_hash(claim) != OLD_CLAIM):
        raise StudyStop('not the D-054 old phase')
    report = read_json(old_folder / ('report.json' if synthetic else 'resume-00001-report.json'))
    prefix, old = report['completed_slots'], report['budget']
    if (not 0 < prefix < len(plan['slots']) or report['status'] != 'stopped'
            or old['held_reservation_usd'] != str(RESERVE) or not old['poisoned']
            or old['total_cost_usd'] is not None or not old['pending']):
        raise StudyStop('not a single unknown old attempt')
    known = Decimal(old['known_cost_usd'])
    cap = Decimal(plan['proposed_phase_cap_usd'])
    if not synthetic and (prefix != 45 or known != Decimal('0.05125386') or old['calls'] != 274
            or plan['slots'][prefix]['slot_id'] != 'S00046'
            or plan['slots'][prefix]['task_id'] != '4hop1__322597_452185_53858_80699'
            or plan['slots'][prefix]['config_id'] != 'C14' or cap != Decimal('36.12')):
        raise StudyStop('changed D-054 target or budget')
    value = dict(schema='spatial-recovery/D-054-v1', plan_sha256=plan['sha256'],
        old_folder=str(old_folder.resolve()), old_manifest=str(old_manifest.resolve()),
        old_manifest_sha256=file_hash(old_manifest), old_claim_sha256=file_hash(claim),
        completed_before=prefix, old_attempts=old['calls'], old_pending=old['pending'],
        old_known_cost_usd=str(known), old_reserve_usd=str(RESERVE),
        phase_cap_usd=str(cap), segment_cap_usd=str(cap-known-RESERVE),
        segment_max_calls=sum(s['planned_calls'] for s in plan['slots'][prefix:]),
        first_slot=plan['slots'][prefix], synthetic=synthetic)
    value['sha256'] = digest(value)
    return value


def check_base(c, plan, manifest, task_ids, repeats, *, bindings, source_path, control, guard, synthetic):
    guard()
    validate_plan(plan, manifest, task_ids, repeats, bindings=bindings)
    if file_hash(source_path) != manifest['source_hashes']['train']:
        raise StudyStop('changed task source')
    if c != contract(plan, c['old_folder'], c['old_manifest'], control, synthetic=synthetic):
        raise StudyStop('changed recovery contract or reserve')
    old = Path(c['old_folder'])
    if inventory(old) != read_json(c['old_manifest']):
        raise StudyStop('old evidence changed')
    claim = read_json(Path(control) / f"{plan['sha256']}.claim.json")
    if any(claim.get(k) != v for k,v in dict(plan_sha256=plan['sha256'],
            output=str(old.resolve()), mode='synthetic' if synthetic else 'live',
            reserved_task_ids=task_ids, repeat_ids=repeats, failure_policy=F01,
            status='consumed_even_after_failure_no_resume').items()):
        raise StudyStop('old claim differs')
    if read_json(old/'plan.json') != plan:
        raise StudyStop('old plan differs')
    # Read the actual chain without editing it or passing it as a complete ledger.
    rows=[]; previous='0'*64
    for sequence,line in enumerate((old/'budget.jsonl').read_bytes().splitlines()):
        row=json.loads(line); checksum=row.pop('sha256')
        if row['sequence'] != sequence or row['previous'] != previous or digest(row) != checksum:
            raise StudyStop('old ledger damaged')
        previous=checksum; rows.append(row)
    prefix=c['completed_before']; name=plan['slots'][prefix]['slot_id']
    pairs=list(zip(rows[1:-2:2], rows[2:-2:2]))
    settlements=[]; cost=Decimal(0)
    for reserved,settled in pairs:
        if (reserved['kind'] != 'reserved' or settled['kind'] != 'settled'
                or settled['failed'] or settled['over_reservation']
                or reserved['attempt_id'] != settled['attempt_id']):
            raise StudyStop('old terminal costs not complete')
        settlements.append((settled['attempt_id'],settled['usage']))
        cost += Decimal(settled['usage']['cost_usd'])
    if (len(settlements)+1 != c['old_attempts'] or str(cost) != c['old_known_cost_usd']
            or rows[-2]['kind'] != 'reserved' or rows[-2]['attempt_id'] != c['old_pending']
            or rows[-2]['reservation_usd'] != c['old_reserve_usd']
            or rows[-1]['kind'] != 'settled' or not rows[-1]['failed']
            or rows[-1]['attempt_id'] != c['old_pending'] or rows[-1]['usage']['cost_usd'] is not None):
        raise StudyStop('old uncertainty differs')
    stem=f"{c['old_attempts']:05d}"
    checked=inspect_records(plan, manifest, source_path=source_path, folder=old,
        budget=SimpleNamespace(settlements=settlements), synthetic=synthetic,
        failure_policy=F01, slots=plan['slots'][:prefix], run_prefix=plan['sha256'][:16]+'-',
        extra_slot_files=[old/'slots'/f'{name}{suffix}' for suffix in ('.jsonl','-binding.json')],
        extra_provider_files=[old/'provider'/f'{stem}-{suffix}.json' for suffix in ('request','binding')])
    if len(checked['completed']) != prefix or checked['missing_results']:
        raise StudyStop('old prefix incomplete')
    return checked['generations']


def segment_binding(c, plan, manifest, task_ids, repeats, bindings, source_path):
    return dict(recovery=c, execution=execution_binding(plan,manifest,task_ids,repeats,
        bindings,source_path,F01))


def budget_args(c, synthetic):
    return dict(cap=Decimal(c['segment_cap_usd']), reserve=RESERVE,
        max_calls=c['segment_max_calls'], binding=c['sha256'], allow_synthetic=synthetic)


def claim_path(control, plan):
    return Path(control)/f"{plan['sha256']}.recovery-D054.claim.json"


def inspect_segment(c, plan, manifest, task_ids, repeats, *, bindings, source_path,
                    folder, control, guard, synthetic, old_generations):
    folder=Path(folder)
    expected=segment_binding(c,plan,manifest,task_ids,repeats,bindings,source_path)
    if (read_json(folder/'recovery-binding.json') != expected
            or read_json(claim_path(control,plan)) != dict(contract_sha256=c['sha256'],
                output=str(folder.resolve()), author_decision='D-054', single_recovery=True)):
        raise StudyStop('segment source or one-time claim changed')
    budget=PhaseBudget.read_completed(folder/'budget.jsonl',**budget_args(c,synthetic))
    checked=inspect_records(plan,manifest,source_path=source_path,folder=folder,budget=budget,
        synthetic=synthetic,failure_policy=F01,slots=plan['slots'][c['completed_before']:],
        run_prefix=plan['sha256'][:16]+'-R1-',initial_generations=old_generations)
    if checked['missing_results']:
        raise StudyStop('missing derived recovery result; no dispatch')
    guard()
    evidence=inventory(folder); evidence['@claim']=file_hash(claim_path(control,plan))
    return dict(budget=budget,generations=checked['generations'],
        completed_slots=c['completed_before']+len(checked['completed']),
        resume_token=digest(evidence),evidence=evidence)


def inspect_recovery(c, plan, manifest, task_ids, repeats, *, bindings, source_path,
                     folder, control, guard, synthetic=False):
    with phase_lock(control,plan):
        generations=check_base(c,plan,manifest,task_ids,repeats,bindings=bindings,
            source_path=source_path,control=control,guard=guard,synthetic=synthetic)
        return inspect_segment(c,plan,manifest,task_ids,repeats,bindings=bindings,
            source_path=source_path,folder=folder,control=control,guard=guard,
            synthetic=synthetic,old_generations=generations)


def run_recovery(c, plan, manifest, task_ids, repeats, *, bindings, source_path,
                 folder, control, guard, transport, synthetic=False, resume_from=None,
                 stop_after_slots=None):
    with phase_lock(control,plan):
        generations=check_base(c,plan,manifest,task_ids,repeats,bindings=bindings,
            source_path=source_path,control=control,guard=guard,synthetic=synthetic)
        folder=Path(folder); prefix=c['completed_before']; label=''
        limit=len(plan['slots']) if stop_after_slots is None else stop_after_slots
        if type(limit) is not int or not prefix < limit <= len(plan['slots']):
            raise StudyStop('invalid recovery checkpoint')
        if resume_from is None:
            save_new(claim_path(control,plan),encoded(dict(contract_sha256=c['sha256'],
                output=str(folder.resolve()),author_decision='D-054',single_recovery=True)))
            folder.mkdir(parents=True,exist_ok=False)
            for sub in ('slots','provider'): (folder/sub).mkdir()
            save_new(folder/'recovery-binding.json',encoded(segment_binding(c,plan,manifest,
                task_ids,repeats,bindings,source_path)))
            budget=PhaseBudget(folder/'budget.jsonl',**budget_args(c,synthetic))
        else:
            state=inspect_segment(c,plan,manifest,task_ids,repeats,bindings=bindings,
                source_path=source_path,folder=folder,control=control,guard=guard,
                synthetic=synthetic,old_generations=generations)
            if resume_from != state['resume_token'] or state['completed_slots'] >= limit:
                raise StudyStop('stale token or no remaining slots')
            prefix=state['completed_slots']; budget=state['budget']; generations=state['generations']
            label=f"resume-{len(list(folder.glob('resume-*-start.json')))+1:05d}-"
            save_new(folder/f'{label}start.json',encoded(dict(resume_from=resume_from,
                completed_before=prefix,evidence_before=state['evidence'],started_utc=now())))
        report=dict(status='started',contract_sha256=c['sha256'],completed_slots=prefix,
            completed_before=prefix,mode='synthetic' if synthetic else 'live',author_decision='D-054')
        try:
            status,raw=transport('models/google/gemini-2.5-flash-lite/endpoints')
            save_new(folder/f'{label}endpoint.json',raw)
            save_new(folder/f'{label}endpoint-retrieval.json',encoded(dict(utc=now(),http_status=status)))
            if status != 200: raise StudyStop('catalog unavailable')
            validate_endpoint(raw)
            adapter=StudyAdapter(folder/'provider',transport,budget,synthetic=synthetic,failure_policy=F01)
            adapter.generations.update(generations)
            configs={x.config_id:x for x in bank()}; last=None
            for slot in plan['slots'][prefix:limit]:
                guard()
                if last != slot['task_id']:
                    task,reference=load_task(source_path,slot['task_id'],manifest,phase='spatial')
                    last=slot['task_id']
                public='task-'+digest([manifest['source_hashes']['train'],slot['task_id']])
                if task.task_id != public or reference.task_id != public:
                    raise StudyStop('task identity changed')
                name=slot['slot_id']; run_id=plan['sha256'][:16]+'-R1-'+name
                save_new(folder/'slots'/f'{name}-binding.json',encoded({**slot,'run_id':run_id,
                    'public_task_id':public,'plan_sha256':plan['sha256']}))
                journal=folder/'slots'/f'{name}.jsonl'; config=configs[slot['config_id']]
                execute(task,config,adapter,rounds=2,run_id=run_id,journal_path=journal,
                    producer_limit=1024,failure_policy=F01)
                value=read_result(journal,config,task,reference,family_id=slot['family_id'],
                    phase='spatial',repeat=slot['repeat'])
                save_new(folder/'slots'/f'{name}-result.json',encoded(result_dict(value)))
                report['completed_slots']+=1
            guard()
            report['status']='completed' if limit==len(plan['slots']) else 'paused_at_checkpoint'
        except BaseException as error:
            report.update(status='stopped',error_type=type(error).__name__)
            raise
        finally:
            report.update(finished_utc=now(),budget=budget.snapshot(),
                common_budget=dict(phase_cap_usd=c['phase_cap_usd'],
                    old_known_cost_usd=c['old_known_cost_usd'],old_unknown_reserve_usd=c['old_reserve_usd'],
                    known_cost_usd=str(Decimal(c['old_known_cost_usd'])+budget.cost),
                    total_cost_usd=None, # Old unresolved cost remains unknown even after successful recovery.
                    known_plus_held_usd=str(Decimal(c['old_known_cost_usd'])+Decimal(c['old_reserve_usd'])+
                        budget.cost+Decimal(budget.snapshot()['held_reservation_usd'])),
                    dispatch_attempts=c['old_attempts']+budget.calls))
            save_new(folder/f'{label}report.json',encoded(report))
        return report


def result_paths(c, plan, folder, completed_slots, *, require_complete=True):
    """One terminal row per planned slot; never include the old partial attempt."""
    if require_complete and completed_slots != len(plan['slots']):
        raise StudyStop('no training on an incomplete grid')
    if not c['completed_before'] <= completed_slots <= len(plan['slots']):
        raise StudyStop('invalid complete prefix')
    return [(Path(c['old_folder']) if i<c['completed_before'] else Path(folder)) /
        'slots'/f"{slot['slot_id']}-result.json" for i,slot in enumerate(plan['slots'][:completed_slots])]


def recovery_candidate(root, source_zip, source_manifest):
    """Prepare exact source/data/old-evidence binding without loading a key."""
    from .study_release import candidate, bound_metadata
    root=Path(root).resolve(); base=root/'eval-harness/eval'
    value=candidate(root,source_zip,source_manifest)
    plan,_,_,_,_,_=bound_metadata(root)
    c=contract(plan,base/'runs/Z26-SPATIAL-001',base/'runs/Z26-STOP-002/run-manifest.json',
        base/'study-control/spatial')
    old_source=base/'runs/Z26-SOURCE-003/source.zip'
    if file_hash(old_source) != OLD_SOURCE:
        raise StudyStop('old source package changed')
    value.update(schema='spatial-recovery-release/D-054-v1',recovery=c,
        segment_cap_usd=c['segment_cap_usd'],segment_max_calls=c['segment_max_calls'])
    value['files'].update({str(old_source):OLD_SOURCE,c['old_manifest']:OLD_MANIFEST,
        str(base/'study-control/spatial'/f'{PLAN}.claim.json'):OLD_CLAIM})
    value['files'].update({str(Path(c['old_folder'])/n):h for n,h in read_json(c['old_manifest']).items()})
    FileGuard(value['files'])()
    return value


def live_context(root, release_path):
    """Validate authorization, local backup and exact source before any transport."""
    from .study_release import bound_metadata
    from .technical import DATA_PATH
    root,release_path=Path(root).resolve(),Path(release_path).resolve()
    release=read_json(release_path)
    if release.get('status') != 'authorized_by_author' or release.get('author_decision') != 'D-054':
        raise StudyStop('D-054 author release required')
    backup=release.get('backup_evidence')
    if (not isinstance(backup,dict) or set(backup) != {'path','sha256','location_kind','location_description','author_decision'}
            or backup['location_kind'] != 'local' or backup['author_decision'] != 'D-054'
            or not isinstance(backup['location_description'],str) or not backup['location_description'].strip()):
        raise StudyStop('D-054 verified local backup required')
    expected=recovery_candidate(root,release['source_zip'],release['source_manifest'])
    expected.update(status='authorized_by_author',author_decision='D-054',backup_evidence=backup)
    if release != expected:
        raise StudyStop('release differs from recovery candidate')
    files={**release['files'],str(release_path):file_hash(release_path),backup['path']:backup['sha256']}
    guard=FileGuard(files);guard()
    plan,manifest,ids,repeats,bindings,_=bound_metadata(root)
    return dict(c=release['recovery'],plan=plan,manifest=manifest,task_ids=ids,repeats=repeats,
        bindings=bindings,source_path=root/DATA_PATH/'musique_ans_v1.0_train.jsonl',
        control=root/'eval-harness/eval/study-control/spatial',guard=guard,synthetic=False)


def run_live_recovery(root, release_path, folder, *, resume_from=None, stop_after_slots=None):
    from .openrouter import Transport, load_key
    context=live_context(root,release_path)
    client=None
    def transport(endpoint,body=None):
        nonlocal client
        if client is None:
            client=Transport(load_key(Path(root)/'.env',source='file'))
        return client(endpoint,body)
    return run_recovery(**context,folder=folder,transport=transport,
        resume_from=resume_from,stop_after_slots=stop_after_slots)
