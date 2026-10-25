"""D-055 continuation of the frozen Z26 prefix, without replacing model answers."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .configurations import bank
from .contracts import Message, Request
from .data import digest, load_task
from .evaluation import read_result
from .execution import execute
from .failure_policy import F01, ModelFailure
from .journal import read_journal
from .openrouter import RESERVE, decode_billing, encoded, now, save_new, validate_endpoint
from .rate_limit import RateAdapter, RateStop
from .spatial_plan import validate_plan
from .study import FileGuard, StudyStop, file_hash
from .study_recovery import PLAN, inventory
from .study_resume import execution_binding, phase_lock, read_json, result_dict


def budget_arguments(c):
    return dict(cap=Decimal(c['remaining_cap_usd']), reserve=RESERVE,
                max_calls=c['remaining_max_calls'], binding=digest(c))


def claim_value(c, folder):
    return dict(author_decision='D-055', contract_sha256=digest(c),
                output=str(Path(folder).resolve()), single_continuation=True)


def claim_path(control, plan):
    return Path(control)/f"{plan['sha256']}.continuation-D055.claim.json"


def binding(c, plan, manifest, task_ids, repeats, bindings, source_path):
    return dict(contract=c, execution=execution_binding(plan, manifest, task_ids,
        repeats, bindings, source_path, F01))


def check_context(c, plan, manifest, task_ids, repeats, bindings, source_path, guard, base_guard):
    guard(); base_guard()
    validate_plan(plan, manifest, task_ids, repeats, bindings=bindings)
    if (c['plan_sha256'] != plan['sha256']
            or file_hash(source_path) != manifest['source_hashes']['train']
            or Decimal(c['phase_cap_usd']) != Decimal(c['old_known_cost_usd'])
                + Decimal(c['old_reserve_usd']) + Decimal(c['remaining_cap_usd'])
            or type(c['completed_before']) is not int
            or not 0 <= c['completed_before'] < len(plan['slots'])):
        raise StudyStop('D-055 phase binding differs')


def make_adapter(c, folder, transport, *, restore, audit_only=False, adapter_options=None):
    return RateAdapter(Path(folder)/'provider', transport, budget_args=budget_arguments(c),
        base_generations=c['base_generations'], seeds=c['seeds'], restore=restore,
        audit_only=audit_only, **(adapter_options or {}))


def run_id(c, plan, slot):
    # Keep the original logical namespace, including IDs embedded in messages.
    # A new physical journal does not change the scientific request.
    return c['run_prefix']+slot['slot_id']


def inspect_locked(c, plan, manifest, task_ids, repeats, *, bindings, source_path,
                   folder, control, guard, base_guard, adapter_options=None):
    check_context(c, plan, manifest, task_ids, repeats, bindings, source_path, guard, base_guard)
    folder = Path(folder)
    if (read_json(claim_path(control, plan)) != claim_value(c, folder)
            or read_json(folder/'binding.json') != binding(c, plan, manifest, task_ids,
                                                        repeats, bindings, source_path)):
        raise StudyStop('continuation claim or source differs')
    adapter = make_adapter(c, folder, None, restore=True, audit_only=True, adapter_options=adapter_options)
    configs = {x.config_id:x for x in bank()}
    completed, expected, used, cache = c['completed_before'], set(), set(), {}
    pending_slot = False
    for slot in plan['slots'][c['completed_before']:]:
        name = slot['slot_id']; directory = folder/'slots'
        journals = sorted(directory.glob(f'{name}-journal-*.jsonl'))
        result_path = directory/f'{name}-result.json'
        if not journals:
            if result_path.exists(): raise StudyStop('result without journal')
            pending_slot = True
            continue
        if pending_slot: raise StudyStop('gap in continuation slots')
        if slot['task_id'] not in cache:
            cache[slot['task_id']] = load_task(source_path, slot['task_id'], manifest, phase='spatial')
        task, reference = cache[slot['task_id']]
        config = configs[slot['config_id']]
        slot_binding = {**slot, 'run_id':run_id(c, plan, slot), 'public_task_id':task.task_id,
                        'plan_sha256':plan['sha256']}
        bp = directory/f'{name}-binding.json'; expected.add(bp.name)
        if read_json(bp) != slot_binding: raise StudyStop('slot binding differs')
        terminal = None
        for n, journal in enumerate(journals, 1):
            if journal.name != f'{name}-journal-{n:05d}.jsonl' or terminal is not None:
                raise StudyStop('journal gap or reconstruction after terminal result')
            expected.add(journal.name)
            checked = read_journal(journal, config); trace = checked['trace']
            if trace['run_id'] != slot_binding['run_id'] or trace['task']['task_id'] != task.task_id:
                raise StudyStop('journal identity differs')
            # Reconstruct requests from every actual started event, including abandoned
            # journals. Their completed answers must equal durable provider evidence.
            events = trace['events']
            for i, event in enumerate(events):
                if event['kind'] != 'started': continue
                logical = event['attempt_id']; used.add(logical)
                request = Request(logical, task, event['role'], event['round'], event['instruction'],
                    tuple(Message(**m) for m in event['messages']), event['max_output_tokens'])
                from .openrouter import payload
                state = adapter.states.get(logical)
                if state is None or state['outcome'] == 'rate_limited':
                    if i != len(events)-1 or checked['sealed']:
                        raise StudyStop('journal uses an unanswered call')
                    if state and state['body'] != encoded(payload(request, producer_limit=1024)):
                        raise StudyStop('pending retry bytes differ')
                    continue
                response = adapter(request)
                if i == len(events)-1: continue  # durable response, interrupted before journal append
                actual = events[i+1]
                expected_event = dict(kind='model_failed' if isinstance(response, ModelFailure) else 'completed',
                                      attempt_id=logical, usage=response.usage.to_dict())
                expected_event.update(reason=response.reason) if isinstance(response, ModelFailure) else expected_event.update(text=response.text)
                if actual != expected_event: raise StudyStop('journal answer differs from original response')
            if checked['sealed']:
                reproduced = execute(task, config, adapter, rounds=2, run_id=slot_binding['run_id'],
                                     producer_limit=1024, failure_policy=F01)
                if reproduced != trace: raise StudyStop('terminal transcript differs from deterministic replay')
                terminal = journal
        if terminal is not None:
            value = result_dict(read_result(terminal, config, task, reference,
                family_id=slot['family_id'], phase='spatial', repeat=slot['repeat']))
            if not result_path.exists() or read_json(result_path) != value:
                raise StudyStop('missing or altered terminal result; inspect before continuation')
            expected.add(result_path.name)
            provenance = directory/f'{name}-provenance.json'; expected.add(provenance.name)
            entries = read_json(provenance)
            wanted = [dict(logical_id=e['attempt_id'], origin=adapter.states[e['attempt_id']]['origin'],
                      generation_id=adapter.states[e['attempt_id']]['generation'])
                      for e in reproduced['events'] if e['kind']=='started']
            if entries != wanted: raise StudyStop('answer provenance differs')
            completed += 1
        else:
            if result_path.exists(): raise StudyStop('partial journal has terminal result')
            pending_slot = True
    if set(p.name for p in (folder/'slots').iterdir()) != expected:
        raise StudyStop('extra slot evidence or duplicate terminal result')
    if set(adapter.states) - used - {s['logical_id'] for s in c['seeds']}:
        raise StudyStop('dispatch outside reconstructed raster')
    guard(); base_guard()
    evidence = inventory(folder)
    evidence['@claim'] = file_hash(claim_path(control, plan))
    return dict(completed_slots=completed, resume_token=digest(evidence), evidence=evidence,
                budget=adapter.budget.snapshot(), retry_attempts=adapter.retries,
                known_phase_usd=str(Decimal(c['old_known_cost_usd'])+adapter.budget.cost))


def inspect_continuation(**context):
    with phase_lock(context['control'], context['plan']):
        return inspect_locked(**context)


def run_continuation(c, plan, manifest, task_ids, repeats, *, bindings, source_path,
                     folder, control, guard, base_guard, transport, resume_from=None,
                     stop_after_slots=None, adapter_options=None):
    with phase_lock(control, plan):
        check_context(c, plan, manifest, task_ids, repeats, bindings, source_path, guard, base_guard)
        folder = Path(folder); prefix=c['completed_before']
        limit = len(plan['slots']) if stop_after_slots is None else stop_after_slots
        if type(limit) is not int or not prefix < limit <= len(plan['slots']):
            raise StudyStop('checkpoint outside remaining raster')
        if resume_from is None:
            save_new(claim_path(control, plan), encoded(claim_value(c, folder)))
            folder.mkdir(parents=True, exist_ok=False)
            for sub in ('slots','provider'): (folder/sub).mkdir()
            save_new(folder/'binding.json', encoded(binding(c, plan, manifest, task_ids, repeats, bindings, source_path)))
        else:
            checked = inspect_locked(c,plan,manifest,task_ids,repeats,bindings=bindings,source_path=source_path,
                folder=folder,control=control,guard=guard,base_guard=base_guard,adapter_options=adapter_options)
            prefix=checked['completed_slots']
            if checked['resume_token'] != resume_from or prefix >= limit:
                raise StudyStop('stale continuation token or exhausted checkpoint')
        number=len(list(folder.glob('session-*-start.json')))+1
        label=f'session-{number:05d}'
        save_new(folder/f'{label}-start.json', encoded(dict(started_utc=now(),resume_from=resume_from,
            completed_before=prefix,stop_after_slots=limit)))
        adapter=make_adapter(c,folder,transport,restore=resume_from is not None,adapter_options=adapter_options)
        report=dict(status='started',started_utc=now(),completed_slots=prefix,author_decision='D-055')
        try:
            status,raw=transport('models/google/gemini-2.5-flash-lite/endpoints')
            save_new(folder/f'{label}-endpoint.json',raw)
            save_new(folder/f'{label}-endpoint-retrieval.json',encoded(dict(utc=now(),http_status=status)))
            if status != 200: raise StudyStop('endpoint catalog unavailable')
            validate_endpoint(raw)
            configs={x.config_id:x for x in bank()}; last=None
            for slot in plan['slots'][prefix:limit]:
                guard()
                if last != slot['task_id']:
                    task,reference=load_task(source_path,slot['task_id'],manifest,phase='spatial');last=slot['task_id']
                name=slot['slot_id']; directory=folder/'slots'
                bp=directory/f'{name}-binding.json'
                if not bp.exists():
                    save_new(bp,encoded({**slot,'run_id':run_id(c,plan,slot),'public_task_id':task.task_id,'plan_sha256':plan['sha256']}))
                n=len(list(directory.glob(f'{name}-journal-*.jsonl')))+1
                journal=directory/f'{name}-journal-{n:05d}.jsonl';config=configs[slot['config_id']]
                trace=execute(task,config,adapter,rounds=2,run_id=run_id(c,plan,slot),journal_path=journal,
                    producer_limit=1024,failure_policy=F01)
                provenance=[dict(logical_id=e['attempt_id'],origin=adapter.states[e['attempt_id']]['origin'],
                    generation_id=adapter.states[e['attempt_id']]['generation']) for e in trace['events'] if e['kind']=='started']
                save_new(directory/f'{name}-provenance.json',encoded(provenance))
                value=read_result(journal,config,task,reference,family_id=slot['family_id'],phase='spatial',repeat=slot['repeat'])
                save_new(directory/f'{name}-result.json',encoded(result_dict(value)))
                report['completed_slots']+=1
            guard();base_guard()
            report['status']='completed' if limit==len(plan['slots']) else 'paused_at_checkpoint'
        except BaseException as error:
            report.update(status='stopped',error_type=type(error).__name__)
            raise
        finally:
            report.update(finished_utc=now(),budget=adapter.budget.snapshot(),retry_attempts=adapter.retries,
                known_phase_usd=str(Decimal(c['old_known_cost_usd'])+adapter.budget.cost),
                phase_total_usd=None,old_unresolved_reserve_usd=c['old_reserve_usd'],
                total_dispatches=c['old_attempts']+adapter.budget.calls)
            save_new(folder/f'{label}-report.json',encoded(report))
        return report


def result_paths(c, plan, folder, completed_slots):
    if completed_slots != len(plan['slots']): raise StudyStop('no selection from a partial grid')
    return [Path(c['base_results'][slot['slot_id']]) if i<c['completed_before'] else
            Path(folder)/'slots'/f"{slot['slot_id']}-result.json" for i,slot in enumerate(plan['slots'])]


def live_base(root, plan):
    """Pin the previously rescored 1245-slot base; never reinterpret old ledgers."""
    root=Path(root).resolve();base=root/'eval-harness/eval'
    paths={
        'runs/Z26-R1-STOP-001/run-manifest.json':'d4600fb2f3a10cb65090c2695211e240f69c4f69c5ccade15da29c139a457904',
        'runs/Z26-R1-STOP-001/diagnosis.json':'e174076b6d455669e7f829b3d4476c4ae29a8ed33e948967a44c9baec9a47029',
        'runs/Z26-R1-SOURCE-004/source.zip':'39f9007ff4a8c4dd5924a6079b909e7514f8279e9d52373f8edadddc52a74ea5',
        'runs/Z26-R1-STOP-001/source.zip':'5a5c1b07314d5b052e4eed96dcdee5368b3149ac4ef5f7b50ef8037768f8e3d0',
        'runs/Z26-SOURCE-003/source.zip':'d936b7c296b8e937cf7892ea9a7ab8ab9f2cc765a5f3ccdb1d7f30d7aa268e6b',
    }
    # The original complete-prefix manifest is the same D-054 authority constant.
    from .study_recovery import OLD_MANIFEST, OLD_CLAIM
    paths['runs/Z26-STOP-002/run-manifest.json']=OLD_MANIFEST
    paths[f'study-control/spatial/{PLAN}.claim.json']=OLD_CLAIM
    fixed={str(base/n):h for n,h in paths.items()};FileGuard(fixed)()
    old=base/'runs/Z26-SPATIAL-001';r1=base/'runs/Z26-R1-SPATIAL-001'
    r1_claim=base/f'study-control/spatial/{PLAN}.recovery-D054.claim.json'
    if read_json(r1_claim) != dict(contract_sha256='dd587960f15bd51f730970f1a787eb9a0d1f503877ec7a284a27bdde46691f4a',
            output=str(r1.resolve()),author_decision='D-054',single_recovery=True):
        raise StudyStop('original D-054 claim differs')
    fixed[str(r1_claim)]=file_hash(r1_claim)
    for folder,manifest_name in ((old,'runs/Z26-STOP-002/run-manifest.json'),
                                 (r1,'runs/Z26-R1-STOP-001/run-manifest.json')):
        expected=read_json(base/manifest_name)
        if inventory(folder) != expected: raise StudyStop('frozen old evidence differs')
        fixed.update({str(folder/n):h for n,h in expected.items()})
    diagnosis=read_json(base/'runs/Z26-R1-STOP-001/diagnosis.json')
    if (plan['sha256'] != PLAN or len(plan['slots']) != 4900
            or diagnosis['completed_total'] != 1245 or not diagnosis['all_terminal_records_rescored_equal']
            or diagnosis['known_phase_usd'] != '1.69335714'
            or diagnosis['partial_slot'] != plan['slots'][1245]):
        raise StudyStop('not the D-055 base')
    generations=[]
    for folder in (old,r1):
        for p in sorted((folder/'provider').glob('*-billing.json')):
            generations.append(read_json(p)['generation_id'])
    if len(generations) != 7564 or len(set(generations)) != 7564:
        raise StudyStop('base generation census differs')
    seeds=[]
    for n in (7290,7291):
        binding_path=r1/'provider'/f'{n:05d}-binding.json';b=read_json(binding_path)
        seed=dict(logical_id=b['attempt_id'],output_limit=1024,
                  origin=f'Z26-R1-SPATIAL-001/provider/{n:05d}',
                  received_at=datetime.fromisoformat(diagnosis['stopped_utc']).timestamp())
        for kind in ('request','response','received'):
            p=r1/'provider'/f'{n:05d}-{kind}.json'
            seed[kind]=dict(path=str(p),sha256=file_hash(p))
        if seed['request']['sha256'] != b['request_sha256']:raise StudyStop('seed request binding differs')
        seeds.append(seed)
    results={s['slot_id']:str((old if i<45 else r1)/'slots'/f"{s['slot_id']}-result.json")
             for i,s in enumerate(plan['slots'][:1245])}
    c=dict(schema='spatial-continuation/D-055-v1',plan_sha256=PLAN,completed_before=1245,
           old_attempts=7565,old_known_cost_usd='1.69335714',old_reserve_usd='0.14',
           phase_cap_usd='36.12',remaining_cap_usd='34.28664286',remaining_max_calls=22469,
           base_generations=sorted(generations),seeds=seeds,base_results=results,
           run_prefix=PLAN[:16]+'-R1-')
    if sum(s['planned_calls'] for s in plan['slots'][1245:])-1 != 22450:
        raise StudyStop('remaining logical-call bound differs')
    return c,fixed


def continuation_candidate(root, source_zip, source_manifest):
    from .study_release import candidate, bound_metadata
    root=Path(root).resolve()
    value=candidate(root,source_zip,source_manifest)
    plan,*_=bound_metadata(root)
    c,base_files=live_base(root,plan)
    value.update(schema='spatial-continuation-release/D-055-v1',continuation=c,
                 base_files=base_files,remaining_cap_usd=c['remaining_cap_usd'],
                 remaining_max_calls=c['remaining_max_calls'])
    return value


def live_context(root, release_path):
    from .study_release import bound_metadata
    from .technical import DATA_PATH
    root=Path(root).resolve();release_path=Path(release_path).resolve()
    release=read_json(release_path)
    if release.get('status') != 'authorized_by_author' or release.get('author_decision') != 'D-055':
        raise StudyStop('D-055 release required')
    backup=release.get('backup_evidence',{})
    if (set(backup) != {'path','sha256','location_kind','location_description','author_decision'}
            or backup['location_kind'] != 'local' or backup['author_decision'] != 'D-055'
            or not backup['location_description']):
        raise StudyStop('verified D-055 local backup required')
    expected=continuation_candidate(root,release['source_zip'],release['source_manifest'])
    expected.update(status='authorized_by_author',author_decision='D-055',backup_evidence=backup)
    if release != expected:raise StudyStop('release differs from candidate')
    guard=FileGuard({**release['files'],str(release_path):file_hash(release_path),backup['path']:backup['sha256']})
    base_guard=FileGuard(release['base_files']);guard();base_guard()
    plan,manifest,task_ids,repeats,bindings,_=bound_metadata(root)
    return dict(c=release['continuation'],plan=plan,manifest=manifest,task_ids=task_ids,repeats=repeats,
        bindings=bindings,source_path=root/DATA_PATH/'musique_ans_v1.0_train.jsonl',
        control=root/'eval-harness/eval/study-control/spatial',guard=guard,base_guard=base_guard)


def run_live_continuation(root,release_path,folder,*,resume_from=None,stop_after_slots=None):
    from .openrouter import Transport, load_key
    context=live_context(root,release_path);client=None
    def transport(endpoint,body=None):
        nonlocal client
        if client is None:client=Transport(load_key(Path(root)/'.env',source='file'))
        return client(endpoint,body)
    return run_continuation(**context,folder=folder,transport=transport,resume_from=resume_from,
                            stop_after_slots=stop_after_slots)
