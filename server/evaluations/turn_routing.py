"""Measure turn routing on the configured chat model with labelled synthetic turns.

Run from server/: PYTHONPATH=. ../.venv/bin/python evaluations/turn_routing.py
No database access; only the router prompt and synthetic text reach the model.
"""

import json
import sys
import time

from app.ai.client import get_chat_client
from app.conversation.interpret import route

MCQ = {"type": "practice", "format": "mcq", "question": "What does a transformer's attention compute?",
       "options": ["A) Word frequencies", "B) Weighted mixes of other tokens' values", "C) Grammar rules", "D) A random sample"]}
OPEN = {"type": "practice", "format": "cue_card", "question": "Explain in your own words how binary represents numbers."}
LESSON = [{"role": "assistant", "content": "A fraction a/b means a parts of a whole split into b equal parts..."}]

# (message, context, expected actions in order, expected slot checks)
CASES = [
    ("I'm learning how LLMs work. I understand that they predict the next token from probabilities learned in training.", {}, ["bank"], {}),
    ("I'm looking into maths.", {}, ["bank"], {}),
    ("I learned that binary uses only 0 and 1 because transistors have two states. Quiz me on it.", {}, ["bank", "practice"], {"1.refers_to_context": True}),
    ("What gaps or misunderstandings do I have about maths?", {}, ["diagnose"], {"0.topic~": "math"}),
    ("Pick a gap from anything I've learned.", {}, ["diagnose"], {"0.whole_bank": True}),
    ("Remind me how fractions work, using my pizza analogy.", {}, ["recall"], {"0.analogy~": "pizza"}),
    ("Remind me how this works using my analogy", {"recent_turns": LESSON}, ["recall"], {"0.refers_to_context": True}),
    ("Give me cue cards for things I learned recently about LLMs", {}, ["practice"], {"0.format": "cue_card", "0.period": "recent", "0.topic~": "llm"}),
    ("Give me a multiple-choice quiz about binary", {}, ["practice"], {"0.format": "mcq", "0.topic~": "binary"}),
    ("Quiz me on what I learned last week", {}, ["practice"], {"0.period": "last_week"}),
    ("Show me a diagram of how attention works", {}, ["teach"], {"0.style": "diagram"}),
    ("Can you explain what a derivative is?", {}, ["teach"], {"0.topic~": "derivative"}),
    ("I get it now: a derivative is the slope of the curve at a single point.", {"recent_turns": LESSON}, ["bank"], {}),
    ("Yes, save that explanation", {"recent_turns": LESSON}, ["adopt"], {}),
    ("B", {"active_activity": MCQ}, ["answer"], {}),
    ("I think it's the weighted mix one", {"active_activity": MCQ}, ["answer"], {}),
    ("Binary is base two, each place is a power of two", {"active_activity": OPEN}, ["answer"], {}),
    ("I don't know", {"active_activity": OPEN}, ["answer"], {}),
    ("stop the quiz", {"active_activity": OPEN}, ["stop"], {}),
    ("What can you do?", {}, ["help"], {}),
    ("Actually, I now think tokens are pieces of words, not whole words. I'm not sure how they're chosen though.", {}, ["bank"], {}),
    ("What did I say about recursion?", {}, ["recall"], {"0.topic~": "recursion"}),
]


def check(result, expected, slots):
    actions = [intent.action for intent in result.intents]
    problems = [] if actions == expected else [f"actions {actions} != {expected}"]
    for key, wanted in slots.items():
        index, field = key.split(".", 1)
        fuzzy = field.endswith("~")
        field = field.rstrip("~")
        if int(index) >= len(result.intents):
            problems.append(f"missing intent {index}")
            continue
        value = getattr(result.intents[int(index)], field)
        if fuzzy and not (value and wanted in value.casefold()) or not fuzzy and value != wanted:
            problems.append(f"{field}={value!r} expected {wanted!r}")
    return problems


def main():
    client = get_chat_client()
    rows, passed = [], 0
    for message, context, expected, slots in CASES:
        started = time.monotonic()
        try:
            result = route(client, message, context)
            problems = check(result, expected, slots)
            output = result.model_dump(exclude_defaults=True)
        except Exception as exc:  # Record the failure type for the evaluation report.
            problems, output = [f"{type(exc).__name__}: {exc}"], None
        elapsed = round(time.monotonic() - started, 2)
        passed += not problems
        rows.append({"message": message, "expected": expected, "output": output, "problems": problems, "seconds": elapsed})
        print(("PASS" if not problems else "FAIL"), f"{elapsed:>6}s", message[:70], "" if not problems else problems, flush=True)
    print(f"\n{passed}/{len(CASES)} passed; model {client.model_key}")
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as file:
            json.dump({"model": client.model_key, "passed": passed, "total": len(CASES), "rows": rows}, file, indent=2)


if __name__ == "__main__":
    main()
