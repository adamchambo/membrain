"""Small API client for conversational capture; no database credentials needed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


class TransportError(RuntimeError):
    pass


def request(base: str, method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(base.rstrip("/") + "/api/v1" + path, data=data, method=method,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=60) as response:
            payload = response.read()
        return json.loads(payload) if payload else None
    except HTTPError as exc:
        try:
            detail = json.load(exc).get("detail", "API request failed")
        except (ValueError, AttributeError):
            detail = "API request failed"
        raise RuntimeError(f"{exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise TransportError("Oracle is unreachable; check that the API is running") from exc


def save_message(base: str, text: str, conversation_id: str | None):
    request_id = str(uuid4())
    body = {"raw_text": text, "conversation_id": conversation_id, "request_id": request_id}
    # Reuse the request ID if transport fails so a retry cannot duplicate a save.
    try:
        return request(base, "POST", "/captures/ingest", body)
    except TransportError:
        return request(base, "POST", "/captures/ingest", body)


def state_file(base: str) -> Path:
    root = Path(os.getenv("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / "oracle"
    return root / (hashlib.sha256(base.encode()).hexdigest()[:16] + ".json")


def load_state(base: str):
    try:
        value = json.loads(state_file(base).read_text())
        required = ("capture_id", "conversation_id", "processing_job_id")
        return value if isinstance(value, dict) and all(isinstance(value.get(key), str) for key in required) else None
    except (OSError, ValueError):
        return None


def remember(base: str, receipt):
    target = state_file(base)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(receipt))
        temporary.chmod(0o600)
        temporary.replace(target)
    except OSError:
        print("Saved on the server; this device could not remember the conversation.", file=sys.stderr)


def chat(base: str, conversation_id: str | None, new: bool = False):
    print("Tell Oracle what you're learning. /show, /undo, /new, or /quit.")
    last = None if new else load_state(base)
    if conversation_id and last and last["conversation_id"] != conversation_id:
        last = None
    conversation_id = conversation_id or (last["conversation_id"] if last else None)
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if text == "/quit":
            return
        if text == "/new":
            conversation_id, last = None, None
            remember(base, None)
            print("Started a new conversation.")
            continue
        try:
            if text == "/show":
                if last:
                    detail = request(base, "GET", f"/captures/{last['capture_id']}")
                    print(detail["raw_text"])
                    for concept_id in detail["concept_ids"]:
                        concept = request(base, "GET", f"/concepts/{concept_id}")
                        if concept["latest_revision"]:
                            print(f"{concept['title']}: {concept['latest_revision']['body']}")
                    for proposal in detail["proposals"]:
                        if proposal["kind"] == "clarification" and proposal["status"] == "pending":
                            for question in proposal["payload"].get("questions", []):
                                print("For later: " + question["question"])
                    job = request(base, "GET", f"/jobs/{last['processing_job_id']}")
                    if job["status"] in ("pending", "running", "failed"):
                        print(job["last_error"] or "Saved; organizing your understanding.")
                continue
            if text == "/undo":
                if last:
                    request(base, "POST", f"/captures/{last['capture_id']}/undo")
                    print("Undone. Original words remain in history.")
                continue
            if not text:
                continue
            last = save_message(base, text, conversation_id)
            conversation_id = last["conversation_id"]
            remember(base, last)
            print("Saved.")
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)


def review(base: str, concept_id: str):
    session = request(base, "POST", "/review-sessions", {"concept_ids": [concept_id]})
    question = request(base, "POST", f"/review-sessions/{session['id']}/next")
    print(question["prompt"])
    try:
        response = input("You: ").strip()
        if not response:
            return
        attempt = request(base, "POST", f"/review-sessions/{session['id']}/attempts", {"question_id": question["id"], "response": response})
        print("Answer saved. Preparing recall feedback...")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            result = request(base, "GET", f"/review-attempts/{attempt['id']}")
            if result["feedback"]:
                print("Recall feedback (factual correctness has not been checked):")
                print(result["feedback"]["feedback"])
                return
            job = request(base, "GET", f"/jobs/{attempt['feedback_job_id']}")
            if job["last_error"]:
                break
            time.sleep(0.5)
        print(f"Your answer is saved. Return to review attempt {attempt['id']} for feedback later.")
    except (EOFError, KeyboardInterrupt):
        print()


def main():
    parser = argparse.ArgumentParser(description="Capture learning through the Oracle API")
    parser.add_argument("--api-url", default=os.getenv("ORACLE_API_URL", "http://127.0.0.1:8000"), help="Oracle server URL")
    commands = parser.add_subparsers(dest="command", required=True)
    chat_parser = commands.add_parser("chat", help="Start or resume a capture conversation")
    chat_parser.add_argument("--conversation", help="Existing conversation UUID")
    chat_parser.add_argument("--new", action="store_true", help="Start a fresh conversation instead of resuming")
    capture = commands.add_parser("capture", help="Save one message without waiting for AI")
    capture.add_argument("text", help="Your topic or explanation, in your own words")
    capture.add_argument("--conversation", help="Existing conversation UUID")
    show = commands.add_parser("show", help="Read a saved capture")
    show.add_argument("capture_id", help="Saved capture UUID")
    undo = commands.add_parser("undo", help="Undo a capture's latest derived learning")
    undo.add_argument("capture_id", help="Saved capture UUID")
    review_parser = commands.add_parser("review", help="Try one cue card for a saved concept")
    review_parser.add_argument("concept_id", help="Concept UUID to review")
    args = parser.parse_args()
    try:
        if args.command == "chat":
            chat(args.api_url, args.conversation, args.new)
        elif args.command == "capture":
            receipt = save_message(args.api_url, args.text, args.conversation)
            remember(args.api_url, receipt)
            print(json.dumps(receipt, indent=2))
        elif args.command == "review":
            review(args.api_url, args.concept_id)
        elif args.command == "show":
            print(json.dumps(request(args.api_url, "GET", f"/captures/{args.capture_id}"), indent=2))
        else:
            request(args.api_url, "POST", f"/captures/{args.capture_id}/undo")
            print("Undone")
    except RuntimeError as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
