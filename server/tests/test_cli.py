"""Generated SDK → FastAPI → disposable database and worker journeys."""
import asyncio
import json
import io
from dataclasses import replace
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from unittest.mock import patch
import unittest
from urllib3.response import HTTPResponse
from oracle_sdk.rest import RESTResponse

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'clients/cli'))
from oracle_cli.api import SDKBackend
from oracle_cli.types import Context, ClientError
from oracle_cli.session import Session as TerminalSession
from oracle_cli.config import Store
from app.jobs.worker import run_one
from app.knowledge.models import Concept, ExplanationRevision
from app.config import read_config
import test_ingestion as support


class CLIJourneys(unittest.TestCase):
    setUpClass=classmethod(support.IngestionTests.setUpClass.__func__)
    tearDownClass=classmethod(support.IngestionTests.tearDownClass.__func__)
    api=support.IngestionTests.api
    save=support.IngestionTests.save
    process=support.IngestionTests.process
    rows=support.IngestionTests.rows

    def setUp(self):
        support.IngestionTests.setUp(self)
        self.backend=SDKBackend('http://local.test')
        self.requests=[]
        def request(method,url,**kwargs):
            self.requests.append((method,url))
            parsed=urlsplit(url)
            status,body=asyncio.run(support.asgi_call(method,parsed.path+('?' + parsed.query if parsed.query else ''),kwargs.get('body')))
            return RESTResponse(HTTPResponse(body=io.BytesIO(json.dumps(body,default=str).encode() if body is not None else b''),status=status,headers={'Content-Type':'application/json'},preload_content=False))
        self.backend.client.rest_client.request=request
    def tearDown(self):
        self.backend.close()
        support.IngestionTests.tearDown(self)

    def captured(self):
        result=self.backend.call('capture.message','Binary uses two symbols.',Context(request_id=uuid4()))
        receipt={'capture_id':str(result.context.capture_id),'processing_job_id':str(result.job.id)}
        self.process(receipt,support.output(support.understanding('Binary','Binary uses two symbols.')))
        return result

    def test_capture_processing_search_review_and_feedback(self):
        captured=self.captured()
        status,organized=self.backend.poll(captured.job,captured.context)
        self.assertEqual(status,'succeeded')
        self.assertTrue(organized.payload['concept_ids'])
        found=self.backend.call('bank.search','binary',captured.context)
        selected=self.backend.call('bank.select',str(found.items[0].id),replace(captured.context,item_kind='concept'))
        context=replace(selected.context,mode='teach_back')
        started=self.backend.call('review.begin','',context)
        question=self.backend.call('review.next','',started.context)
        self.assertTrue(question.prompt)
        attempt=self.backend.call('review.answer','Two symbols represent digits.',question.context)
        run_one(self.engine,job_id=attempt.job.id,assessor=lambda snapshot,prompt,response:{'recall':'consistent','feedback':'Matches recorded explanation.','correctness':'not_verified'})
        status,feedback=self.backend.poll(attempt.job,attempt.context)
        self.assertEqual(feedback.payload['feedback']['correctness'],'not_verified')
        self.backend.call('review.finish','',attempt.context)
        self.assertEqual(len(self.rows(ExplanationRevision)),1)

    def test_real_menu_saves_to_server_and_resumes_ids(self):
        from tempfile import TemporaryDirectory
        class Monitor:
            def start(self):pass
            def stop(self):pass
            def watch(self,*args):pass
            def drain(self):return []
        with TemporaryDirectory() as directory:
            store=Store(Path(directory)/'cli.json');entries=iter(['1','1','My original explanation','/menu','0']);output=[]
            terminal=TerminalSession(self.backend,read=lambda _:next(entries),write=output.append,store=store,api_url=self.backend.url,monitor=Monitor())
            terminal.run()
            restored=store.resume(self.backend.url)
            self.assertIsNotNone(restored.conversation_id)
            record=self.api('GET',f'/captures/{restored.capture_id}')
            self.assertEqual(record['raw_text'],'My original explanation')

    def test_possible_gap_diagnostic_and_lesson_remain_separate(self):
        captured=self.captured();concept=self.rows(Concept)[0]
        context=Context().scope(concept=concept.id,label=concept.title)
        queued=self.backend.call('gap.suggest','',context)
        output={'content':'A possible missing connection.','verification':'not_verified','uncertainty':['No external source checked'],
                'suggestions':[{'kind':'gap','concept_id':str(concept.id),'rationale':'Intermediate step is not recorded.','evidence':'unrecorded','diagnostic_question':'How do bits become interpreted values?'}]}
        with patch('app.learning.service.get_chat_client',return_value=support.ScriptedClient(output)):
            run_one(self.engine,job_id=queued.job.id)
        status,artifact=self.backend.poll(queued.job,queued.context)
        selected=self.backend.call('suggestion.select',str(artifact.items[0].id),artifact.context)
        question=self.backend.call('gap.start','',selected.context)
        self.assertIn('interpreted',question.prompt)
        answer=self.backend.call('gap.answer','The program interprets the bits.',selected.context)
        self.assertIsNotNone(answer.context.capture_id)
        self.assertIsNotNone(answer.context.artifact_id)
        lesson=self.backend.call('learn.lesson','',selected.context)
        with patch('app.learning.service.get_chat_client',return_value=support.ScriptedClient({'content':'An illustrative lesson.','verification':'not_verified'})):
            run_one(self.engine,job_id=lesson.job.id)
        status,learned=self.backend.poll(lesson.job,lesson.context)
        self.assertEqual(status,'succeeded')
        self.assertEqual(len(self.rows(ExplanationRevision)),1)
        self.backend.call('suggestion.dismiss','I will revisit this later.',selected.context)

    def test_partial_setup_preserves_other_capability_and_explicit_null_disables(self):
        config={'chat':{'url':'http://localhost/chat','model':'original-chat','api_key':'chat-secret'},
                'embeddings':{'url':'http://localhost/embeddings','model':'vectors','api_key':'vector-secret','profile':{'model':'vectors','revision':'v1','dimensions':3}}}
        self.api('PUT','/setup',config)
        self.api('PUT','/setup',{'chat':{'url':'http://localhost/chat','model':'new-chat','api_key':'new-secret'}})
        saved=read_config()['settings']
        self.assertEqual(saved['ORACLE_CHAT_MODEL'],'new-chat')
        self.assertEqual(saved['ORACLE_EMBEDDING_API_KEY'],'vector-secret')
        self.assertEqual(saved['ORACLE_EMBEDDING_MODEL'],'vectors')
        self.api('PUT','/setup',{'chat':None})
        self.assertEqual(read_config()['settings']['ORACLE_EMBEDDING_API_KEY'],'vector-secret')
        self.assertEqual(read_config()['settings']['ORACLE_CHAT_API_KEY'],'')

    def test_subject_resource_pagination_and_reflection(self):
        self.captured();concept=self.rows(Concept)[0]
        subject=self.api('POST','/subjects',{'title':'Computing'},201)
        self.api('PUT',f'/subjects/{subject["id"]}/concepts/{concept.id}')
        context=Context(item_kind='subject')
        scoped=self.backend.call('bank.select',subject['id'],context)
        members=self.backend.call('bank.subject_members','',scoped.context)
        self.assertEqual(members.items[0].id,concept.id)
        self.backend.call('reflect.run','',scoped.context)
        self.backend.call('bank.attach','https://example.com/article',Context(concept_id=concept.id))
        resources=self.backend.call('bank.resources','',Context())
        opened=self.backend.call('bank.select',str(resources.items[0].id),Context(item_kind='resource'))
        self.backend.call('bank.read','',opened.context)
        for index in range(26): self.save(f'Topic {index}')
        page=self.backend.call('chat.recent','',Context())
        self.assertTrue(page.cursor)
        next_page=self.backend.call('chat.recent','',Context(),cursor=page.cursor)
        self.assertFalse({row.id for row in page.items} & {row.id for row in next_page.items})

    def test_sdk_over_real_loopback_http(self):
        import socket
        import threading
        import time
        import uvicorn
        from app.main import app
        sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(10)
        server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,ws='none'))
        thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True)
        thread.start()
        live=None
        try:
            for _ in range(100):
                if server.started:break
                time.sleep(0.01)
            self.assertTrue(server.started)
            live=SDKBackend(f'http://127.0.0.1:{sock.getsockname()[1]}')
            result=live.call('capture.message','An actual loopback HTTP capture.',Context(request_id=uuid4()))
            record=self.api('GET',f'/captures/{result.context.capture_id}')
            self.assertEqual(record['raw_text'],'An actual loopback HTTP capture.')
            live.call('capture.undo','',result.context)
        finally:
            if live:live.close()
            server.should_exit=True
            thread.join(timeout=5)
            sock.close()

    def test_new_question_needs_no_existing_concept_and_does_not_bank_generated_text(self):
        result=self.backend.call('clarify.start','What does a CPU do?',Context())
        with patch('app.learning.service.get_chat_client',return_value=support.ScriptedClient({'content':'An illustrative answer.','verification':'not_verified'})):
            run_one(self.engine,job_id=result.job.id)
        status,answer=self.backend.poll(result.job,result.context)
        self.assertEqual(status,'succeeded')
        self.assertEqual(answer.payload['inputs']['concept_ids'],[])
        self.assertEqual(len(self.rows(Concept)),0)
        self.assertEqual(len(self.rows(ExplanationRevision)),0)
        self.backend.call('learn.diagram','',answer.context)
        self.api('POST','/learning-tasks',{'kind':'suggestions','concept_ids':[]},expected=422)

    def test_resume_unfinished_review_returns_pending_question_without_snapshot(self):
        self.captured();concept=self.rows(Concept)[0]
        started=self.backend.call('review.begin','',Context().scope(concept=concept.id))
        question=self.backend.call('review.next','',started.context)
        history=self.backend.call('review.history','',Context())
        self.assertEqual(history.items[0].id,started.context.review_session_id)
        resumed=self.backend.call('review.resume',str(history.items[0].id),Context())
        self.assertEqual(resumed.context.question_id,question.context.question_id)
        self.assertIsNone(resumed.payload)
        self.assertEqual(resumed.prompt,question.prompt)
