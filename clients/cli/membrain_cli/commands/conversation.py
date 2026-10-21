"""Conversational turns: the server interprets each message and chooses the activity."""
from __future__ import annotations
from dataclasses import replace
import membrain_sdk as sdk
from ..config import local_timezone
from ..types import ClientError, Context, Result

from . import data, required


def turn_result(turn, context: Context) -> Result:
    """Wrap a TurnRead; payload is wire data so the session needs no SDK types."""
    context = replace(context, conversation_id=turn.conversation_id, capture_id=turn.capture_id, turn_id=turn.id)
    return Result(turn.reply or '', context, payload=data(turn))


class ConversationCommands:
    def _turn(self, operation, text, context):
        if operation == 'turn.send':
            turn = self.execute(self.conversation.submit_turn, sdk.TurnCreate(
                text=text, client_message_id=required(context.request_id, 'a message'),
                conversation_id=context.conversation_id, timezone=local_timezone()))
        elif operation == 'turn.get':
            turn = self.execute(self.conversation.get_turn, required(context.turn_id, 'a message'))
        elif operation == 'turn.retry':
            turn = self.execute(self.conversation.retry_turn, required(context.turn_id, 'a message'))
        elif operation == 'turn.history':
            page = self.execute(self.conversation.list_turns, required(context.conversation_id, 'a conversation'),
                                limit=int(text or 10))
            return Result('', context, payload=[data(turn) for turn in page.items])
        else:
            raise ClientError(f'Unsupported CLI operation: {operation}')
        return turn_result(turn, context)
