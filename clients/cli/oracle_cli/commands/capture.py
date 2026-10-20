"""Domain command handlers using the adapter's generated SDK clients."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime
import random
from uuid import UUID
import oracle_sdk as sdk
from ..types import ClientError, Context, Item, Job, Result


from . import data, required


class CaptureCommands:
    def _capture(self, operation, text, context, cursor):
        if operation == 'capture.message':
            receipt = self.execute(self.captures.ingest_capture, sdk.QuickCapture(
                raw_text=text, conversation_id=context.conversation_id,
                reply_to_proposal_id=context.proposal_id, request_id=context.request_id))
            context = replace(context, conversation_id=receipt.conversation_id, capture_id=receipt.capture_id,
                              proposal_id=None, request_id=None)
            return self.queue('Saved your message.', context, Job(receipt.processing_job_id, 'capture', receipt.capture_id))
        if operation == 'capture.inspect':
            capture = self.execute(self.captures.get_capture, required(context.capture_id, 'a capture'))
            return Result('Saved capture and processing proposals:', context, payload=data(capture))
        if operation == 'capture.undo':
            self.execute(self.captures.undo_capture, required(context.capture_id, 'a capture'))
            return Result('Retracted derived understanding; original capture remains.', context)
        if operation == 'capture.reply':
            return Result('Reply will be linked to that clarification.', replace(context, proposal_id=UUID(text)))
        if operation in ('chat.recent', 'chat.find'):
            page = self.execute(self.management.list_conversations, cursor=cursor, limit=25)
            rows = page.items
            if operation == 'chat.find' and text:
                rows = [row for row in rows if text.casefold() in (row.title or '').casefold() or text == str(row.id)]
            return Result('Conversations (use /more for older pages):', context,
                          tuple(Item(row.id, 'conversation', row.title or 'Untitled conversation') for row in rows), cursor=page.next_cursor)
        if operation == 'chat.select':
            conversation = self.execute(self.captures.conversation_history, UUID(text))
            return Result('Conversation history:', replace(context, conversation_id=conversation.id, capture_id=None,
                          label=conversation.title or 'Conversation'), payload=data(conversation), cursor=conversation.next_cursor)
        if operation == 'chat.history':
            history = self.execute(self.captures.conversation_history, required(context.conversation_id, 'a conversation'), cursor=cursor)
            return Result('Earlier messages:', context, payload=data(history), cursor=history.next_cursor)
        raise ClientError('Unknown conversation action.')
