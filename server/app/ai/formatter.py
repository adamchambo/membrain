"""Compatibility imports for the original format API; ownership is feature-local."""

from app.ai.providers.compatible import CompatibleChatClient
from app.captures.ai_schemas import FormatCandidate
from app.captures.formatter import CaptureAI, Formatter, get_formatter


class ChatCompletionsFormatter(CaptureAI):
    def __init__(self, url: str, model_key: str, api_key: str | None):
        super().__init__(CompatibleChatClient(url, model_key, api_key))


__all__ = ["FormatCandidate", "Formatter", "ChatCompletionsFormatter", "get_formatter"]
