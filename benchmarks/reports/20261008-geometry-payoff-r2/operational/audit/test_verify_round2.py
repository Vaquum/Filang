"""Synthetic-only tests of the independent R2 auditor."""
import copy
import contextlib
import io
import json
import hashlib
import math
from pathlib import Path
import tempfile
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from experiments.geometry_information import verify_round2 as audit


class Round2OracleTests(unittest.TestCase):
    def source(self, size=20, step=60):
        opens = 100 + np.arange(size, dtype=float)
        prices = np.column_stack((opens, opens+2, opens-2, opens+1))
        return {"timestamp": np.arange(size, dtype=np.int64)*step,
                "prices": prices, "interval_seconds": step}

    def test_unpublished_protocol_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"protocol.json"
            path.write_text('{}\n')
            with self.assertRaisesRegex(ValueError, "drafts cannot run"):
                audit.admitted_protocol(path)

    def test_commit_source_freeze_ancestry_and_protocol_path_binding(self):
        path='experiments/geometry_information/round2_protocol.json';code=b'producer bytes\n'
        record={'protocol_repository_path':path,'freeze_commit':'a'*40,
            'implementation':{'git_head':'b'*40,'files':{'producer.py':hashlib.sha256(code).hexdigest()}}}
        with tempfile.TemporaryDirectory() as temporary:
            protocol=Path(temporary)/'protocol.json';protocol.write_bytes(b'{}\n')
            def answer(command,**kwargs):
                if command[1]=='merge-base':return SimpleNamespace(stdout=b'')
                return SimpleNamespace(stdout=protocol.read_bytes() if command[2].endswith(path) else code)
            with patch.object(audit.subprocess,'run',side_effect=answer):
                audit.committed_implementation(record,protocol,temporary)
            wrong=copy.deepcopy(record);wrong['protocol_repository_path']='elsewhere.json'
            with self.assertRaisesRegex(ValueError,'protocol repository path'):
                audit.committed_implementation(wrong,protocol,temporary)
            wrong=copy.deepcopy(record);wrong['implementation']['files']['producer.py']='0'*64
            with patch.object(audit.subprocess,'run',side_effect=answer),self.assertRaisesRegex(ValueError,'reported commit'):
                audit.committed_implementation(wrong,protocol,temporary)
            with patch.object(audit.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['git'])), \
                    self.assertRaisesRegex(ValueError,'commit/ancestry'):
                audit.committed_implementation(record,protocol,temporary)

    def test_array_identity_and_unreferenced_member_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);folder=root/'15m';folder.mkdir();files={}
            for filename in [*(f'year{year}.npz' for year in audit.YEARS),'bootstrap.npz']:
                np.savez(folder/filename,known=np.array([1.,2.]))
                files[filename]={'bytes':(folder/filename).stat().st_size,'sha256':audit.digest(folder/filename),
                    'arrays':{'known':{'dtype':'<f8','shape':[2],'sha256':audit.array_digest(np.array([1.,2.]))}}}
            (folder/'arrays.json').write_bytes(audit.independent.canonical_json({'schema':'filang-payoff-arrays-v1','files':files}))
            arrays=audit.Arrays(root,15)
            arrays.get('15m/year2023.npz','known',np.array([1.,2.]))
            with self.assertRaisesRegex(ValueError,'unaudited binary members'):arrays.finish()
            with self.assertRaisesRegex(ValueError,'floating values'):
                arrays.get('15m/year2023.npz','known',np.array([1.,3.]))
            with self.assertRaisesRegex(ValueError,'timeframe/path'):
                arrays.get('../15m/year2023.npz','known')
            (folder/'year2024.npz').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'bundle identity'):arrays.get('15m/year2024.npz','known')

    def test_targets_include_flat_and_exclude_boundary_gap(self):
        source = self.source()
        source["prices"][11, 0] = source["prices"][10, 0]
        result = audit.target_oracle(source, np.arange(9,20), 0, 20*60)
        self.assertTrue(result["target_valid"][9])
        self.assertEqual(result["target_log_return"][9], 0)
        self.assertEqual(result["target_simple_return"][9], 0)
        self.assertFalse(result["target_valid"][-2:].any())
        boundary = audit.target_oracle(source, np.arange(9,20), 9*60, 12*60)
        self.assertEqual(np.flatnonzero(boundary["target_valid"]).tolist(), [9])
        source["timestamp"][12:] += 60
        gapped = audit.target_oracle(source, np.arange(9,20), 0, 21*60)
        self.assertTrue(gapped["target_valid"][9])
        self.assertFalse(gapped["target_valid"][10])

    def test_ridge_direct_gradient_finite_difference(self):
        x = np.array([[0,1,1],[1,1,1],[0,0,1],[1,0,1]],dtype=float)
        y = np.array([0,-.01,.02,0]);theta=np.array([.2,.1,-.3,.05])
        objective, gradient = audit.ridge_objective_gradient(x,y,theta[0],theta[1:],.01)
        numerical=[]
        for i in range(len(theta)):
            delta=np.zeros_like(theta);delta[i]=1e-6
            p=theta+delta;m=theta-delta
            numerical.append((audit.ridge_objective_gradient(x,y,p[0],p[1:],.01)[0]-
                              audit.ridge_objective_gradient(x,y,m[0],m[1:],.01)[0])/2e-6)
        np.testing.assert_allclose(gradient,numerical,atol=1e-11,rtol=1e-9)
        self.assertGreater(objective,0)

    def test_known_ridge_optimum_and_constant_collinear_columns(self):
        x=np.array([[0,0,1],[1,1,1]],dtype=float)
        y=np.array([0,1.]);penalty=.5
        # Symmetric duplicate columns each carry 1/4; intercept 1/4;
        # constant column is zero because the intercept is unpenalized.
        _,gradient=audit.ridge_objective_gradient(x,y,.25,[.25,.25,0],penalty)
        np.testing.assert_array_equal(gradient,np.zeros(4))

    def test_model_tie_uses_original_tolerance(self):
        rows=[{"n":10,"lambda":.1,"validation_mse":1.0},
              {"n":2,"lambda":.001,"validation_mse":1.0+5e-13},
              {"n":2,"lambda":.1,"validation_mse":1.0+9e-13},
              {"n":2,"lambda":1.,"validation_mse":1.0+2e-12}]
        self.assertIs(audit.select_model(rows),rows[2])

    def test_policy_tie_cash_turnover_entry_exit_id(self):
        def row(kind,turnover,entry,exit_,identity,net=0):
            return {"policy":{"kind":kind,"entry_threshold":entry,"exit_threshold":exit_,"id":identity},
                    "metrics":{"net_log_return":net,"one_way_turnover":turnover}}
        cash=row('cash',0,0,0,'cash');active=row('threshold',0,1,-1,'a',5e-13)
        self.assertIs(audit.select_policy([active,cash]),cash)
        values=[row('threshold',4,0,0,'a'),row('threshold',2,0,0,'b'),
                row('threshold',2,1,0,'c'),row('threshold',2,1,-1,'e'),row('threshold',2,1,-1,'d')]
        self.assertIs(audit.select_policy(values),values[-1])

    def ledger(self, score, opens=None, timestamps=None, **kwargs):
        size=len(score)
        return audit.signed_cash_share_oracle(
            np.arange(size,dtype=np.int64)*60 if timestamps is None else timestamps,
            np.full(size,100.) if opens is None else opens, np.asarray(score,dtype=float),
            start=kwargs.pop('start',0),end=kwargs.pop('end',size*60),interval_seconds=60,
            fee_bps=kwargs.pop('fee_bps',0),slippage_bps=kwargs.pop('slippage_bps',0),**kwargs)

    def test_signed_threshold_equality_neutral_hold_nan_and_terminal(self):
        result=self.ledger([.1,0,-.1,np.nan,.2,.2,.2],entry_threshold=.1,exit_threshold=-.1)
        np.testing.assert_array_equal(result['trace']['position_after'],[0,1,1,1,0,1,0])
        self.assertEqual(result['metrics']['completed_trades'],2)
        self.assertTrue(result['trades'][-1]['terminal_liquidation'])
        self.assertEqual(result['trace']['signal_score'][3],-.1)
        self.assertEqual(result['trace']['signal_request'][-1],1)

    def test_gap_mark_precedes_delayed_signal_and_cash_cost_replay(self):
        result=self.ledger([.1,-.2,.1,.1,.1],opens=np.array([100,100,120,120,132]),
                           timestamps=np.array([0,60,240,300,360]),end=420,
                           entry_threshold=.1,exit_threshold=0,fee_bps=10,slippage_bps=2)
        expected=1.2*1.1*((1-.001)**2*(1-.0002)/(1+.0002))**2
        self.assertAlmostEqual(result['metrics']['net_log_return'],math.log(expected),places=14)
        self.assertEqual(result['gaps'][0]['position_before'],1)
        self.assertEqual(result['gaps'][0]['position_after'],0)
        self.assertEqual(result['gaps'][0]['delay_seconds'],120)
        reset=self.ledger([.1,.1,.1,.1,.1],start=120,end=300,entry_threshold=.1,exit_threshold=0)
        np.testing.assert_array_equal(reset['trace']['position_after'],[0,1,0])

    def test_signed_account_matches_adapter_across_gaps_nan_costs_and_controls(self):
        from experiments.geometry_information import returns
        rng=np.random.default_rng(701)
        ts=np.cumsum(rng.choice([60,120,240],size=40)).astype(np.int64)
        opens=100*np.exp(np.cumsum(rng.normal(0,.03,len(ts))))
        source={'timestamp':ts,'prices':np.column_stack((opens,opens,opens,opens)),'interval_seconds':60}
        start,end=int(ts[4]),int(ts[-1]+60)
        for policy in [*audit.policy_grid(),{'id':'buy_hold','kind':'buy_hold'}]:
            entry,exit_=policy.get('entry_threshold') or 0,policy.get('exit_threshold') or 0
            score=rng.choice([np.nan,entry,exit_,(entry+exit_)/2,-.04,.04],size=len(ts))
            for fee,slip in [(0,0),(5,1),(10,2),(20,4)]:
                expected=audit.ledger_oracle(source,score,start,end,{'fee':fee,'slippage':slip},policy)
                actual=returns.run_score_ledger(ts,opens,score,start=start,end=end,interval_seconds=60,
                    fee_bps=fee,slippage_bps=slip,score_policy=policy)
                audit.compare(actual,expected,'synthetic signed cash/share versus adapter')

    def test_bootstrap_shared_draws_global_centering_zero_day_weights(self):
        folds=[{'G_minus_B':np.array([1.,0,2]),'G_minus_cash':np.array([3.,0,6])},
               {'G_minus_B':np.array([-1.,0]),'G_minus_cash':np.array([-3.,0])}]
        summary,arrays=audit.paired_daily_bootstrap(folds,15,2,replicas=20,seed=7)
        self.assertEqual(summary['contrasts']['G_minus_B']['mean_daily_net_log_gain'],.4)
        np.testing.assert_allclose(arrays['G_minus_cash__ordinary'],3*arrays['G_minus_B__ordinary'])
        np.testing.assert_allclose(arrays['G_minus_cash__centered'],3*arrays['G_minus_B__centered'],atol=1e-15)
        np.testing.assert_allclose(arrays['G_minus_B__ordinary']-.4,arrays['G_minus_B__centered'],atol=1e-15)
        self.assertEqual(summary['p_composite'],max(x['p_one_sided'] for x in summary['contrasts'].values()))

    def test_holm_joint_year_and_activity_boundaries(self):
        results=[]
        for minutes,p in zip(audit.TIMES,[.001,.01,.02,.1,.3]):
            results.append({'minutes':minutes,'p_composite':p,'contrasts':{
                key:{'mean_daily_net_log_gain':.1,'ci95_low':.01} for key in ('G_minus_B','G_minus_cash')},
                'joint_positive_years':3,'completed_G_trades':20})
        final=audit.holm_and_conditions(copy.deepcopy(results))
        self.assertEqual([r['p_holm'] for r in final],[.005,.04,.06,.2,.3])
        self.assertTrue(final[0]['criterion_met']);self.assertFalse(final[2]['criterion_met'])
        results[0]['joint_positive_years']=2;results[1]['completed_G_trades']=19
        self.assertFalse(any(r['criterion_met'] for r in audit.holm_and_conditions(results)))

    def test_actual_compact_synthetic_producer_full_timeframe_replay(self):
        # Producer imports belong to this synthetic integration test only.
        # The auditor's implementation never imports or invokes these modules.
        from threadpoolctl import threadpool_limits
        from experiments.geometry_information import common, run_round2
        from experiments.geometry_information.tests.test_round2 import synthetic_source
        run_round2.numerical()
        with tempfile.TemporaryDirectory() as temporary,threadpool_limits(limits=1):
            base=Path(temporary);run=base/'run';data=base/'data';run.mkdir();(data/'1440m').mkdir(parents=True)
            source,keys=synthetic_source()
            csv=data/'1440m/ohlcv.csv'
            rows=np.column_stack((source['timestamps'],source['ohlc'],np.ones(source['rows'])))
            np.savetxt(csv,rows,delimiter=',',header='timestamp,open,high,low,close,volume',comments='',fmt=['%d']+['%.17g']*5)
            source['sha256']=audit.digest(csv)
            protocol=audit.json_file(audit.HERE/'round2_protocol.json')
            protocol['data']['sources']=[{**protocol['data']['sources'][0],'minutes':1440,'prepared_csv_sha256':source['sha256']}]
            protocol['inference']['bootstrap']['replicates']=7
            (run/'protocol.json').write_bytes(audit.independent.canonical_json(protocol))
            (run/'provenance.json').write_text('{}\n')
            options={'out':str(run),'data_dir':str(data),'keys_dir':'synthetic-only',
                'protocol_sha256':audit.digest(run/'protocol.json'),'implementation_sha256':'e'*64}
            with patch.object(common,'load_source',return_value=source),patch.object(common,'decode_keys',return_value=keys), \
                    contextlib.redirect_stdout(io.StringIO()):
                run_round2.timeframe_job(options,1440)
            raw=audit.independent.load_source(csv,86400)
            receipt={'minutes':1440,'keys_file_sha256':keys['keys_sha256'],'features':{}}
            for n in audit.HISTORIES:
                for family in audit.FAMILIES:
                    features=audit.independent.raw_features(raw['prices'],keys['indices'],n,family)
                    receipt['features'][family+str(n)]={'sha256':audit.array_digest(features)}
            args=SimpleNamespace(run=run,data_dir=data,protocol=run/'protocol.json')
            with contextlib.redirect_stdout(io.StringIO()):
                _,coverage,error,gradient,members=audit.audit_timeframe(args,protocol,receipt,{'implementation':{'sha256':'e'*64}})
            self.assertEqual(coverage,{'candidate_fits':128,'refit_fits':8,'policy_choices':12,
                'validation_ledgers':84,'outer_ledgers':80,'ledger_replays':164,'prediction_phases':8})
            self.assertLessEqual(gradient,1e-10);self.assertGreater(members,1000);self.assertLess(error,1e-8)
            # The fit's direct acceptance tolerance is not replaced by the
            # broader relative+absolute tolerance for comparing artifact floats.
            fits=audit.json_lines(run/'1440m/fits.jsonl')
            fits[0]['intercept']+=2e-10
            fits[0]['coefficient_sha256']=audit.array_digest(np.array([fits[0]['intercept'],*fits[0]['coefficients']]),'<f8')
            fits[0]['gradient']=[0.]*len(fits[0]['gradient']);fits[0]['max_abs_gradient']=0.
            (run/'1440m/fits.jsonl').write_bytes(b''.join(audit.independent.canonical_json(row) for row in fits))
            with self.assertRaisesRegex(ValueError,'direct gradient exceeds'),contextlib.redirect_stdout(io.StringIO()):
                audit.audit_timeframe(args,protocol,receipt,{'implementation':{'sha256':'e'*64}})


if __name__ == '__main__':
    unittest.main()
