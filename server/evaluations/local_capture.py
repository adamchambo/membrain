"""Synthetic evaluation; never reads or modifies the user's bank or settings."""

import json
import time

from app.ai.providers.compatible import CompatibleChatClient
from app.captures.formatter import CaptureAI

CASES = [
    ("topic_only", "I'm learning about computers.", 0),
    ("uncertainty", "I think binary uses ones and zeros, but I'm unsure how they become data.", None),
    ("resource_only", "Bookmark https://example.com/computers for later.", 0),
]


def main():
    client = CompatibleChatClient("http://127.0.0.1:11434/v1/chat/completions", "qwen2.5-coder:3b-base")
    for name, text, expected in CASES:
        started = time.monotonic()
        try:
            result = CaptureAI(client).process(text, {"concepts": [], "history": [], "open_clarifications": []})
            print(json.dumps({"case": name, "schema_valid": True, "expected_understandings": expected,
                              "output": result.model_dump(), "seconds": round(time.monotonic() - started, 2)}), flush=True)
        except Exception as exc:
            print(json.dumps({"case": name, "schema_valid": False, "error_type": type(exc).__name__,
                              "cause_type": type(exc.__cause__).__name__ if exc.__cause__ else None,
                              "seconds": round(time.monotonic() - started, 2)}), flush=True)


if __name__ == "__main__":
    main()
