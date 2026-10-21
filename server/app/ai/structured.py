"""Validate untrusted model text against a schema, with one bounded repair attempt."""

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.client import ChatClient
from app.errors import Unavailable

Model = TypeVar("Model", bound=BaseModel)


def json_object(text: str) -> str:
    """Return the outermost JSON object in text, ignoring reasoning blocks and code fences."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("No JSON object in model output")
    return text[start:end + 1]


def generate(client: ChatClient, system_prompt: str, payload: dict, schema: type[Model], *, failure: str) -> Model:
    """Ask client for schema-valid JSON; payload is serialized data, failure is the safe user-facing error.

    A second attempt includes the validation error, because local models often fix
    a missing field or wrong enum value when told which one was rejected.
    """
    user_input = json.dumps(payload, default=str, ensure_ascii=False)
    error = None
    for _ in range(2):
        text = client.generate(system_prompt, user_input if error is None else json.dumps(
            {**payload, "previous_output_error": error[:600]}, default=str, ensure_ascii=False))
        try:
            return schema.model_validate_json(json_object(text))
        except (ValidationError, ValueError) as exc:
            error = str(exc)
    raise Unavailable(failure)
