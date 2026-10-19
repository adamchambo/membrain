"""Capture tasks over a shared provider client."""

import json
from typing import Protocol

from pydantic import ValidationError

from app.ai.client import ChatClient, get_chat_client
from app.captures.ai_schemas import CaptureOutput, FormatCandidate
from app.captures.prompts.formatting import CAPTURE_PROMPT, CAPTURE_VERSION, FORMAT_PROMPT
from app.errors import Unavailable


class Formatter(Protocol):
    model_key: str

    def format(self, raw_text: str) -> FormatCandidate:
        """Format raw_text without adding factual claims."""


class CaptureAI:
    def __init__(self, client: ChatClient):
        self.client = client
        self.model_key = client.model_key
        self.prompt_version = CAPTURE_VERSION

    def format(self, raw_text: str) -> FormatCandidate:
        try:
            return FormatCandidate.model_validate_json(self.client.generate(FORMAT_PROMPT, raw_text))
        except ValidationError as exc:
            raise Unavailable("The model returned an invalid formatting candidate") from exc

    def process(self, raw_text: str, context: dict) -> CaptureOutput:
        user_input = json.dumps({"raw_text": raw_text, "context": context,
                                 "output_schema": CaptureOutput.model_json_schema()})
        try:
            return CaptureOutput.model_validate_json(self.client.generate(CAPTURE_PROMPT, user_input))
        except ValidationError as exc:
            raise Unavailable("The model returned an invalid capture result") from exc


def get_formatter() -> CaptureAI:
    return CaptureAI(get_chat_client())
