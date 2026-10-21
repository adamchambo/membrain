"""Capture tasks over a shared provider client."""

import json
from typing import Protocol

from pydantic import ValidationError

from app.ai.client import ChatClient, get_chat_client
from app.ai.structured import generate
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
        return generate(self.client, CAPTURE_PROMPT, {"raw_text": raw_text, "context": context,
                        "output_schema": CaptureOutput.model_json_schema()}, CaptureOutput,
                        failure="The model returned an invalid capture result")


def get_formatter() -> CaptureAI:
    return CaptureAI(get_chat_client())
