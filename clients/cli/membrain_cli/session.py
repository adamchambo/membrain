"""Terminal state machine with typed results and queued background notifications."""
from __future__ import annotations
from dataclasses import dataclass, field, replace
import time
from uuid import UUID, uuid4
from .jobs import Monitor
from .menus import MENUS
from . import terminal
from .output import show
from .types import Backend, ClientError, Context, Item, Job, Result

# Seconds between reply checks, and how long to wait before suggesting the worker may be down.
POLL_INTERVAL = 0.5
SLOW_REPLY = 30


@dataclass
class Frame:
    screen: str
    context: Context = field(default_factory=Context)
    operation: str = ''
    prompt: str = ''
    after: str = ''
    items: tuple[Item, ...] = ()
    cursor: str | None = None
    list_operation: str = ''
    list_text: str = ''
    draft: str = ''


class Session:
    def __init__(self, backend: Backend, read=input, write=print, store=None,
                 api_url='', setup=None, context: Context | None = None, monitor=None,
                 start='main', sleep=time.sleep):
        """Inject backend, terminal read/write, optional state store, setup callback, monitor,
        first screen ('main' menus or 'chat') and sleep used while waiting for replies."""
        self.backend, self.read, self.write = backend, read, write
        self.store, self.api_url, self.setup = store, api_url, setup
        self.sleep = sleep
        self.last_context = context or Context()
        self.stack = [Frame(start, self.last_context)]
        self.running = True
        self.monitor = monitor or Monitor(backend)
        self.known_jobs = dict(getattr(backend, 'tracked', {}))
        for job in self.known_jobs.values():
            self.monitor.watch(job, self.last_context)

    @property
    def current(self):
        return self.stack[-1]

    def push(self, screen, context=None, **kwargs):
        self.stack.append(Frame(screen, context or self.current.context, **kwargs))

    def ask(self, operation, prompt, after='', context=None):
        self.push('input', context, operation=operation, prompt=prompt, after=after)

    def main_menu(self):
        self.stack = [Frame('main', self.last_context)]

    def remember(self):
        if self.store:
            try:
                self.store.save(self.api_url, self.last_context, list(self.known_jobs.values())[-100:])
            except OSError:
                self.write('Server operation succeeded, but local resume IDs could not be saved.')

    def invoke(self, operation, text='', context=None, cursor=None, selection=False):
        try:
            result = self.backend.call(operation, text, context or self.current.context, cursor=cursor)
        except ClientError as error:
            self.write(str(error))
            return None
        except (ValueError, TypeError):
            self.write('Invalid input. Choose a displayed item or supply a valid UUID/value.')
            return None
        self.current.context = result.context
        show(replace(result, items=()) if selection and terminal.interactive(self.read, self.write) else result, self.write)
        if result.job:
            self.known_jobs[result.job.id] = result.job
            self.monitor.watch(result.job, result.context)
        # A diagnostic answer can enqueue both capture and learning work.
        for identifier, job in getattr(self.backend, 'tracked', {}).items():
            if identifier not in self.known_jobs:
                self.monitor.watch(job, result.context)
            self.known_jobs[identifier] = job
        if result.context.conversation_id:
            self.last_context = replace(self.last_context, conversation_id=result.context.conversation_id,
                                        capture_id=result.context.capture_id)
        self.remember()
        return result

    def notifications(self):
        for job, result in self.monitor.drain():
            self.known_jobs[job.id] = job
            if hasattr(self.backend, 'tracked'):
                self.backend.tracked[job.id] = job
            self.remember()
            self.write('\nBackground result:')
            show(result, self.write)
            for frame in self.stack:
                identifier = frame.context.artifact_id if job.kind == 'learning' else frame.context.attempt_id if job.kind == 'review_feedback' else frame.context.capture_id
                if identifier == job.target:
                    frame.context = replace(frame.context, artifact_id=result.context.artifact_id,
                                            suggestion_id=result.context.suggestion_id) if job.kind == 'learning' else frame.context

    def run(self):
        self.write('LOCAL STUB MODE — no server or persistent changes.' if self.backend.is_stub else f'Membrain — local API: {self.api_url}')
        if self.current.screen == 'chat':
            self.write('Talk to Membrain in your own words: explain what you learned, ask for a reminder, a quiz or your gaps.')
            self.write('Commands: /new, /menu, /history, /undo, /retry, /help, /quit.')
            self.resume_chat()
        else:
            self.write('Commands: /help, /back, /menu, /chat, /quit, /jobs, /setup. Capture: /show, /undo, /history. /retry resends retained input.')
        self.monitor.start()
        try:
            while self.running:
                self.notifications()
                self.render()
                try:
                    if self.current.screen not in ('input', 'chat') and terminal.interactive(self.read, self.write):
                        frame = self.current
                        menu = MENUS[frame.screen]
                        title = menu.title + (f' — {frame.context.label}' if frame.context.label else '')
                        choices = [(str(i), label) for i, (label, _) in enumerate(menu.choices, 1)]
                        choices.append(('x', 'Exit') if frame.screen == 'main' else ('0', 'Back'))
                        value = terminal.select(title, choices, self.read, self.write, tick=self.notifications)
                    elif self.current.operation == 'selection' and terminal.interactive(self.read, self.write):
                        choices = [(str(i), item.title + (f' — {item.detail}' if item.detail else ''))
                                   for i, item in enumerate(self.current.items, 1)]
                        if self.current.cursor:
                            choices.append(('/more', 'More results'))
                        choices.append(('/back', 'Back'))
                        value = terminal.select('Select a result', choices, self.read, self.write, tick=self.notifications)
                    else:
                        prompt = {'input': '> ', 'chat': '\nYou: '}.get(self.current.screen, 'Choose: ')
                        value = terminal.read_text(prompt, self.read, self.write, tick=self.notifications)
                except (EOFError, KeyboardInterrupt):
                    break
                self.handle(value)
        finally:
            self.monitor.stop()
            self.remember()
            self.write('Exiting. Saved jobs remain on the server; processing requires a running worker. Local draft text is discarded.')

    def render(self):
        frame = self.current
        if frame.screen == 'chat':
            return
        if frame.screen == 'input':
            self.write('\n' + frame.prompt)
            return
        if terminal.interactive(self.read, self.write):
            return
        menu = MENUS[frame.screen]
        self.write('\n' + menu.title + (f' — {frame.context.label}' if frame.context.label else ''))
        for number, (label, _) in enumerate(menu.choices, 1):
            self.write(f'{number}. {label}')
        self.write('x. Exit' if frame.screen == 'main' else '0. Back')

    def handle(self, value):
        command = value.strip()
        if command in ('/help', 'help', '--help', '-h', '?') and (command.startswith('/') or self.current.screen != 'input'):
            self.help()
            return
        if command == '/quit' or (command.lower() == 'x' and self.current.screen == 'main'):
            self.running = False
            return
        if command == '/menu':
            self.main_menu()
            return
        if command == '/chat':
            self.open_chat()
            return
        if command == '/new':
            self.last_context = replace(self.last_context, conversation_id=None, capture_id=None)
            self.stack = [Frame('chat', Context())]
            self.write('Started a new conversation.')
            return
        if self.current.screen == 'chat' and command in ('/retry', '/history'):
            self.retry_turn() if command == '/retry' else self.show_turns(10)
            return
        if command == '/back' or (command == '0' and self.current.screen not in ('input', 'main')):
            if len(self.stack) > 1:
                self.stack.pop()
            return
        if command == '/setup':
            if self.setup:
                self.setup()
            else:
                self.write('Setup is available in live mode: membrain setup.')
            return
        if command == '/jobs':
            self.push('status')
            return
        if command == '/retry' and self.current.draft:
            self.submit(self.current.draft)
            return
        if command in ('/show', '/undo', '/history'):
            operation = {'/show': 'capture.inspect', '/undo': 'capture.undo', '/history': 'chat.history'}[command]
            result = self.invoke(operation)
            if result and command == '/history':
                self.current.cursor, self.current.list_operation = result.cursor, 'chat.history'
            return
        if command == '/more':
            frame = self.current
            if not frame.cursor or not frame.list_operation:
                self.write('No further page is available.')
                return
            result = self.invoke(frame.list_operation, frame.list_text, cursor=frame.cursor, selection=True)
            if result:
                frame.items, frame.cursor = result.items, result.cursor
            return
        if command.startswith('/'):
            self.write('Unknown command. Use /help to list commands.')
            return
        if not command and self.current.operation not in ('reflect.since', 'reflect.until'):
            self.write('Please enter a value.')
            return
        if self.current.screen == 'chat':
            self.converse(value)
            return
        if self.current.screen == 'input':
            self.submit(value)
            return
        choices = MENUS[self.current.screen].choices
        if not command.isascii() or not command.isdecimal() or not 1 <= int(command) <= len(choices):
            self.write('Choose one of the displayed numbers.')
            return
        target = choices[int(command) - 1][1]
        if target.startswith('@'):
            self.action(target[1:])
        elif target == 'formats' and not self.has_scope():
            self.choose('scope.concepts', 'review.scope')
        else:
            self.push(target)

    def help(self):
        """Display terminal commands without changing the current screen or draft."""
        self.write('Help — use ↑/↓ and Enter, type a displayed number, or use these commands:')
        for line in (
            '/help (or help, --help, -h, ? in menus) — show this help',
            '/chat — talk to Membrain (the conversation continues where you left it)',
            '/new — start a new conversation',
            '/setup — configure chat, embeddings and database settings',
            '/back — return to the previous screen',
            '/menu — return to the main menu',
            '/quit — exit the client; saved jobs remain on the server (x at the main menu)',
            '/jobs — inspect processing status',
            '/show — inspect the latest capture',
            '/undo — retract derived changes from the latest capture',
            '/history — show the current conversation history',
            '/more — show the next page of results',
            '/retry — resend input retained after a failed request, or reprocess a failed chat message',
            'Ctrl-C while Membrain is replying — keep chatting; the reply appears when ready',
            'From your shell: membrain setup opens configuration; membrain --help lists startup options.',
        ):
            self.write(line)

    def open_chat(self):
        self.stack = [Frame('chat', replace(Context(), conversation_id=self.last_context.conversation_id,
                                            capture_id=self.last_context.capture_id))]
        self.write('Back in the conversation.' if self.last_context.conversation_id else 'Talk to Membrain in your own words.')

    def resume_chat(self):
        """Show the end of the remembered conversation so a pending question has its context."""
        if not self.current.context.conversation_id:
            return
        self.write('Continuing your last conversation (/new starts a fresh one).')
        self.show_turns(2)

    def show_turns(self, count):
        context = self.current.context
        if not context.conversation_id:
            self.write('No conversation yet.')
            return
        try:
            turns = self.backend.call('turn.history', str(count), context).payload
        except ClientError as error:
            self.write(str(error))
            return
        for turn in turns:
            self.write(f"\nYou: {turn['message']}")
            if turn['status'] == 'processing':
                self.write('Membrain: (still working on this)')
                self.watch_turn(turn, context)
            else:
                self.write('Membrain: ' + (turn.get('reply') or turn.get('error') or ''))

    def converse(self, value):
        """Send value as a turn, keeping a stable request ID so /retry cannot duplicate it."""
        frame = self.current
        if frame.context.request_id is None or frame.draft != value:
            frame.context = replace(frame.context, request_id=uuid4())
        frame.draft = value
        try:
            result = self.backend.call('turn.send', value, frame.context)
        except ClientError as error:
            self.write(str(error))
            self.write('Message kept. Use /retry to send it again.')
            return
        frame.draft = ''
        frame.context = replace(result.context, request_id=None)
        self.last_context = replace(self.last_context, conversation_id=result.context.conversation_id,
                                    capture_id=result.context.capture_id)
        self.remember()
        self.wait(result)

    def retry_turn(self):
        frame = self.current
        if frame.draft:
            self.converse(frame.draft)
            return
        if not frame.context.turn_id:
            self.write('Nothing to retry.')
            return
        try:
            result = self.backend.call('turn.retry', '', frame.context)
        except ClientError as error:
            self.write(str(error))
            return
        self.wait(result)

    def wait(self, result):
        """Show progress until the reply is ready; Ctrl-C hands the turn to the background monitor."""
        turn, shown, waited, hinted = result.payload, 0, 0.0, False
        try:
            while True:
                progress = turn.get('progress') or []
                for step in progress[shown:]:
                    self.write(f"  … {step['text']}")
                shown = len(progress)
                if turn['status'] != 'processing':
                    break
                if waited >= SLOW_REPLY and not hinted:
                    hinted = True
                    self.write('  Still working. If nothing changes, check the worker is running (./start status). '
                               'Press Ctrl-C to keep chatting meanwhile.')
                self.sleep(POLL_INTERVAL)
                waited += POLL_INTERVAL
                result = self.backend.call('turn.get', '', result.context)
                turn = result.payload
        except KeyboardInterrupt:
            self.watch_turn(turn, result.context)
            self.write('\nStill working on that; the reply will appear here when it is ready.')
            return
        except ClientError as error:
            self.watch_turn(turn, result.context)
            self.write(f'{error} Your message is saved; the reply will appear once the server is reachable.')
            return
        self.current.context = result.context
        if turn['status'] == 'failed':
            if turn.get('reply'):
                self.write('\nMembrain: ' + turn['reply'])
            self.write(f"Couldn't finish: {turn.get('error') or 'processing stopped'}. Use /retry to try again.")
            return
        self.write('\nMembrain: ' + (turn.get('reply') or ''))

    def watch_turn(self, turn, context):
        if turn.get('job_id'):
            job = Job(turn['job_id'], 'turn', turn['id'], 'running')
            self.known_jobs[job.id] = job
            self.monitor.watch(job, context)

    def has_scope(self):
        context = self.current.context
        return bool(context.concept_id or context.subject_id or context.concept_ids)

    def choose(self, operation, after, text=''):
        result = self.invoke(operation, text, selection=True)
        if result is None:
            return
        if not result.items and not result.cursor and not operation.startswith('jobs.list.'):
            self.write('No matching items. Use /back or choose another activity.')
            return
        kinds = {'bank.resources': 'resource', 'bank.subjects': 'subject', 'scope.subjects': 'subject', 'chat.recent': 'conversation', 'suggestion.list': 'suggestion', 'review.history': 'review_session'}
        kind = 'job' if operation.startswith('jobs.list.') else kinds.get(operation, 'concept')
        context = replace(result.context, item_kind=kind)
        self.push('input', context, operation='selection', prompt='Choose a result number or enter its UUID; /more for the next page.',
                  after=after, items=result.items, cursor=result.cursor, list_operation=operation, list_text=text)

    def select(self, text):
        frame = self.current
        if text.strip().isascii() and text.strip().isdecimal():
            index = int(text.strip()) - 1
            if not 0 <= index < len(frame.items):
                self.write('Choose a displayed result number.')
                return
            item = frame.items[index]
        else:
            try:
                identifier = UUID(text.strip())
            except ValueError:
                self.write('Choose a result number or UUID.')
                return
            item = next((row for row in frame.items if row.id == identifier),
                        Item(identifier, frame.context.item_kind, str(identifier)))
        context = replace(frame.context, item_kind=item.kind, label=item.title)
        operation = 'chat.select' if item.kind == 'conversation' else 'jobs.select' if item.kind == 'job' else 'review.resume' if item.kind == 'review_session' else 'suggestion.select' if item.kind == 'suggestion' else 'capture.reply' if item.kind == 'proposal' else 'bank.select'
        result = self.invoke(operation, str(item.id), context)
        if not result:
            return
        frame.context = result.context
        destination = frame.after
        self.stack.pop()
        if item.kind == 'conversation' or item.kind == 'proposal':
            self.ask('capture.message', 'Continue the conversation:', context=result.context)
            self.current.cursor = result.cursor
            self.current.list_operation = 'chat.history'
        elif item.kind == 'review_session':
            self.ask('review.answer', result.prompt, 'review_next', context=result.context)
        elif item.kind == 'job':
            self.push('job', result.context)
        elif item.kind == 'capture':
            self.push('capture_item', result.context)
        elif destination == 'review.scope':
            self.push('scope', result.context)
        elif destination == 'gap.scope':
            self.push('gap_scope', result.context)
        elif destination == 'diagnostic':
            self.push('gap_candidate', result.context)
            self.diagnostic()
        elif destination == 'reflect.subject':
            self.push('reflection', result.context)
            self.invoke('reflect.run')
        elif destination == 'reflect.both':
            self.ask('reflect.since', 'From ISO timestamp with timezone (blank: beginning):', context=result.context)
        elif destination == 'subject.add':
            added = self.invoke('subject.add_member', context=result.context)
            if added:
                self.push('subject', added.context)
        elif destination == 'revision_history':
            self.push('concept', result.context)
            self.invoke('bank.history')
        elif destination == 'ask.clarify':
            self.ask('clarify.start', 'What would you like to clarify?', context=result.context)
        elif item.kind == 'subject':
            self.push('subject', result.context)
        elif item.kind == 'resource':
            self.push('resource', result.context)
        else:
            self.push(destination or 'concept', result.context)

    def submit(self, value):
        frame = self.current
        old_draft = frame.draft
        frame.draft = value
        if frame.operation == 'selection':
            self.select(value)
            return
        if frame.operation == 'bank.search':
            self.choose('bank.search', 'concept', value)
            frame.draft = ''
            return
        if frame.operation in ('reflect.since', 'reflect.until'):
            name = frame.operation.split('.')[1]
            context = replace(frame.context, **{name: value.strip()})
            if name == 'since':
                self.ask('reflect.until', 'Until ISO timestamp with timezone (blank: now):', context=context)
            else:
                result = self.invoke('reflect.run', context=context)
                if result:
                    self.push('reflection', result.context)
            return
        if frame.operation in ('capture.message', 'gap.answer', 'clarify.explain') and (frame.context.request_id is None or old_draft != value):
            frame.context = replace(frame.context, request_id=uuid4())
        result = self.invoke(frame.operation, value)
        if result is None:
            self.write('Input retained in memory. Use /retry to try again, or enter a replacement.')
            return
        frame.draft = ''
        if frame.operation == 'capture.message':
            frame.context = result.context
            return
        next_screen = frame.after or ('review_next' if frame.operation == 'review.answer' else 'gap_next' if frame.operation in ('gap.answer', 'gap.familiar') else 'clarify_next')
        self.stack.pop()
        self.push(next_screen, result.context)

    def diagnostic(self):
        if not self.current.context.diagnostic_question:
            if not self.current.context.artifact_id:
                result = self.invoke('gap.start')
                if result:
                    self.push('gap_candidate', result.context)
                return
            self.choose('suggestion.list', 'diagnostic')
            return
        result = self.invoke('gap.start')
        if result and result.prompt:
            self.ask('gap.answer', result.prompt, 'gap_next', context=result.context)

    def review_question(self, mode=None):
        context = self.current.context
        if mode and mode != context.mode:
            context = replace(context, mode=mode, review_session_id=None, question_id=None)
        started = self.invoke('review.begin', context=context)
        if not started:
            return
        result = self.invoke('review.next', context=started.context)
        if result and result.prompt:
            self.ask('review.answer', result.prompt, 'review_next', context=result.context)

    def action(self, operation):
        if operation in ('setup', 'help', 'chat'):
            self.handle('/' + operation)
        elif operation == 'capture.new':
            self.ask('capture.message', 'What did you learn? Enter an explanation, uncertainty, question or resource.', context=Context())
        elif operation in ('chat.recent', 'chat.find'):
            # Both can page through all conversations; no silent first-page-only search.
            self.choose('chat.recent', 'capture_input')
        elif operation == 'subject.create':
            self.ask('subject.create', 'Subject name:', after='subject')
        elif operation == 'subject.add':
            self.current.context = replace(self.current.context, membership_subject_id=self.current.context.subject_id)
            self.choose('scope.concepts', 'subject.add')
        elif operation.startswith('search.'):
            self.last_context = replace(self.last_context, search_mode=operation.split('.')[1])
            self.current.context = replace(self.current.context, search_mode=operation.split('.')[1])
            self.write('Search mode updated.')
            self.stack.pop()
            self.current.context = replace(self.current.context, search_mode=operation.split('.')[1])
        elif operation == 'bank.history' and not self.current.context.concept_id:
            self.choose('bank.reflection_changes' if self.current.screen == 'reflection' else 'bank.concepts', 'revision_history')
        elif operation == 'bank.search':
            self.ask('bank.search', 'Search your bank:')
        elif operation in ('bank.concepts', 'bank.archived', 'bank.subjects', 'bank.resources', 'bank.recents', 'bank.timeline', 'bank.related', 'bank.subject_members'):
            self.choose(operation, 'concept')
        elif operation == 'bank.select':
            self.choose('bank.concepts', 'concept')
        elif operation in ('clarify.choose', 'clarify.start'):
            if operation == 'clarify.choose':
                self.choose('scope.concepts', 'ask.clarify')
            else:
                self.ask('clarify.start', 'What would you like to clarify?')
        elif operation == 'clarify.unresolved':
            self.choose(operation, 'capture_input')
        elif operation == 'clarify.explain':
            self.ask(operation, 'Explain your updated understanding in your own words:')
        elif operation == 'review.history':
            self.choose('review.history', 'review_next')
        elif operation == 'review.subject':
            self.choose('scope.subjects', 'review.scope')
        elif operation == 'review.concept':
            self.choose('scope.concepts', 'review.scope')
        elif operation == 'review.suggest':
            result = self.invoke(operation)
            if result:
                self.push('scope', result.context)
        elif operation in ('review.cue', 'review.teach', 'review.steps', 'review.apply', 'review.mixed'):
            self.review_question({'review.cue': 'cue_card', 'review.teach': 'teach_back', 'review.steps': 'fill_gap', 'review.apply': 'applied', 'review.mixed': 'quiz'}[operation])
        elif operation == 'review.next':
            self.review_question()
        elif operation == 'review.finish':
            if self.invoke(operation):
                self.main_menu()
        elif operation == 'gap.choose':
            self.push('gap_kind')
        elif operation in ('gap.concept', 'gap.subject'):
            self.choose('scope.subjects' if operation.endswith('subject') else 'scope.concepts', 'gap.scope')
        elif operation in ('gap.suggest', 'gap.surprise'):
            result = self.invoke(operation)
            if result:
                self.push('gap_candidate', result.context)
        elif operation == 'gap.start':
            self.diagnostic()
        elif operation == 'gap.familiar':
            self.ask(operation, "Explain what is familiar, or enter 'skip' without claiming assessed mastery:", 'gap_next')
        elif operation in ('artifact.inspect', 'suggestion.list'):
            self.choose('suggestion.list', 'suggestion')
        elif operation in ('suggestion.adopt', 'suggestion.dismiss'):
            self.ask(operation, 'Describe your decision (recorded with this suggestion):', 'gap_next')
        elif operation.startswith('learn.'):
            self.invoke(operation)
        elif operation == 'reflect.subject':
            self.choose('scope.subjects', 'reflect.subject')
        elif operation == 'reflect.both':
            self.choose('scope.subjects', 'reflect.both')
        elif operation == 'reflect.period':
            self.ask('reflect.since', 'From ISO timestamp with timezone (blank: beginning):', context=replace(self.current.context, subject_id=None))
        elif operation.startswith('jobs.list.'):
            self.choose(operation, 'job')
        elif operation in ('bank.attach', 'bank.edit'):
            self.ask(operation, 'Resource URL or locator:' if operation == 'bank.attach' else 'Your revised explanation:', 'concept')
        else:
            result = self.invoke(operation)
            if result and result.prompt:
                self.write(result.prompt)
