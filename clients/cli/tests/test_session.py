"""Navigation, state and feedback behavior without a live terminal or server."""
import unittest
from dataclasses import replace
from uuid import uuid4
from oracle_cli.session import Session
from oracle_cli.stub_api import StubAPI, DEMO
from oracle_cli.types import ClientError, Context, Job, Result
from oracle_cli.jobs import Monitor


class QuietMonitor:
    def start(self): pass
    def stop(self): pass
    def watch(self, job, context): pass
    def drain(self): return []


class SessionTests(unittest.TestCase):
    def run_session(self, *inputs, backend=None):
        values = iter(inputs)
        output = []
        backend = backend or StubAPI()
        def read(prompt):
            try: return next(values)
            except StopIteration: raise EOFError from None
        session = Session(backend, read=read, write=output.append, monitor=QuietMonitor())
        session.run()
        return session, backend, '\n'.join(output)

    def test_invalid_input_back_and_eof(self):
        _, _, output = self.run_session('/back', '999', '', 'x')
        self.assertIn('Choose one of the displayed numbers', output)
        self.assertIn('Please enter a value', output)
        self.assertIn('Exiting', output)
        self.run_session()

    def test_main_menu_exit_uses_x_and_zero_does_not_exit(self):
        session = Session(StubAPI(), write=lambda text: None, monitor=QuietMonitor())
        session.handle('0')
        self.assertTrue(session.running)
        session.handle('1')
        session.handle('0')
        self.assertEqual(session.current.screen, 'main')
        session.handle('x')
        self.assertFalse(session.running)
        _, _, output = self.run_session('x')
        self.assertIn('x. Exit', output)
        self.assertNotIn('0. Exit', output)

    def test_capture_retains_typed_ids_and_raw_text(self):
        session, backend, _ = self.run_session('1', '1', '  My explanation  ', '/show', '/undo', '/menu', 'x')
        self.assertEqual([call[0] for call in backend.calls], ['capture.message', 'capture.inspect', 'capture.undo'])
        self.assertEqual(backend.calls[0][1], '  My explanation  ')
        self.assertEqual(backend.calls[1][2].capture_id, DEMO)
        self.assertIsNotNone(session.last_context.conversation_id)

    def test_retry_preserves_request_id(self):
        class FailOnce(StubAPI):
            def __init__(self): super().__init__(); self.requests=[]
            def call(self, operation, text, context, **kwargs):
                if operation == 'capture.message':
                    self.requests.append(context.request_id)
                    if len(self.requests) == 1: raise ClientError('Temporary failure')
                return super().call(operation,text,context,**kwargs)
        backend=FailOnce()
        _, _, output=self.run_session('1','1','Original words','/retry','/quit',backend=backend)
        self.assertEqual(len(backend.requests),2)
        self.assertEqual(backend.requests[0],backend.requests[1])
        self.assertIn('Input retained',output)

    def test_review_keeps_question_scope_and_answers_before_feedback(self):
        _, backend, output = self.run_session('4','2','1','1','2','My answer','1','Second answer','4','0')
        answers=[call for call in backend.calls if call[0]=='review.answer']
        self.assertEqual(len(answers),2)
        self.assertEqual(answers[0][2].concept_id,DEMO)
        self.assertEqual(answers[1][2].mode,'teach_back')
        self.assertLess(output.index('[Stub question]'),output.index('Answer received'))

    def test_gap_requires_selecting_a_suggestion_and_shows_no_deficit(self):
        _, backend, output=self.run_session('5','3','2','1','My answer','/quit')
        self.assertIn('No gap established', output)
        answer=next(call for call in backend.calls if call[0]=='gap.answer')
        self.assertEqual(answer[2].suggestion_id,DEMO)
        self.assertTrue(answer[2].diagnostic_question)

    def test_back_restores_prior_scope(self):
        session, _, _=self.run_session('5','1','1','1','2','/back')
        self.assertEqual(session.current.screen,'gap_scope')
        self.assertEqual(session.current.context.concept_id,DEMO)

    def test_scope_change_clears_question_and_suggestion_ids(self):
        context=Context(concept_id=uuid4(),review_session_id=uuid4(),question_id=uuid4(),suggestion_id=uuid4())
        selected=context.scope(subject=DEMO,label='Computing')
        self.assertIsNone(selected.concept_id)
        self.assertIsNone(selected.question_id)
        self.assertIsNone(selected.suggestion_id)

    def test_job_polling_does_not_print_until_drain(self):
        backend=StubAPI(); monitor=Monitor(backend)
        job=Job(uuid4(),'capture',DEMO)
        monitor.watch(job,Context(capture_id=DEMO))
        monitor.tick()
        self.assertEqual(len(monitor.drain()),1)
        self.assertEqual(monitor.drain(),[])
        self.assertFalse(monitor.pending)

    def test_polling_survives_network_loss_without_spamming(self):
        class Offline(StubAPI):
            def poll(self,job,context): raise ClientError('offline')
        monitor=Monitor(Offline());monitor.watch(Job(uuid4(),'capture',DEMO),Context())
        monitor.tick();monitor.tick()
        self.assertEqual(len(monitor.drain()),1)
        self.assertEqual(len(monitor.pending),1)

    def test_completed_jobs_do_not_replay_after_restart(self):
        monitor=Monitor(StubAPI())
        completed=Job(uuid4(),'capture',DEMO,status='succeeded')
        monitor.watch(completed,Context())
        self.assertFalse(monitor.pending)
        self.assertFalse(monitor.drain())
