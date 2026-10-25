"""One prospective R5 schedule; original plan, pair and budget identities stay intact."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .data import canonical, digest
from .pilot_calendar import utc, window_interval


def make_schedule(plan, *, acceptance_utc, technical_ready_utc):
    """Metadata only. Caller records and binds both actual events before using S."""
    accepted = utc(datetime.fromisoformat(acceptance_utc))
    ready = utc(datetime.fromisoformat(technical_ready_utc))
    anchor = max(accepted, ready)
    berlin = ZoneInfo('Europe/Berlin')
    lower = anchor + timedelta(minutes=30)
    start = lower.astimezone(berlin).replace(minute=0, second=0, microsecond=0)
    while start < lower:
        start += timedelta(hours=1)
    if len(plan['pairs']) != 360 or len(plan['slots']) != 720 or len(plan['windows']) != 12:
        raise ValueError('exact original 360-pair plan required')
    sections = []
    for index, window in enumerate(plan['windows']):
        moment = start + timedelta(hours=index)
        pairs = plan['pairs'][max(1, index * 30):(index + 1) * 30]
        if any(pair['window_id'] != window['window_id'] for pair in pairs):
            raise ValueError('original group assignment differs')
        sections.append({'section_id': f'R5-E{index + 1:02d}',
                         'original_window_id': window['window_id'],
                         'pair_ids': [pair['pair_id'] for pair in pairs],
                         'timezone': 'Europe/Berlin',
                         'start_utc': utc(moment).isoformat(),
                         'pair_start_before_utc': utc(moment + timedelta(minutes=25)).isoformat(),
                         'end_utc': utc(moment + timedelta(minutes=55)).isoformat()})
    schedule = {'schema': 'z42-pilot-overnight-r5-schedule/v1',
                'original_plan_sha256': plan['sha256'],
                'anchor': {'acceptance_utc': accepted.isoformat(), 'technical_ready_utc': ready.isoformat(),
                           't_utc': anchor.isoformat(), 's_utc': utc(start).isoformat()},
                'sections': sections}
    return {**schedule, 'sha256': digest(schedule)}


def validate_schedule(plan, schedule):
    anchor = schedule['anchor']
    expected = make_schedule(plan, acceptance_utc=anchor['acceptance_utc'],
                             technical_ready_utc=anchor['technical_ready_utc'])
    if canonical(schedule) != canonical(expected):
        raise ValueError('changed prospective schedule, anchor, or original assignment')
    return schedule


def section_for_pair(schedule, pair_id):
    matches = [section for section in schedule['sections'] if pair_id in section['pair_ids']]
    if len(matches) != 1:
        raise ValueError('pair lacks one exact remaining execution section')
    return matches[0]


def require_activation_time(schedule, moment):
    """Local audit may precede S, but never precedes T or survives first cutoff."""
    now = utc(moment)
    earliest = utc(datetime.fromisoformat(schedule['anchor']['t_utc']))
    if not earliest <= now < window_interval(schedule['sections'][0])[1]:
        raise ValueError('outside prospective activation interval')
