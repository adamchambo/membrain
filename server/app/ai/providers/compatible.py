"""Chat and embedding transport for compatible local or remote HTTP servers."""

import json
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.errors import Unavailable


def post_json(url: str, payload: dict, api_key: str | None = None, *, timeout: float = 60) -> dict:
    """POST payload to url, using api_key as a bearer credential and timeout as the read limit in seconds."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("Provider response exceeds limit")
            result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Expected an object")
        return result
    except (TimeoutError, socket.timeout) as exc:
        raise Unavailable("The model exceeded its response time limit; your saved input is retained") from exc
    except HTTPError as exc:
        raise Unavailable(f"The model rejected the request (HTTP {exc.code}); check its profile and context limits") from exc
    except URLError as exc:
        detail = "The model exceeded its response time limit" if isinstance(exc.reason, TimeoutError) else "The configured model endpoint is unavailable"
        raise Unavailable(detail) from exc
    except (OSError, ValueError) as exc:
        raise Unavailable("The model endpoint returned an invalid response") from exc


class CompatibleChatClient:
    def __init__(self, url: str, model_key: str, api_key: str | None = None, *,
                 profile: str = "standard", max_tokens: int = 2048, temperature: float = 0.2):
        """Connect to url/model_key with optional API key, named thinking profile and output/sampling limits."""
        self.url = url
        self.model_key = model_key
        self.api_key = api_key
        self.profile, self.max_tokens, self.temperature = profile, max_tokens, temperature

    def generate(self, system_prompt: str, user_input: str) -> str:
        if self.profile == "qwen3_fast":
            system_prompt += "\n/no_think"
        result = post_json(self.url, {
            "model": self.model_key,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_input}],
        }, self.api_key)
        try:
            content = result["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Expected text")
            return content
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise Unavailable("The configured conversation model returned no text") from exc
