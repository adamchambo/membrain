"""Provider selection without feature prompts or database decisions."""

import os
from typing import Protocol

from app.errors import NotConfigured
from app.config import setting


class ChatClient(Protocol):
    model_key: str

    def generate(self, system_prompt: str, user_input: str) -> str:
        """Send task instructions and user/context data; return untrusted text."""


def get_chat_client() -> ChatClient:
    from app.ai.providers.compatible import CompatibleChatClient

    url = setting("ORACLE_CHAT_COMPLETIONS_URL")
    model = setting("ORACLE_CHAT_MODEL")
    if not url or not model:
        raise NotConfigured("A conversation model is not configured")
    return CompatibleChatClient(url, model, setting("ORACLE_CHAT_API_KEY"))
