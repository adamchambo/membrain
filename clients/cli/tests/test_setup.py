"""Wizard prompts, retained provider settings and client-state boundaries."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from uuid import uuid4
from oracle_cli.config import Store, server_url
from oracle_cli.types import ClientError, Context, Job
from oracle_cli.wizard.flow import run


class SetupTests(unittest.TestCase):
    def test_state_is_per_server_and_contains_ids_only(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';store=Store(path)
            context=Context(conversation_id=uuid4(),capture_id=uuid4(),diagnostic_question='do not persist question')
            store.save('http://127.0.0.1:8000',context,[Job(uuid4(),'capture',context.capture_id)])
            restored=Store(path)
            self.assertEqual(restored.resume('http://127.0.0.1:8000').conversation_id,context.conversation_id)
            self.assertIsNone(restored.resume('http://127.0.0.1:9000').conversation_id)
            self.assertNotIn('do not persist',path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
    def test_server_url_rejects_embedded_keys(self):
        for url in ['http://user:secret@localhost','http://localhost?key=secret','file:///tmp/api']:
            with self.assertRaises(ClientError): server_url(url)
    def test_wizard_only_submits_changed_capability_and_never_echoes_key(self):
        class Fake:
            def __init__(self): self.saved=[];self.setup=NS(save_setup=lambda configuration: self.saved.append(configuration))
            def readiness(self):
                return NS(database=NS(ready=True),worker=NS(ready=True),settings=NS(chat=NS(configured=False),embeddings=NS(configured=True),environment_overrides=[]))
            def execute(self,fn,*args,**kwargs): return fn(*args)
        backend=Fake();output=[]
        answers=iter(['2','2','1','model','1'])
        run(backend,read=lambda prompt:next(answers),write=output.append,secret=lambda prompt:'provider-secret')
        self.assertEqual(backend.saved[0].model_fields_set,{'chat'})
        self.assertNotIn('provider-secret','\n'.join(output))
    def test_cancelled_wizard_does_not_submit_unfinished_settings(self):
        class Fake:
            setup=NS(save_setup=lambda _: None)
            def execute(self, *args, **kwargs): raise AssertionError('No write expected')
            def readiness(self): return NS(database=NS(ready=True),worker=NS(ready=True),settings=NS(chat=NS(configured=False),embeddings=NS(configured=False)))
        inputs=iter(['2'])
        def read(prompt):
            try:return next(inputs)
            except StopIteration:raise EOFError
        self.assertTrue(run(Fake(),read=read,write=lambda _:None))

    def test_local_provider_defaults_and_no_key_prompt(self):
        from oracle_cli.wizard import models
        for runtime, port in [('1', '11434'), ('2', '1234')]:
            answers = iter(['1', runtime, '', 'installed-model'])
            def no_secret(prompt): raise AssertionError('Local model needs no key')
            result = models.chat(lambda prompt: next(answers), no_secret)
            self.assertEqual(result.url, f'http://localhost:{port}/v1/chat/completions')
            self.assertIsNone(result.api_key)

    def test_custom_endpoint_and_cloud_provider(self):
        from oracle_cli.wizard import models
        answers = iter(['3', 'http://localhost:9000/v1/chat/completions', 'model'])
        result = models.chat(lambda prompt: next(answers), lambda prompt: '')
        self.assertEqual(result.url, 'http://localhost:9000/v1/chat/completions')
        answers = iter(['2', '2', 'https://provider.example/v1/chat/completions', 'remote-model'])
        result = models.chat(lambda prompt: next(answers), lambda prompt: 'secret')
        self.assertEqual(result.url, 'https://provider.example/v1/chat/completions')
        self.assertEqual(result.api_key.get_secret_value(), 'secret')

    def test_embedding_provider_preserves_profile(self):
        from oracle_cli.wizard import models
        answers = iter(['1', '1', '', 'nomic-embed-text', 'revision-1', '768', 'y'])
        result = models.embeddings(lambda prompt: next(answers), lambda prompt: self.fail('No key needed'))
        self.assertEqual(result.url, 'http://localhost:11434/v1/embeddings')
        self.assertEqual(result.profile.dimensions, 768)
        self.assertEqual(result.profile.document_prefix, 'search_document: ')

    def test_back_from_provider_does_not_save(self):
        from oracle_cli.wizard import models
        answers = iter(['1', '0'])
        with self.assertRaises(models.Cancelled):
            models.chat(lambda prompt: next(answers), lambda prompt: '')
