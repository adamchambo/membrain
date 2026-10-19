"""A small boundary for formatting user-supplied explanations."""

import json
import os
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.errors import Unavailable


class FormatCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_title: str = Field(min_length=1, max_length=255)
    explanation_text: str = Field(min_length=1)
    uncertainty: list[str] = Field(default_factory=list)

    @field_validator("candidate_title", "explanation_text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A formatting candidate cannot be blank")
        return value.strip()


class Formatter(Protocol):
    model_key: str

    def format(self, raw_text: str) -> FormatCandidate:
        """Return a structured version of the user's words without adding facts."""


class ChatCompletionsFormatter:
    """Use a configured OpenAI-compatible chat-completions endpoint."""

    def __init__(self, url: str, model_key: str, api_key: str | None):
        self.url = url
        self.model_key = model_key
        self.api_key = api_key

    def format(self, raw_text: str) -> FormatCandidate:
        payload = {
            "model": self.model_key,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Organize the user's explanation into JSON with exactly these keys: "
                        "candidate_title (string), explanation_text (string), uncertainty (array of strings). "
                        "Preserve the user's meaning and uncertainty. Do not add facts, definitions, "
                        "corrections, or claims the user did not make. Return JSON only."
                    ),
                },
                {"role": "user", "content": raw_text},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=45) as response:
                result = json.load(response)
            content = result["choices"][0]["message"]["content"]
            return FormatCandidate.model_validate_json(content)
        except (HTTPError, URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            raise Unavailable("The configured formatter did not return a valid explanation candidate") from exc


def get_formatter() -> Formatter:
    """Read the configured endpoint, model name, and optional secret."""
    url = os.getenv("ORACLE_CHAT_COMPLETIONS_URL")
    model_key = os.getenv("ORACLE_CHAT_MODEL")
    if not url or not model_key:
        raise Unavailable("A conversation model is not configured for formatting")
    return ChatCompletionsFormatter(url, model_key, os.getenv("ORACLE_CHAT_API_KEY"))
