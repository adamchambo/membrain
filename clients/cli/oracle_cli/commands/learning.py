"""Domain command handlers using the adapter's generated SDK clients."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime
import random
from uuid import UUID
import oracle_sdk as sdk
from ..types import ClientError, Context, Item, Job, Result


from . import data, required


class LearningCommands:
    def _learning(self, operation, text, context):
        if operation == 'clarify.start':
            return self.task('clarification', text, context)
        if operation == 'clarify.explain':
            if not context.concept_id:
                raise ClientError('Choose one concept before saving a revised explanation.')
            self.execute(self.knowledge.add_revision, context.concept_id, sdk.RevisionCreate(explanation_text=text))
            return Result('Saved your updated understanding as a new revision.', context)
        if operation == 'clarify.unresolved':
            if context.capture_id:
                page = self.execute(self.captures.list_proposals, context.capture_id, kind='clarification')
                rows = [Item(row.id, 'proposal', row.payload.get('question', 'Clarification')) for row in page.items if row.status == 'pending']
                return Result('Pending clarification questions for this capture:', context, tuple(rows))
            raise ClientError('Open a capture first to revisit its pending questions, or choose a concept and ask a question.')
        if operation in ('gap.suggest', 'gap.surprise'):
            if not (context.subject_id or context.concept_id or context.concept_ids):
                page = self.concepts()
                if not page.items:
                    raise ClientError('Capture an explanation first, then investigate a possible gap.')
                row = random.choice(page.items) if operation == 'gap.surprise' else page.items[0]
                context = context.scope(concept=row.id, label=row.title)
            reason = 'Random scope sampled from the newest 100 concepts.' if operation == 'gap.surprise' else 'Selected recorded scope; suggestions are hypotheses, not established deficits.'
            result = self.task('suggestions', 'Suggest possible gaps with reasons and short diagnostic questions. Do not diagnose missing knowledge from absent records.', context)
            return replace(result, message=reason + '\n' + result.message)
        if operation == 'artifact.inspect' or operation == 'suggestion.list':
            artifact = self.execute(self.learning.artifact_detail, required(context.artifact_id, 'a learning result'))
            ids = tuple(UUID(value) for value in artifact.inputs.get('concept_ids', []))
            context = replace(context, subject_id=None, concept_ids=ids, concept_id=ids[0] if len(ids) == 1 else None, question=artifact.inputs.get('question', ''))
            rows = tuple(Item(row.id, 'suggestion', row.payload.rationale, f'{row.payload.kind}; {row.payload.evidence}; {row.status}') for row in artifact.suggestions if row.status == 'pending')
            return Result('Generated result, sources, uncertainty and suggestions:', context, rows, payload=data(artifact))
        if operation == 'suggestion.select':
            artifact = self.execute(self.learning.artifact_detail, required(context.artifact_id, 'a learning result'))
            selected = next((row for row in artifact.suggestions if str(row.id) == text), None)
            if selected is None:
                raise ClientError('Choose a suggestion from the current learning result.')
            context = replace(context, subject_id=None, concept_id=selected.payload.concept_id,
                              concept_ids=(selected.payload.concept_id,), suggestion_id=selected.id,
                              diagnostic_question=selected.payload.diagnostic_question or '')
            return Result('Possible gap or change; inspect its evidence before deciding.', context, payload=data(selected))
        if operation == 'gap.start':
            if not context.diagnostic_question:
                return self.task('suggestions', 'Propose a possible gap and a short diagnostic question. Missing records do not establish a deficit.', context)
            return Result('Diagnostic question; this possible gap is still unassessed.', context, prompt=context.diagnostic_question)
        if operation == 'gap.answer':
            # Persist the user's answer immediately; analysis remains a separate artifact.
            capture = self._capture('capture.message', 'Diagnostic question: ' + context.diagnostic_question + '\nMy answer: ' + text, context, None)
            context = capture.context
            result = self.task('clarification', f'Diagnostic question: {context.diagnostic_question}\nUser answer: {text}\nDiscuss the evidence and uncertainty. Do not infer mastery or an established deficit without evidence.', context)
            return replace(result, message='Saved your diagnostic answer as a capture. ' + result.message)
        if operation == 'gap.familiar':
            if text.strip().lower() != 'skip':
                return self._learning('clarify.explain', text, context)
            if context.suggestion_id:
                self.execute(self.learning.decide_suggestion, context.suggestion_id,
                             sdk.Decision(action='dismiss', message='User marked familiar without providing an explanation; no assessed mastery inferred.'))
            return Result('Marked familiar for this suggestion; no assessment or learned status inferred.', context)
        if operation in ('suggestion.adopt', 'suggestion.dismiss'):
            result = self.execute(self.learning.decide_suggestion, required(context.suggestion_id, 'a suggestion'),
                                  sdk.Decision(action='adopt' if operation.endswith('adopt') else 'dismiss', message=text))
            return Result('Recorded your explicit decision.', replace(context, suggestion_id=None), payload=data(result))
        if operation.startswith('learn.'):
            kind = {'learn.lesson': 'lesson', 'learn.familiar': 'clarification', 'learn.example': 'worked_example', 'learn.diagram': 'diagram'}[operation]
            question = text or context.question or 'Build on familiar recorded concepts and show sources or uncertainty.'
            if not (context.concept_id or context.concept_ids or context.subject_id or context.question or text):
                raise ClientError('Enter a question or choose recorded concepts first.')
            return self.task(kind, question, context)
        raise ClientError('Unknown learning action.')
