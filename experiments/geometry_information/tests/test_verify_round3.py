"""Independent R3 grammar, exact-tail and complete synthetic artifact replay."""
import contextlib
import copy
from fractions import Fraction
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from experiments.geometry_information import verify_round3 as audit


class RoundThreeVerifierTests(unittest.TestCase):
    def protocol(self):
        path=audit.HERE/'round3_protocol.json'
        return audit.json_file(path)

    def test_unpublished_protocol_remains_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'protocol.json';path.write_text('{}\n')
            with self.assertRaisesRegex(ValueError,'drafts cannot run'):audit.admitted_protocol(path)

    def test_catalogue_exhaustive_raw_ohlc_native_and_producer_parity(self):
        from experiments.geometry_information import interactions
        states=audit.oriented_pair_states();self.assertEqual(len(states),7452)
        payload,encoded,groups=audit.catalogue_oracle()
        self.assertEqual([len(group) for group in groups],[75,150])
        self.assertEqual(encoded,interactions.catalogue_bytes())
        prices=[]
        for current,prior,d0,d1 in states:
            for candle,color in ((prior,d1),(current,d0)):
                low,bottom,top,high=[float(rank+100) for rank in candle]
                opening,closing=(bottom,top) if color>=0 else (top,bottom)
                prices.append([opening,high,low,closing])
        prices=np.asarray(prices);rows=np.arange(1,len(prices),2,dtype=np.int64)
        raw=audit.raw_interaction_indices(prices,rows)
        ranks=np.asarray([[a,b] for a,b,_,_ in states],dtype=np.uint8)
        up=np.asarray([[a>0,b>0] for _,_,a,b in states],dtype=bool)
        np.testing.assert_array_equal(raw,audit.key_interaction_indices(ranks,up))
        np.testing.assert_array_equal(raw,interactions.interaction_indices(ranks,up))
        self.assertEqual(set(raw[:,0]),set(range(75)));self.assertEqual(set(raw[:,1]),set(range(75,225)))
        np.testing.assert_array_equal(audit.raw_features(prices,rows,2,'I'),interactions.features(ranks,up,2,'I'))
        np.testing.assert_array_equal(audit.raw_features(prices,rows,2,'A'),audit.independent.raw_features(prices,rows,2,'G'))
        for n in audit.HISTORIES:
            self.assertEqual(len(audit.feature_names(n,'I')),38*n-34+225)

    def test_catalogue_hash_path_and_retained_record_tampering_rejected(self):
        protocol=self.protocol();audit.catalogue_contract(protocol)
        wrong=copy.deepcopy(protocol);wrong['features']['catalogue']['catalogue_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'pinned catalogue'):audit.catalogue_contract(wrong)
        wrong=copy.deepcopy(protocol);wrong['features']['catalogue']['catalogue_file']='elsewhere.json'
        with self.assertRaisesRegex(ValueError,'pinned catalogue'):audit.catalogue_contract(wrong)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'catalogue.json').write_bytes(audit.catalogue_oracle()[1]+b'\n')
            with self.assertRaisesRegex(ValueError,'run catalogue'):audit.catalogue_contract(protocol,root)

    def test_serialized_native_feature_stage_checks_all_interaction_projections(self):
        from experiments.geometry_information.tests.test_verify_round1 import VerifierTests
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);folder=root/'1m';folder.mkdir()
            source,bounds=VerifierTests().native_fixture(folder)
            protocol=self.protocol();protocol['data'].update(bounds['data'])
            protocol['data']['sources']=[{'minutes':1,'prepared_csv_sha256':source['sha256'],
                'expected_source_rows':40,'missing_grid_bars':0}]
            args=SimpleNamespace(data_dir=root,keys_root=root,run=None)
            with contextlib.redirect_stdout(io.StringIO()):receipt=audit.feature_stage(args,protocol)[0]
            rows=np.arange(9,40,dtype=np.int64)
            self.assertEqual(receipt['records_checked'],31)
            self.assertTrue(receipt['all_interaction_indices_and_columns_checked'])
            self.assertEqual(receipt['interaction_indices'],{'dtype':'<i2','shape':[31,2],
                'sha256':audit.array_digest(audit.raw_interaction_indices(source['prices'],rows),'<i2')})
            for n in audit.HISTORIES:
                for family in audit.FAMILIES:
                    actual=audit.raw_features(source['prices'],rows,n,family)
                    self.assertEqual(receipt['features'][family+str(n)]['sha256'],audit.array_digest(actual))
                    self.assertEqual(receipt['features'][family+str(n)]['shape'],list(actual.shape))

    def test_exact_fraction_metadata_and_tail_bits_match_independent_fraction_sum(self):
        from experiments.geometry_information import exact_bootstrap
        smallest=np.nextafter(0.,1.)
        folds=[{'I_minus_A':np.array([.1,-.1,smallest,0.]),'I_minus_cash':np.array([.2,-.03,0.,-.1])},
               {'I_minus_A':np.array([-.07,0.,.02]),'I_minus_cash':np.array([0.,-.2,.4])}]
        encoded=audit.exact_encoding_oracle(folds)
        hits=audit.exact_tail_oracle(encoded,30,2,37,17)
        rng=np.random.default_rng(17+30000+2);wanted=[]
        for _ in range(37):
            totals=[Fraction(),Fraction()];pooled=[Fraction(),Fraction()]
            for fold in folds:
                size=len(fold['I_minus_A'])
                selected=[]
                for start in rng.integers(0,size,size=math.ceil(size/2),dtype=np.int64):
                    selected.extend([(int(start)+k)%size for k in range(2)])
                for column,name in enumerate(('I_minus_A','I_minus_cash')):
                    values=[Fraction.from_float(float(value)) for value in fold[name]]
                    totals[column]+=sum((values[index] for index in selected[:size]),Fraction())
                    pooled[column]+=sum(values,Fraction())
            wanted.append([totals[column]>=2*pooled[column] for column in range(2)])
        np.testing.assert_array_equal(hits,wanted)
        self.assertEqual(encoded['metadata']['contrasts']['I_minus_A']['denominator_exponent'],1074)
        # Independent conversion agrees with the producer on ordinary finite
        # cases after the explicitly executed binary64 I-minus-A subtraction.
        source=[{'daily_I':np.array([.1,-.2,0.]),'daily_A':np.array([.02,0.,-.01])}]
        direct=[{'I_minus_A':source[0]['daily_I']-source[0]['daily_A'],'I_minus_cash':source[0]['daily_I']}]
        ours=audit.exact_encoding_oracle(direct);theirs=exact_bootstrap.prepare_exact(source)
        self.assertEqual(ours['metadata'],theirs.metadata)
        _,_,_,producer_hits=exact_bootstrap.bootstrap_economics(source,15,2,29,13)
        np.testing.assert_array_equal(audit.exact_tail_oracle(ours,15,2,29,13),producer_hits)

    def test_single_atom_equality_and_zero_have_exact_tail(self):
        folds=[]
        for i,size in enumerate((365,366,365,280)):
            values=np.zeros(size)
            if i==1:values[0]=-.001
            folds.append({'I_minus_A':values,'I_minus_cash':np.zeros(size)})
        encoded=audit.exact_encoding_oracle(folds);hits=audit.exact_tail_oracle(encoded,30,7)
        rng=np.random.default_rng(20261008+30000+7);multiplicities=[]
        for _ in range(2000):
            count=0
            for fold_index,size in enumerate((365,366,365,280)):
                starts=rng.integers(0,size,size=math.ceil(size/7),dtype=np.int64)
                chosen=((starts[:,None]+np.arange(7))%size).ravel()[:size]
                if fold_index==1:count=int(np.sum(chosen==0))
            multiplicities.append(count)
        np.testing.assert_array_equal(hits[:,0],np.asarray(multiplicities)<=2)
        self.assertTrue(hits[:,1].all())
        self.assertTrue(hits[np.asarray(multiplicities)==2,0].all())

    def test_committed_code_and_protocol_path_are_bound(self):
        protocol_path='experiments/geometry_information/round3_protocol.json';code=b'code\n'
        run={'protocol_repository_path':protocol_path,'freeze_commit':'a'*40,
             'implementation':{'git_head':'b'*40,'files':{'producer.py':hashlib.sha256(code).hexdigest()}}}
        with tempfile.TemporaryDirectory() as temporary:
            p=Path(temporary)/'p.json';p.write_bytes(b'{}\n')
            def git(args,**kwargs):
                return SimpleNamespace(stdout=b'' if args[1]=='merge-base' else p.read_bytes() if args[2].endswith(protocol_path) else code)
            with patch.object(audit.subprocess,'run',side_effect=git):audit.committed_implementation(run,p,temporary)
            wrong=copy.deepcopy(run);wrong['protocol_repository_path']='other.json'
            with self.assertRaisesRegex(ValueError,'protocol repository path'):audit.committed_implementation(wrong,p,temporary)
            wrong=copy.deepcopy(run);wrong['implementation']['files']['producer.py']='0'*64
            with patch.object(audit.subprocess,'run',side_effect=git),self.assertRaisesRegex(ValueError,'reported commit'):
                audit.committed_implementation(wrong,p,temporary)
            with patch.object(audit.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['git'])),self.assertRaises(ValueError):
                audit.committed_implementation(run,p,temporary)

    def test_full_compact_synthetic_producer_all_members_and_exact_tail_tampering(self):
        from threadpoolctl import threadpool_limits
        from experiments.geometry_information import common,run_round3
        from experiments.geometry_information.tests.test_round3 import synthetic_source
        run_round3.numerical()
        with tempfile.TemporaryDirectory() as temporary,threadpool_limits(limits=1):
            base=Path(temporary);run=base/'run';data=base/'data';run.mkdir();(data/'1440m').mkdir(parents=True)
            source,keys=synthetic_source();csv=data/'1440m/ohlcv.csv'
            values=np.column_stack((source['timestamps'],source['ohlc'],np.ones(source['rows'])))
            np.savetxt(csv,values,delimiter=',',header='timestamp,open,high,low,close,volume',comments='',fmt=['%d']+['%.17g']*5)
            source['sha256']=audit.digest(csv);protocol=self.protocol()
            protocol['data']['sources']=[{**protocol['data']['sources'][0],'minutes':1440,'prepared_csv_sha256':source['sha256']}]
            protocol['inference']['bootstrap']['replicates']=7
            (run/'protocol.json').write_bytes(audit.independent.canonical_json(protocol));(run/'provenance.json').write_text('{}\n')
            (run/'catalogue.json').write_bytes(audit.catalogue_oracle()[1])
            options={'out':str(run),'data_dir':str(data),'keys_dir':'synthetic-only','protocol_sha256':audit.digest(run/'protocol.json'),
                     'implementation_sha256':'e'*64}
            with patch.object(common,'load_source',return_value=source),patch.object(common,'decode_keys',return_value=keys), \
                    contextlib.redirect_stdout(io.StringIO()):run_round3.timeframe_job(options,1440)
            raw=audit.independent.load_source(csv,86400)
            receipt={'minutes':1440,'keys_file_sha256':keys['keys_sha256'],'features':{}}
            for n in audit.HISTORIES:
                for family in audit.FAMILIES:
                    receipt['features'][family+str(n)]={'sha256':audit.array_digest(audit.raw_features(raw['prices'],keys['indices'],n,family))}
            args=SimpleNamespace(run=run,data_dir=data,protocol=run/'protocol.json');identity={'implementation':{'sha256':'e'*64}}
            exact_checks=[]
            with contextlib.redirect_stdout(io.StringIO()):
                _,coverage,error,gradient,members=audit.audit_timeframe(args,protocol,receipt,identity,exact_checks)
            self.assertEqual(coverage,{'candidate_fits':128,'refit_fits':8,'policy_choices':12,'validation_ledgers':84,
                'outer_ledgers':80,'ledger_replays':164,'prediction_phases':8})
            self.assertEqual(len(exact_checks),6);self.assertGreater(members,1000);self.assertLessEqual(gradient,1e-10)
            path=run/'1440m/bootstrap-exact.json';original=path.read_bytes();bad=audit.json_file(path)
            bad['contrasts']['I_minus_A']['numerators_decimal'][0]='999'
            path.write_bytes(audit.independent.canonical_json(bad))
            with self.assertRaisesRegex(ValueError,'complete exact integer metadata'),contextlib.redirect_stdout(io.StringIO()):
                audit.audit_timeframe(args,protocol,receipt,identity)
            path.write_bytes(original)
            # Re-seal the modified array index in the fixture: rejection must
            # come from independently reconstructed integer tail bits, not just
            # the outer byte-integrity envelope.
            bundle=run/'1440m/bootstrap.npz';index_path=run/'1440m/arrays.json'
            original_bundle,original_index=bundle.read_bytes(),index_path.read_bytes()
            payload=audit.read_npz(bundle);payload['block7__exact_hits'][0,0]^=True
            np.savez_compressed(bundle,**payload)
            index=audit.json_file(index_path);entry=index['files']['bootstrap.npz']
            entry['sha256']=audit.digest(bundle);entry['bytes']=bundle.stat().st_size
            entry['arrays']['block7__exact_hits']['sha256']=audit.array_digest(payload['block7__exact_hits'])
            index_path.write_bytes(audit.independent.canonical_json(index))
            with self.assertRaisesRegex(ValueError,'integer/mask values'),contextlib.redirect_stdout(io.StringIO()):
                audit.audit_timeframe(args,protocol,receipt,identity)
            bundle.write_bytes(original_bundle);index_path.write_bytes(original_index)
            summary_path=run/'1440m/summary.json';original_summary=summary_path.read_bytes()
            bad=audit.json_file(summary_path);record=bad['bootstrap']['7']['comparisons']['I_minus_A']
            record['p_one_sided']=record['p_one_sided']/2 if record['p_one_sided'] else .5
            summary_path.write_bytes(audit.independent.canonical_json(bad))
            with self.assertRaisesRegex(ValueError,'p_one_sided'),contextlib.redirect_stdout(io.StringIO()):
                audit.audit_timeframe(args,protocol,receipt,identity)
            summary_path.write_bytes(original_summary)
            fits=audit.json_lines(run/'1440m/fits.jsonl');fits[0]['intercept']+=2e-10
            fits[0]['coefficient_sha256']=audit.array_digest(np.array([fits[0]['intercept'],*fits[0]['coefficients']]),'<f8')
            fits[0]['gradient']=[0.]*len(fits[0]['gradient']);fits[0]['max_abs_gradient']=0.
            (run/'1440m/fits.jsonl').write_bytes(b''.join(audit.independent.canonical_json(row) for row in fits))
            with self.assertRaisesRegex(ValueError,'direct gradient exceeds'),contextlib.redirect_stdout(io.StringIO()):
                audit.audit_timeframe(args,protocol,receipt,identity)


if __name__=='__main__':unittest.main()
