"""Conversational screen: send, progress, background handoff and safe retries."""
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import membrain_sdk as sdk
from membrain_cli.api import SDKBackend
from membrain_cli.config import local_timezone
from membrain_cli.session import Session
from membrain_cli.stub_api import StubAPI
from membrain_cli.types import ClientError, Context, Job, Result


class RecordingMonitor:
    def __init__(self): self.watched = []
    def start(self): pass
    def stop(self): pass
    def watch(self, job, context): self.watched.append(job)
    def drain(self): return []


def turn(status='processing', progress=(), reply=None, error=None, turn_id=None):
    return {'id': turn_id or TURN, 'job_id': JOB, 'conversation_id': CONVERSATION, 'capture_id': CAPTURE, 'message': 'hi',
            'status': status, 'progress': [{'text': text} for text in progress], 'reply': reply, 'error': error}


TURN, JOB, CONVERSATION, CAPTURE = uuid4(), uuid4(), uuid4(), uuid4()


class ScriptedTurns(StubAPI):
    """Returns the given turn states in order for send/get/retry calls."""
    def __init__(self, *states, fail_sends=0):
        super().__init__()
        self.states, self.fail_sends = list(states), fail_sends

    def call(self, operation, text, context, **kwargs):
        if not operation.startswith('turn.') or operation == 'turn.history':
            return super().call(operation, text, context, **kwargs)
        self.calls.append((operation, text, context))
        if operation == 'turn.send' and self.fail_sends:
            self.fail_sends -= 1
            raise ClientError('Cannot reach the API.')
        state = self.states.pop(0)
        return Result(state['reply'] or '', replace(context, conversation_id=CONVERSATION, capture_id=CAPTURE, turn_id=TURN), payload=state)


class ChatTests(unittest.TestCase):
    def run_chat(self, *inputs, backend=None, sleep=lambda seconds: None):
        values, output = iter(inputs), []
        def read(prompt):
            try: return next(values)
            except StopIteration: raise EOFError from None
        monitor = RecordingMonitor()
        session = Session(backend or StubAPI(), read=read, write=output.append, monitor=monitor, start='chat', sleep=sleep)
        session.run()
        return session, monitor, '\n'.join(output)

    def test_stub_chat_sends_verbatim_text_with_a_request_id(self):
        session, _, output = self.run_chat('  I think binary uses two symbols.  ', '/quit')
        operation, text, context = session.backend.calls[0]
        self.assertEqual((operation, text), ('turn.send', '  I think binary uses two symbols.  '))
        self.assertIsNotNone(context.request_id)
        self.assertIn('Membrain: [Stub]', output)
        self.assertIsNotNone(session.last_context.conversation_id)

    def test_progress_is_shown_once_and_reply_follows(self):
        backend = ScriptedTurns(turn(progress=['Reading your message']),
                                turn(progress=['Reading your message', 'Saving and organising your explanation']),
                                turn('completed', ['Reading your message', 'Saving and organising your explanation'], 'Saved.'))
        _, _, output = self.run_chat('Binary uses two symbols.', '/quit', backend=backend)
        self.assertEqual(output.count('Reading your message'), 1)
        self.assertLess(output.index('Saving and organising'), output.index('Membrain: Saved.'))
        self.assertEqual([call[0] for call in backend.calls], ['turn.send', 'turn.get', 'turn.get'])

    def test_failed_send_keeps_the_same_request_id_for_retry(self):
        backend = ScriptedTurns(turn('completed', reply='Saved.'), fail_sends=1)
        _, _, output = self.run_chat('My explanation', '/retry', '/quit', backend=backend)
        sends = [call for call in backend.calls if call[0] == 'turn.send']
        self.assertEqual(len(sends), 2)
        self.assertEqual(sends[0][2].request_id, sends[1][2].request_id)
        self.assertIn('Message kept', output)

    def test_failed_turn_shows_partial_reply_and_retry_reprocesses_it(self):
        backend = ScriptedTurns(turn('failed', reply='Saved your explanation.', error='The model could not prepare an explanation'),
                                turn('completed', reply='Saved your explanation.\n\nBinary is base two.'))
        _, _, output = self.run_chat('Binary uses two symbols. Explain binary.', '/retry', '/quit', backend=backend)
        self.assertIn("Couldn't finish: The model could not prepare an explanation", output)
        self.assertEqual(backend.calls[-1][0], 'turn.retry')
        self.assertEqual(backend.calls[-1][2].turn_id, TURN)
        self.assertIn('Binary is base two.', output)

    def test_interrupting_a_slow_reply_hands_it_to_the_background_monitor(self):
        def interrupt(seconds): raise KeyboardInterrupt
        backend = ScriptedTurns(turn(progress=['Reading your message']))
        session, monitor, output = self.run_chat('Quiz me', '/quit', backend=backend, sleep=interrupt)
        self.assertIn('the reply will appear here', output)
        self.assertEqual([(job.id, job.kind, job.target) for job in monitor.watched], [(JOB, 'turn', TURN)])
        self.assertIn(JOB, session.known_jobs)

    def test_map_writes_a_local_page_from_map_data(self):
        from pathlib import Path
        with patch('membrain_cli.session.write_map', return_value=Path('/tmp/membrain-map.html')):
            session, _, output = self.run_chat('hello', '/map', '/quit')
        self.assertEqual([call[0] for call in session.backend.calls if call[0] == 'bank.map'], ['bank.map'])
        self.assertIn('Opened /tmp/membrain-map.html', output)

    def test_new_and_menu_switch_without_losing_the_conversation(self):
        session, _, output = self.run_chat('hello', '/menu', '/chat', '/new', '/quit')
        self.assertIn('Back in the conversation', output)
        self.assertIsNone(session.current.context.conversation_id)
        self.assertEqual(session.current.screen, 'chat')


class MapPageTests(unittest.TestCase):
    def test_write_map_inlines_json_and_copies_three(self):
        from membrain_cli.map_page import write_map
        with tempfile.TemporaryDirectory() as raw:
            package = Path(raw) / 'pkg'
            package.mkdir()
            (package / 'three.min.js').write_text('/* three */', encoding='utf-8')
            dest = Path(raw) / 'out'
            opened = []
            class Traversable:
                def joinpath(self, name):
                    return package / Path(name).name
            with patch('membrain_cli.map_page.files', return_value=Traversable()):
                path = write_map({'nodes': [{'id': '1', 'label': 'Binary', 'excerpt': 'Two symbols.'}]},
                                 directory=dest, opener=opened.append)
            page = path.read_text(encoding='utf-8')
            self.assertIn('"label": "Binary"', page)
            self.assertEqual((dest / 'three.min.js').read_text(encoding='utf-8'), '/* three */')
            self.assertTrue(opened[0].startswith('file:'))


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.backend = SDKBackend('http://127.0.0.1:8000')

    def tearDown(self):
        self.backend.close()

    def read(self, status='completed'):
        now = datetime.now(timezone.utc)
        return sdk.TurnRead(id=TURN, conversation_id=CONVERSATION, capture_id=CAPTURE, sequence=1, message='hi', status=status,
                            progress=[], reply='Saved.' if status == 'completed' else None, error=None, job_id=JOB,
                            banked_concept_ids=[], active_question=None, created_at=now, completed_at=now if status == 'completed' else None)

    def test_send_uses_request_id_and_local_timezone(self):
        sent = []
        class Conversation:
            def submit_turn(inner, body, **kwargs):
                sent.append(body)
                return self.read('processing')
        self.backend.conversation = Conversation()
        request = uuid4()
        with patch.dict(os.environ, {'TZ': 'Europe/London'}):
            result = self.backend.call('turn.send', 'hello', Context(request_id=request))
        self.assertEqual((sent[0].client_message_id, sent[0].timezone, sent[0].conversation_id), (request, 'Europe/London', None))
        self.assertEqual((result.context.turn_id, result.payload['status']), (TURN, 'processing'))

    def test_background_poll_maps_turn_status(self):
        class Conversation:
            def get_turn(inner, turn_id, **kwargs): return self.read()
        self.backend.conversation = Conversation()
        status, result = self.backend.poll(Job(JOB, 'turn', TURN), Context())
        self.assertEqual((status, result.message), ('succeeded', 'Saved.'))

    def test_local_timezone_prefers_tz_then_falls_back(self):
        with patch.dict(os.environ, {'TZ': ':Pacific/Auckland'}):
            self.assertEqual(local_timezone(), 'Pacific/Auckland')
        with patch.dict(os.environ, {'TZ': ''}), patch('os.path.realpath', return_value='/nowhere'):
            self.assertEqual(local_timezone(), 'UTC')

    def test_map_uses_the_conversation_subject(self):
        sent, subject = [], uuid4()
        class Captures:
            def conversation_history(inner, conversation_id, **kwargs):
                return sdk.ConversationRead(id=CONVERSATION, title='Computing', subject_id=subject,
                                            captures=[], next_cursor=None)
        class Maps:
            def concept_map(inner, body, **kwargs):
                sent.append(body)
                return sdk.ConceptMapRead(
                    nodes=[sdk.MapNode(id=TURN, label='Binary', excerpt='Two symbols.',
                                       position=sdk.MapPosition(x=0.1, y=0.2, z=0.3))],
                    confirmed_edges=[], proposed_edges=[], similarity_candidates=[],
                    proposals_truncated=False, vector_status='ready',
                    layout=sdk.MapLayout(method='embedding', version=1, meaning='PCA'))
        self.backend.captures, self.backend.maps = Captures(), Maps()
        result = self.backend.call('bank.map', '', Context(conversation_id=CONVERSATION))
        self.assertEqual((sent[0].subject_id, sent[0].layout), (subject, 'embedding'))
        self.assertEqual(result.payload['nodes'][0]['label'], 'Binary')
