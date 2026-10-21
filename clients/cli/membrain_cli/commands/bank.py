"""Domain command handlers using the adapter's generated SDK clients."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime
import random
from uuid import UUID
import membrain_sdk as sdk
from ..types import ClientError, Context, Item, Job, Result


from . import data, required


class BankCommands:
    def _bank(self, operation, text, context, cursor):
        if operation == 'bank.search':
            result = self.execute(self.discovery.search, q=text, mode='text', limit=100)
            return Result('Search results:', context, tuple(Item(row.id, row.type, row.title, row.match_reason) for row in result.items))
        if operation in ('bank.concepts', 'scope.concepts'):
            page = self.concepts(cursor)
            return Result('Saved concepts:', context, tuple(Item(row.id, 'concept', row.title) for row in page.items), cursor=page.next_cursor)
        if operation in ('bank.subjects', 'scope.subjects'):
            page = self.execute(self.subjects.list_subjects, limit=500)
            return Result('Subjects (first 500):', context, tuple(Item(row.id, 'subject', row.title) for row in page.items))
        if operation == 'bank.subject_members':
            ids = self.scope_ids(context, maximum=2000)
            rows = [self.execute(self.knowledge.get_concept, identifier) for identifier in ids[:100]]
            return Result('Subject concepts (first 100; review can use the full supported scope):', context, tuple(Item(row.id, 'concept', row.title) for row in rows))
        if operation == 'bank.resources':
            page = self.execute(self.management.list_resources, cursor=cursor, limit=25)
            return Result('Resources:', context, tuple(Item(row.id, 'resource', row.title or row.uri) for row in page.items), cursor=page.next_cursor)
        if operation in ('bank.recents', 'bank.timeline'):
            function = self.discovery.recents if operation.endswith('recents') else self.discovery.timeline
            page = self.execute(function, cursor=cursor, limit=25)
            rows = []
            for row in page.items:
                if row.concept_id:
                    rows.append(Item(row.concept_id, 'concept', f'{row.type} at {row.occurred_at}'))
                elif row.type == 'resource':
                    rows.append(Item(row.id, 'resource', f'Resource at {row.occurred_at}'))
                elif row.type == 'capture':
                    rows.append(Item(row.id, 'capture', f'Capture at {row.occurred_at}'))
            return Result('Learning activity:', context, tuple(rows), payload=data(page), cursor=page.next_cursor)
        if operation == 'bank.select':
            identifier = UUID(text)
            if context.item_kind == 'subject':
                scope = self.execute(self.subjects.subject_scope, identifier)
                return Result(f'Scope contains {len(scope.concept_ids)} concepts.', context.scope(subject=identifier, label=context.label), payload=data(scope))
            if context.item_kind == 'resource':
                row = self.execute(self.knowledge.get_resource, identifier)
                selected = replace(context.scope(), resource_id=row.id, item_kind='resource', label=row.title or row.uri)
            elif context.item_kind == 'capture':
                row = self.execute(self.captures.get_capture, identifier)
                selected = replace(context, capture_id=row.id, conversation_id=row.conversation_id, label='Capture')
            else:
                row = self.execute(self.knowledge.get_concept, identifier)
                selected = context.scope(concept=row.id, label=row.title)
            return Result('Selected item:', selected, payload=data(row))
        if operation == 'bank.read':
            if context.item_kind == 'resource':
                row = self.execute(self.knowledge.get_resource, required(context.resource_id, 'a resource'))
            else:
                row = self.execute(self.knowledge.get_concept, required(context.concept_id, 'a concept'))
            payload = data(row)
            if context.item_kind == 'resource':
                payload['stored_content'] = data(self.execute(self.sources.source_chunks, context.resource_id))
            return Result('Saved record:', context, payload=payload)
        if operation == 'bank.history':
            page = self.execute(self.knowledge.list_revisions, required(context.concept_id, 'a concept'), cursor=cursor)
            return Result('Your explanation history:', context, payload=data(page), cursor=page.next_cursor)
        if operation == 'bank.related':
            result = self.execute(self.discovery.related, required(context.concept_id, 'a concept'))
            rows = [Item(row.target_concept_id if row.source_concept_id == context.concept_id else row.source_concept_id,
                         'concept', row.relation_type, 'User-confirmed relationship') for row in result.confirmed]
            rows += [Item(row.id, 'concept', row.title, 'Semantic candidate; relationship unconfirmed') for row in result.semantic_candidates]
            return Result('Confirmed links and separate semantic candidates:', context, tuple(rows), payload=data(result))
        if operation == 'bank.edit':
            self.execute(self.knowledge.add_revision, required(context.concept_id, 'a concept'), sdk.RevisionCreate(explanation_text=text))
            return Result('Saved a new revision of your explanation.', context)
        if operation == 'bank.attach':
            resource = self.execute(self.knowledge.create_resource, sdk.ResourceCreate(kind='other', uri=text))
            self.execute(self.knowledge.attach_resource, required(context.concept_id, 'a concept'), sdk.ResourceLink(resource_id=resource.id))
            return Result('Resource attached; saving a resource does not mark it learned.', context)
        if operation == 'bank.archive':
            if context.item_kind == 'resource':
                self.execute(self.management.patch_resource, required(context.resource_id, 'a resource'), sdk.ResourcePatch(archived=True))
            else:
                self.execute(self.management.patch_concept, required(context.concept_id, 'a concept'), sdk.ConceptPatch(archived=True))
            return Result('Archived the item; history remains.', context)
        raise ClientError('Unknown bank action.')
