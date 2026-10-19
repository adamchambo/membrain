"""Chat and embedding transport for compatible local or remote HTTP servers."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.errors import Unavailable


def post_json(url: str, payload: dict, api_key: str | None = None) -> dict:
    """POST payload to url, using api_key only as a bearer credential."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=45) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("Provider response exceeds limit")
            result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Expected an object")
        return result
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise Unavailable("The configured AI endpoint failed to return a valid response") from exc


class CompatibleChatClient:
    def __init__(self, url: str, model_key: str, api_key: str | None = None):
        self.url = url
        self.model_key = model_key
        self.api_key = api_key

    def generate(self, system_prompt: str, user_input: str) -> str:
        result = post_json(self.url, {
            "model": self.model_key,
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
