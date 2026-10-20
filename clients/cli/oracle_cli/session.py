"""Terminal state machine with typed results and queued background notifications."""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from uuid import UUID, uuid4
from .jobs import Monitor
from .menus import MENUS
from .output import show
from .types import Backend, ClientError, Context, Item, Result


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
                 api_url='', setup=None, context: Context | None = None, monitor=None):
        """Inject backend, terminal read/write, optional state store, setup callback and monitor."""
        self.backend, self.read, self.write = backend, read, write
        self.store, self.api_url, self.setup = store, api_url, setup
        self.last_context = context or Context()
        self.stack = [Frame('main', self.last_context)]
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

    def invoke(self, operation, text='', context=None, cursor=None):
        try:
            result = self.backend.call(operation, text, context or self.current.context, cursor=cursor)
        except ClientError as error:
            self.write(str(error))
            return None
        except (ValueError, TypeError):
            self.write('Invalid input. Choose a displayed item or supply a valid UUID/value.')
            return None
        self.current.context = result.context
        show(result, self.write)
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
        self.write('LOCAL STUB MODE — no server or persistent changes.' if self.backend.is_stub else f'Oracle — local API: {self.api_url}')
        self.write('Commands: /back, /menu, /quit, /jobs, /setup. Capture: /show, /undo, /history. /retry resends retained input.')
        self.monitor.start()
        try:
            while self.running:
                self.notifications()
                self.render()
                try:
                    value = self.read('> ' if self.current.screen == 'input' else 'Choose: ')
                except (EOFError, KeyboardInterrupt):
                    break
                self.handle(value)
        finally:
            self.monitor.stop()
            self.remember()
            self.write('Exiting. Server jobs continue; local draft text is discarded.')

    def render(self):
        frame = self.current
        if frame.screen == 'input':
            self.write('\n' + frame.prompt)
            return
        menu = MENUS[frame.screen]
        self.write('\n' + menu.title + (f' — {frame.context.label}' if frame.context.label else ''))
        for number, (label, _) in enumerate(menu.choices, 1):
            self.write(f'{number}. {label}')
        self.write('0. ' + ('Exit' if frame.screen == 'main' else 'Back'))

    def handle(self, value):
        command = value.strip()
        if command == '/quit':
            self.running = False
            return
        if command == '/menu':
            self.main_menu()
            return
        if command == '/back' or (command == '0' and self.current.screen != 'input'):
            if len(self.stack) > 1:
                self.stack.pop()
            elif command == '0':
                self.running = False
            return
        if command == '/setup':
            if self.setup:
                self.setup()
            else:
                self.write('Setup is available in live mode: oracle setup.')
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
            result = self.invoke(frame.list_operation, frame.list_text, cursor=frame.cursor)
            if result:
                frame.items, frame.cursor = result.items, result.cursor
            return
        if command.startswith('/'):
            self.write('Unknown command. Use /back, /menu, /quit, /jobs or /setup.')
            return
        if not command and self.current.operation not in ('reflect.since', 'reflect.until'):
            self.write('Please enter a value.')
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

    def has_scope(self):
        context = self.current.context
        return bool(context.concept_id or context.subject_id or context.concept_ids)

    def choose(self, operation, after, text=''):
        result = self.invoke(operation, text)
        if result is None:
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
        if frame.operation in ('capture.message', 'gap.answer') and (frame.context.request_id is None or old_draft != value):
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
        if operation == 'capture.new':
            self.ask('capture.message', 'What did you learn? Enter an explanation, uncertainty, question or resource.', context=Context())
        elif operation in ('chat.recent', 'chat.find'):
            # Both can page through all conversations; no silent first-page-only search.
            self.choose('chat.recent', 'capture_input')
        elif operation == 'bank.search':
            self.ask('bank.search', 'Search your bank:')
        elif operation in ('bank.concepts', 'bank.subjects', 'bank.resources', 'bank.recents', 'bank.timeline', 'bank.related', 'bank.subject_members'):
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
