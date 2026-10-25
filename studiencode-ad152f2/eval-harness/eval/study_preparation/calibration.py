"""Fixed M-Ib/K3* report. Partial data can never yield a method acceptance."""
from math import ceil, exp, fsum, lgamma, log, log1p, sqrt, isfinite, inf
from statistics import NormalDist
from array import array


def wilson(successes, total):
    if type(total) is not int or total < 1 or not 0 <= successes <= total:
        raise ValueError('valid binomial counts required')
    z=NormalDist().inv_cdf(.975); p=successes/total; den=1+z*z/total
    mid=(p+z*z/(2*total))/den
    half=z*sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return [max(0.,mid-half),min(1.,mid+half)]


def binomial_upper(k, n, p=.025):
    """Exact binomial distribution tail (floating arithmetic, no normal approx)."""
    if type(k) is not int or type(n) is not int or not 0<=k<=n or not 0<p<1:
        raise ValueError('binomial domain')
    if k == 0:return 1.
    logs=[lgamma(n+1)-lgamma(j+1)-lgamma(n-j+1)+j*log(p)+(n-j)*log1p(-p)
          for j in range(k,n+1)]
    peak=max(logs)
    return min(1.,exp(peak)*fsum(exp(v-peak) for v in logs))


def holm(events, alpha=.025):
    ordered=sorted(events,key=lambda e:(e['p'],e['id']))
    rejected=[]; stop=False
    for i,e in enumerate(ordered):
        threshold=alpha/(len(ordered)-i)
        reject=not stop and e['p']<=threshold
        if reject:rejected.append(e['id'])
        else:stop=True
    return rejected


def _quantile(values, p):
    return sorted(values)[ceil(p*len(values))-1]


def summarize(catalog, records, *, check_resources=None):
    """Consume records once; retain IDs, counters and exact numeric widths only.

    The Z44 decision fields retain their original formula and ordering. Extra
    descriptive fields do not participate in acceptance, including R8 success.
    """
    check=check_resources or (lambda:None)
    check()
    groups={g['id']:g for g in catalog['groups']}
    control={g['id']:g for g in catalog['controls']}
    specs={**groups,**control}
    seen={gid:bytearray(g['repetitions']) for gid,g in specs.items()}
    counts={gid:0 for gid in specs}
    hits={e['id']:0 for e in catalog['events']}
    by_event={gid:[] for gid in groups}
    for event in catalog['events']:
        by_event[event['group_id']].append(event)
    state={(gid,e['id']):dict(bad=0, lower_misses=0, upper_misses=0,
                             L=array('d'), U=array('d'))
           for gid,g in specs.items() for e in g['endpoints']}
    r8_success=0
    for row in records:
        check()
        gid=row['group_id'];rep=row['rep']
        if gid not in specs or type(rep) is not int or not 0<=rep<specs[gid]['repetitions']:
            raise ValueError('unexpected group/repetition')
        if seen[gid][rep]:raise ValueError('duplicate dataset')
        spec=specs[gid]
        if row['result']['n']!=spec['n'] or row['result']['bootstrap_reps']!=19999:
            raise ValueError('changed n/B')
        endpoints=row['result']['endpoints']
        if set(endpoints)!={e['id'] for e in spec['endpoints']}:
            raise ValueError('missing or extra endpoints')
        for e in spec['endpoints']:
            value=endpoints[e['id']]; item=state[gid,e['id']]
            if any(not isinstance(value[k],(int,float)) or isinstance(value[k],bool)
                   for k in ('estimate','lower','upper')):
                raise ValueError('decoded numeric endpoint fields required')
            if any(value[k]!=value[k] for k in ('lower','upper')):
                raise ValueError('NaN bound')
            if value['status']=='ok' and not all(isfinite(value[k]) for k in ('estimate','lower','upper')):
                raise ValueError('nonfinite informative endpoint')
            item['bad']+=value['status']!='ok'
            item['lower_misses']+=value['lower']>e['truth']
            item['upper_misses']+=value['upper']<e['truth']
            if gid in groups:
                for direction,bound in [('L','lower'),('U','upper')]:
                    item[direction].append(abs(value['estimate']-value[bound]) if value['status']=='ok' else inf)
        for event in by_event.get(gid,()):
            if event['direction']=='Joint':
                hit=endpoints['P-D']['lower']>-.03 and endpoints['P-C']['upper']<.9
            else:
                item=state[gid,event['endpoint_id']]
                # Increment from this record, never from the accumulated count.
                truth=next(e['truth'] for e in spec['endpoints'] if e['id']==event['endpoint_id'])
                value=endpoints[event['endpoint_id']]
                hit=value['lower']>truth if event['direction']=='L' else value['upper']<truth
            hits[event['id']]+=bool(hit)
        if gid=='P/R8':
            r8_success+=endpoints['P-D']['lower']>-.03 and endpoints['P-C']['upper']<.9
        seen[gid][rep]=1; counts[gid]+=1
    full=all(counts[gid]==spec['repetitions'] for gid,spec in specs.items())
    event_rows=[]
    for event in catalog['events']:
        check()
        total=counts[event['group_id']]; k=hits[event['id']]
        event_rows.append(dict(id=event['id'],count=k,total=total,
                               wilson=wilson(k,total) if total else None,
                               p=binomial_upper(k,total) if full else None))
    info=[]
    for gid,spec in groups.items():
        total=counts[gid]
        for e in spec['endpoints']:
            check()
            item=state[gid,e['id']];bad=item['bad']
            entry=dict(group_id=gid,endpoint_id=e['id'],total=total,uninformative=bad,
                       uninformative_wilson=wilson(bad,total) if total else None,
                       h=e['h'],width_required=e['information_width_required'])
            for direction in ('L','U'):
                vals=item[direction]
                entry[direction]=dict(median=_quantile(vals,.5),p90=_quantile(vals,.9)) if vals else None
            entry['pass']=None
            if full:
                entry['pass']=(entry['uninformative_wilson'][1]<=.01 and
                    (not entry['width_required'] or all(entry[d]['median']<=1.01*e['h'] and
                     entry[d]['p90']<=1.25*e['h'] for d in ('L','U'))))
            info.append(entry)
    rejects=holm(event_rows) if full else None
    check()
    accepted=full and not rejects and all(e['wilson'][1]<=.04 for e in event_rows) and all(e['pass'] for e in info)
    controls=[]
    for gid,spec in control.items():
        check()
        for e in spec['endpoints']:
            item=state[gid,e['id']]
            controls.append(dict(group_id=gid,endpoint_id=e['id'],truth=e['truth'],
                total=counts[gid],lower_misses=item['lower_misses'],
                upper_misses=item['upper_misses'],uninformative=item['bad'],pass_required=False))
    descriptive=[]
    if 'P/R8' in groups:
        total=counts['P/R8']
        descriptive.append(dict(group_id='P/R8',joint_successes=r8_success,total=total,
             proportion=r8_success/total if total else None,pass_required=False,
             note='Favorable scenario; no required success rate and no additional calibration event.'))
    return dict(complete=full,accepted=bool(accepted),holm_rejections=rejects,events=event_rows,information=info,controls=controls,
                counts=counts,descriptive=descriptive,
                control_unconditional_means={gid:g.get('means_fraction') for gid,g in control.items()},
                limitation='Finite artificial scenarios only; independent technical and application review still required.')
