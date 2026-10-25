import math
import unittest
import copy
import hashlib
from pathlib import Path
import weakref
from study_preparation.cases import catalog as full_catalog
from study_preparation.calibration import binomial_upper,holm,wilson,summarize


class CalibrationTests(unittest.TestCase):
    def test_exact_binomial_small_enumeration(self):
        for n in (1,10,20):
            for k in range(n+1):
                expected=math.fsum(math.comb(n,j)*.025**j*.975**(n-j) for j in range(k,n+1))
                self.assertAlmostEqual(binomial_upper(k,n),expected,places=13)

    def test_wilson_zero_and_holm_stepdown(self):
        low,high=wilson(0,10000)
        self.assertAlmostEqual(low,0,places=15)
        self.assertGreater(high,0)
        self.assertLess(high,.001)
        e=[dict(id='b',p=.001),dict(id='a',p=.001),dict(id='c',p=.03)]
        self.assertEqual(holm(e),['a','b'])

    def test_partial_results_never_accepted(self):
        catalog={'groups':[dict(id='x',n=9040,repetitions=10000,endpoints=[dict(id='d',truth=0,h=.015,information_width_required=True)])],
                 'controls':[],'events':[dict(id='x/d/L',group_id='x',endpoint_id='d',direction='L')]}
        row=dict(group_id='x',rep=0,result=dict(n=9040,bootstrap_reps=19999,
                 endpoints={'d':dict(estimate=0,lower=-.01,upper=.01,status='ok')}))
        result=summarize(catalog,[row])
        self.assertFalse(result['accepted']);self.assertFalse(result['complete'])
        self.assertIsNone(result['holm_rejections'])
        with self.assertRaises(ValueError):summarize(catalog,[row,row])

    def test_streaming_parity_with_preserved_z44_on_small_full_and_partial_fixtures(self):
        source=Path(__file__).resolve().parents[1]/'runs/Z45-ANSCHLUSS-001/method/reference-z44-calibration.py'
        content=source.read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(),'163fc51dc17eede1729b490accfc811c9e93be42bf129f44752a04d6d9b33ebc')
        original={};exec(compile(content,str(source),'exec'),original)
        contract=full_catalog();ids={'P/R1','P/R8','P/P3'}
        contract['groups']=[g for g in contract['groups'] if g['id'] in ids]
        contract['controls']=[g for g in contract['controls'] if g['id']=='G-Q']
        contract['events']=[e for e in contract['events'] if e['group_id'] in ids]
        rows=[]
        for group in contract['groups']+contract['controls']:
            group['repetitions']=5
            for rep in range(5):
                endpoints={}
                for e in group['endpoints']:
                    point=e['truth']+(rep-2)*e['h']
                    endpoints[e['id']]=dict(estimate=point,lower=point-e['h']/2,
                                            upper=point+e['h'],status='ok')
                    if rep==4:
                        endpoints[e['id']]=dict(estimate=math.nan,lower=-1 if e['id']=='P-D' else 0,
                                                upper=1 if e['id']=='P-D' else math.inf,status='variance_zero')
                rows.append(dict(group_id=group['id'],rep=rep,result=dict(n=group['n'],bootstrap_reps=19999,endpoints=endpoints)))
        for supplied in (rows,rows[:7],list(reversed(rows)),[]):
            before=original['summarize'](contract,copy.deepcopy(supplied))
            after=summarize(contract,iter(copy.deepcopy(supplied)))
            self.assertEqual({key:after[key] for key in before},before)
            self.assertEqual(after['control_unconditional_means']['G-Q'],contract['controls'][0]['means_fraction'])
        report=summarize(contract,rows)
        self.assertEqual(len(report['descriptive']),1)
        self.assertFalse(report['descriptive'][0]['pass_required'])
        r8=[r for r in rows if r['group_id']=='P/R8']
        expected=sum(r['result']['endpoints']['P-D']['lower']>-.03 and r['result']['endpoints']['P-C']['upper']<.9 for r in r8)
        self.assertEqual(report['descriptive'][0]['joint_successes'],expected)
        self.assertFalse(any(e['id']=='P/R8/P-J/Joint' for e in report['events']))

    def test_one_pass_iterator_does_not_retain_prior_record_objects(self):
        class Row(dict):pass
        spec=dict(id='x',n=20,repetitions=300,endpoints=[dict(id='d',truth=0,h=.01,information_width_required=True)])
        contract=dict(groups=[spec],controls=[],events=[dict(id='x/d/L',group_id='x',endpoint_id='d',direction='L')])
        references=[]
        def stream():
            for rep in range(300):
                self.assertLessEqual(sum(ref() is not None for ref in references),2)
                row=Row(group_id='x',rep=rep,result=dict(n=20,bootstrap_reps=19999,
                    endpoints={'d':dict(estimate=0.,lower=-.01,upper=.01,status='ok')}))
                references.append(weakref.ref(row));yield row
        result=summarize(contract,stream())
        self.assertTrue(result['complete'])
        self.assertEqual(result['counts'],{'x':300})

    def test_invalid_numeric_result_and_duplicate_are_not_dropped(self):
        contract=dict(groups=[dict(id='x',n=20,repetitions=1,endpoints=[dict(id='d',truth=0,h=.01,information_width_required=True)])],controls=[],events=[])
        row=dict(group_id='x',rep=0,result=dict(n=20,bootstrap_reps=19999,endpoints={'d':dict(estimate=0.,lower=-.01,upper=.01,status='ok')}))
        for value in ('Infinity',math.nan):
            damaged=copy.deepcopy(row);damaged['result']['endpoints']['d']['upper']=value
            with self.assertRaises(ValueError):summarize(contract,[damaged])
        with self.assertRaises(ValueError):summarize(contract,[row,row])


if __name__=='__main__':unittest.main()
