"""H6 operator gate checks without keys, encoder, real tasks or network."""
from pathlib import Path
from unittest.mock import patch
import unittest
from study_preparation.final_technical_resume_operator import Session
from study_preparation.final_technical_resume_operator import DeferredHeaderTransport
from study_preparation.final_operator import Session as OriginalSession
from tests.test_technical_retry import trial_directory
from tests.test_rate_limit import Clock,request
from tests.study_fixture import FakeTransport
from communication_pruning.technical_retry import TechnicalAdapter
from communication_pruning.openrouter import encoded
from io import BytesIO
from urllib.error import HTTPError
from decimal import Decimal
import importlib.util
from types import SimpleNamespace
from unittest.mock import Mock


class TechnicalOperatorTests(unittest.TestCase):
    def test_old_and_new_backup_markers_block_dispatch_before_execution(self):
        source=Path(__file__).resolve().parents[1]/'runs/Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/activation/technical_operation.py'
        spec=importlib.util.spec_from_file_location('technical_operation_under_test',source)
        operation=importlib.util.module_from_spec(spec);spec.loader.exec_module(operation)
        with trial_directory() as root:
            session=SimpleNamespace(folder=root/'live',control=root/'control',binding={},candidate={},plan={},create_execution=Mock())
            with patch.object(operation,'ORIGINAL',root/'old'),patch.object(operation,'RUN',root/'new'), \
                 patch.object(operation,'own'),patch.object(operation,'checked'), \
                 patch.object(operation,'read',return_value={'candidate':{},'binding':{}}), \
                 patch.object(operation,'_api',return_value=(None,None,None,None)), \
                 patch.object(operation,'_session',return_value=session):
                for name in ('old','new'):
                    marker=root/name/'operation/BACKUP-CLEANUP-BLOCK.json';marker.parent.mkdir(parents=True)
                    marker.write_text('{}')
                    with self.assertRaises(ValueError):operation.dispatch('create',{}, {})
                    session.create_execution.assert_not_called();marker.unlink()
                    marker.symlink_to(root/'absent')
                    with self.assertRaises(ValueError):operation.dispatch('create',{}, {})
                    session.create_execution.assert_not_called();marker.unlink()
                operation.dispatch('create',{}, {})
                session.create_execution.assert_called_once()

    def test_noncanonical_path_rejected_before_initialization(self):
        with self.assertRaises(Exception):Session('relative.json','relative-binding.json')

    def test_metadata_failure_precedes_model_initialization(self):
        session=Session.__new__(Session)
        session.encoder=None;session._last_checkpoint=None;session.last_resource_evidence=None
        session.binding={'sha256':'a'*64};session.operation=Path('/nonexistent');session._ready=True
        with patch.object(session,'metadata_gate',side_effect=RuntimeError('metadata mismatch')) as metadata, \
             patch.object(session,'initialize') as initialize, \
             patch.object(session,'_save_resource_record',return_value={'artificial':True}):
            with self.assertRaises(RuntimeError):session.run(9244,coverage={})
            metadata.assert_called_once();initialize.assert_not_called()

    def test_inherited_transport_passes_http_retry_after_to_real_adapter(self):
        with trial_directory() as root:
            clock=Clock();fake=FakeTransport();calls=[]
            class Reply:
                status=200;headers={}
                def __init__(self,raw):self.raw=raw
                def read(self,n):return self.raw[:n]
                def __enter__(self):return self
                def __exit__(self,*args):pass
            class Opener:
                def open(self,req,timeout):
                    calls.append((req.data,timeout))
                    if len(calls)==1:
                        raise HTTPError(req.full_url,503,'invented',{'Retry-After':'180'},BytesIO(encoded({'error':{'code':503}})))
                    return Reply(fake('chat/completions',req.data)[1])
            session=Session.__new__(Session);session._ready=True;session.candidate={}
            session.settings={'credential_file':'/not-read'};session.client=DeferredHeaderTransport(session)
            self.assertIs(Session.transport,OriginalSession.transport)
            with patch('study_preparation.final_technical_resume_operator.load_key',return_value='invented-test-key'), \
                 patch('urllib.request.build_opener',return_value=Opener()), \
                 patch('study_preparation.final_operator.gate.runtime_guard'):
                a=TechnicalAdapter(root/'calls',session.transport,binding='a'*64,cap='2',max_calls=10,clock=clock,sleep=clock.sleep)
                a(request())
            self.assertEqual(sum(clock.waits),180);self.assertEqual(calls[0],calls[1]);self.assertEqual(calls[0][1],45)
            self.assertEqual(a.held,Decimal('.14'))


if __name__=='__main__':unittest.main()
