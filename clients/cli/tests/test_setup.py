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
        answers=iter(['2','http://localhost:11434/v1/chat/completions','model','1'])
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
