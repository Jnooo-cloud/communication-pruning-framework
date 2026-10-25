"""Small explicit-weight technical cases, not calibration simulations."""
import unittest
import numpy as np
from study_preparation.intervals import analyze, hoeffding, empirical_quantile, secondary_quality
from communication_pruning.paired_iid import intervals as original

PRIMARY = [dict(id='P-D', kind='mean', numerator=[1,0,0], bounds=[-1,1]),
           dict(id='P-C', kind='ratio', numerator=[0,1,0], denominator=[0,0,1])]


class IntervalsTests(unittest.TestCase):
    def test_primary_parity_existing_candidate_explicit_weights(self):
        x = np.array([[-1,.001,.002],[0,.002,.001],[1,.004,.003]])
        c = np.array([6,8,6])
        w = np.array([[5,10,5],[7,6,7],[8,8,4],[4,8,8],[6,8,6]])
        before = original(x,c,resample_counts=w)
        after = analyze(x,c,PRIMARY,resample_counts=w,batch_size=2)['endpoints']
        self.assertAlmostEqual(before['lower_delta'],after['P-D']['lower'],places=12)
        self.assertAlmostEqual(before['upper_rho'],after['P-C']['upper'],places=12)
        self.assertEqual(before['quality_status'],after['P-D']['status'])
        self.assertEqual(before['cost_status'],after['P-C']['status'])

    def test_batch_partition_keeps_draw_stream(self):
        x = np.array([[-1,1,2],[0,2,1],[1,4,3.]])
        c = np.array([60,80,60])
        a = analyze(x,c,PRIMARY,rng=np.random.Generator(np.random.PCG64(987)),bootstrap_reps=31,batch_size=7)
        b = analyze(x,c,PRIMARY,rng=np.random.Generator(np.random.PCG64(987)),bootstrap_reps=31,batch_size=31)
        self.assertEqual(a,b)

    def test_one_undefined_draw_is_retained(self):
        x=np.array([[-1,1,1],[1,1,2.]])
        c=[10,10];w=[[10,10],[20,0]]
        e=analyze(x,c,PRIMARY,resample_counts=w)['endpoints']
        self.assertEqual(e['P-D']['status'],'resample_undefined')
        self.assertEqual(e['P-C']['status'],'resample_undefined')
        self.assertEqual(e['P-D']['undefined_resamples'],1)
        self.assertEqual((e['P-D']['lower'],e['P-D']['upper']),(-1,1))
        self.assertEqual((e['P-C']['lower'],e['P-C']['upper']),(0,float('inf')))

    def test_degenerate_and_weak_denominator(self):
        e=analyze([[0,1,0]],[20],PRIMARY,resample_counts=[[20]])['endpoints']
        self.assertEqual(e['P-D']['status'],'variance_zero')
        self.assertEqual(e['P-C']['status'],'denominator_zero')
        e=analyze([[-1,1,1],[1,1,0]],[1,19],PRIMARY,resample_counts=[[1,19]])['endpoints']
        self.assertEqual(e['P-C']['status'],'denominator_weak')

    def test_proportional_ratio_and_constant_h(self):
        x=np.array([[1,2,3,4],[2,4,4,5.]])
        ep=[dict(id='r',kind='ratio',numerator=[0,1,0,0],denominator=[1,0,0,0]),
            dict(id='h',kind='mean',numerator=[0,0,-1,1])]
        e=analyze(x,[10,10],ep,resample_counts=[[8,12],[12,8]])['endpoints']
        self.assertEqual(e['r']['status'],'variance_zero')
        self.assertEqual(e['h']['status'],'variance_zero')
        self.assertEqual((e['h']['lower'],e['h']['upper']),(-float('inf'),float('inf')))

    def test_cost_scaling(self):
        x=np.array([[-1,1,2],[0,2,1],[1,4,3.]])
        w=[[6,8,6],[8,7,5],[4,10,6]]
        a=analyze(x,[6,8,6],PRIMARY,resample_counts=w)['endpoints']['P-C']
        x[:,1:]*=.00024
        b=analyze(x,[6,8,6],PRIMARY,resample_counts=w)['endpoints']['P-C']
        for k in ('estimate','se','lower','upper'):
            self.assertAlmostEqual(a[k],b[k],places=12)

    def test_invalid_or_unpaired_input_rejected(self):
        for counts,weights in [([10,10],[[9,10]]),([20,0],[[10,10]]),([10,10],[[10.5,9.5]])]:
            with self.assertRaises(ValueError):
                analyze([[-1,1,1],[1,1,2]],counts,PRIMARY,resample_counts=weights)

    def test_quantiles_and_hoeffding(self):
        self.assertEqual(empirical_quantile(range(19999),.025),499)
        self.assertEqual(empirical_quantile(range(19999),.975),19499)
        result=hoeffding(np.zeros(2952))
        self.assertGreater(result['radius'],0)
        self.assertLessEqual(result['radius'],.05)
        twice=hoeffding(np.zeros(2952),(-2,2))
        self.assertAlmostEqual(twice['radius'],2*result['radius'])
        with self.assertRaises(ValueError):hoeffding([2.1],(-2,2))

    def test_all_secondary_quality_contrasts(self):
        reference=secondary_quality([[0,0,0,0,1,0]],'R')
        self.assertEqual(len(reference),9)
        self.assertEqual(reference['R/01']['estimate'],1)
        self.assertEqual(reference['R/06']['estimate'],0)
        fault=secondary_quality([[1,0,0,1]],'F')
        self.assertEqual(fault['d_Q_minus_d_F']['estimate'],-2)
        self.assertEqual(len(secondary_quality([[1,0]],'T1')),1)
        with self.assertRaises(ValueError):secondary_quality([[1,0,0]],'F')


if __name__ == '__main__':
    unittest.main()
