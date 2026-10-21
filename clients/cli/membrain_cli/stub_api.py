"""Explicit, local-only navigation fixtures; never used by the live adapter."""
from dataclasses import replace
from uuid import UUID
from .types import Context, Item, Job, Result

DEMO = UUID('00000000-0000-0000-0000-000000000001')
CONVERSATION = UUID('00000000-0000-0000-0000-000000000002')


class StubAPI:
    is_stub = True

    def __init__(self):
        self.calls = []
        self.tracked = {}
        self.answers = 0

    def close(self):
        pass

    def call(self, operation, text, context, *, cursor=None):
        self.calls.append((operation, text, context))
        if operation.startswith('turn.'):
            if operation == 'turn.history':
                return Result('', context, payload=[])
            message = text if operation == 'turn.send' else '(stub message)'
            turn = {'id': DEMO, 'job_id': DEMO, 'conversation_id': context.conversation_id or CONVERSATION, 'capture_id': DEMO,
                    'message': message, 'status': 'completed', 'progress': [{'text': 'Reading your message'}],
                    'reply': '[Stub] Message received in memory only; no interpretation, saving or assessment happened.',
                    'error': None}
            return Result(turn['reply'], replace(context, conversation_id=turn['conversation_id'], capture_id=DEMO, turn_id=DEMO),
                          payload=turn)
        if operation == 'capture.message':
            return Result('[Stub] Message received in memory only.', replace(context, conversation_id=context.conversation_id or CONVERSATION,
                          capture_id=DEMO, request_id=None))
        if operation in ('bank.concepts', 'scope.concepts', 'bank.search', 'bank.recents', 'bank.timeline', 'bank.related'):
            return Result('[Stub] Navigation example; no personal evidence inspected.', context, (Item(DEMO, 'concept', 'Binary'),))
        if operation in ('bank.subjects', 'scope.subjects'):
            return Result('[Stub] Subjects.', context, (Item(DEMO, 'subject', 'Computing'),))
        if operation == 'bank.resources':
            return Result('[Stub] Resources.', context, (Item(DEMO, 'resource', 'Demo source'),))
        if operation == 'bank.select':
            return Result('[Stub] Selected.', context.scope(subject=UUID(text), label=context.label) if context.item_kind == 'subject' else context.scope(concept=UUID(text), label=context.label))
        if operation.startswith('chat.'):
            if operation == 'chat.select':
                return Result('[Stub] Conversation history.', replace(context, conversation_id=UUID(text)))
            return Result('[Stub] Conversations.', context, (Item(CONVERSATION, 'conversation', 'Demo conversation'),))
        if operation == 'review.suggest':
            return Result('[Stub] Suggested scope; no assessment.', context.scope(concept=DEMO, label='Binary'))
        if operation == 'review.begin':
            return Result('[Stub] Review started.', replace(context, review_session_id=DEMO))
        if operation in ('review.question', 'review.next'):
            return Result('[Stub] Recall question.', replace(context, question_id=DEMO), prompt='[Stub question] Explain the selected topic in your own words.')
        if operation == 'review.answer':
            self.answers += 1
            return Result('[Stub] Answer received. No assessment was performed.', replace(context, attempt_id=DEMO))
        if operation == 'review.finish':
            return Result(f'[Stub] {self.answers} review answer(s); coverage unavailable.', context)
        if operation in ('gap.suggest', 'gap.surprise'):
            return Result('[Stub] Fixed demo candidate; no personal evidence was inspected.', replace(context.scope(concept=DEMO, label='Demo scope'), artifact_id=DEMO))
        if operation in ('suggestion.list', 'artifact.inspect'):
            return Result('[Stub] Possible gap, unassessed.', replace(context, artifact_id=DEMO), (Item(DEMO, 'suggestion', 'Demo possible gap'),))
        if operation == 'suggestion.select':
            return Result('[Stub] Gap suggestion.', replace(context, suggestion_id=DEMO, diagnostic_question='[Stub diagnostic] Which step are you uncertain about?'))
        if operation == 'gap.start':
            return Result('[Stub] Unassessed.', context, prompt=context.diagnostic_question or '[Stub diagnostic] Explain the topic.')
        if operation == 'gap.answer':
            return Result('[Stub] Diagnostic answer received. No gap established.', context)
        if operation.startswith('jobs.list.'):
            return Result('[Stub] Example job.', context, (Item(DEMO, 'job', 'Demo job'),))
        if operation == 'jobs.select':
            return Result('[Stub] Job selected.', replace(context, job_id=UUID(text)))
        return Result(f'[Stub] {operation}; no server request or persistent change.', context)

    def poll(self, job, context):
        return 'succeeded', Result('[Stub] Completed.', context)
