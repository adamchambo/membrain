"""The clarify/save loop and search fallback use the real command handlers."""
from dataclasses import replace
from types import SimpleNamespace as NS
from uuid import uuid4
import unittest
from unittest.mock import patch
from membrain_cli.api import SDKBackend
from membrain_cli.types import Context,ClientError
from membrain_cli.session import Session
from membrain_cli.stub_api import StubAPI
from test_session import QuietMonitor

class WorkflowTests(unittest.TestCase):
    def test_save_new_understanding_uses_capture_and_keeps_request_id(self):
        backend=SDKBackend('http://local');context=Context(artifact_id=uuid4(),request_id=uuid4())
        receipt=NS(conversation_id=uuid4(),capture_id=uuid4(),processing_job_id=uuid4())
        with patch.object(backend,'execute',return_value=receipt) as execute:
            result=backend.call('clarify.explain','I think binary uses two digits.',context)
            submitted=execute.call_args.args[1]
            self.assertEqual(submitted.raw_text,'I think binary uses two digits.')
            self.assertEqual(submitted.request_id,context.request_id)
            self.assertEqual(result.job.kind,'capture')
        backend.close()

    def test_followup_request_names_its_parent_artifact(self):
        backend=SDKBackend('http://local');context=Context(artifact_id=uuid4())
        with patch.object(backend,'execute',return_value=NS(artifact_id=uuid4(),job_id=uuid4())) as execute:
            backend.task('clarification','Explain more simply',context)
            self.assertEqual(execute.call_args.args[1].parent_artifact_id,context.artifact_id)
        backend.close()

    def test_hybrid_search_falls_back_when_embedding_endpoint_is_unavailable(self):
        backend=SDKBackend('http://local')
        with patch.object(backend,'readiness',return_value=NS(settings=NS(embeddings=NS(configured=True)))),patch.object(backend,'execute',side_effect=[ClientError('model unavailable'),NS(items=[])]) as execute:
            result=backend.call('bank.search','binary',Context())
            self.assertEqual(execute.call_args_list[0].kwargs['mode'],'hybrid')
            self.assertEqual(execute.call_args_list[1].kwargs['mode'],'text')
            self.assertIn('exact text',result.message)
        backend.close()

    def test_restore_uses_the_selected_record(self):
        backend=SDKBackend('http://local');identifier=uuid4()
        with patch.object(backend,'execute') as execute:
            backend.call('bank.restore','',Context(concept_id=identifier))
            self.assertEqual(execute.call_args.args[1],identifier)
            self.assertFalse(execute.call_args.args[2].archived)
        backend.close()

    def test_reflection_history_prompts_for_a_concept(self):
        session=Session(StubAPI(),write=lambda _:None,monitor=QuietMonitor())
        session.push('reflection')
        with patch.object(session,'choose') as choose:
            session.action('bank.history')
            choose.assert_called_once_with('bank.reflection_changes','revision_history')
