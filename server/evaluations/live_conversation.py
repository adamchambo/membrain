"""Run a scripted learning conversation end to end on the configured models.

Run from server/ with DATABASE_URL naming a disposable, migrated membrain_test_* database:
    PYTHONPATH=. ../.venv/bin/python evaluations/live_conversation.py [out.json]
Turns go through the real API service and worker code, so routing, banking, scope,
practice and diagnosis are exercised exactly as in the product. Messages are synthetic.
"""

import json
import os
import sys
import time
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.captures.models import Conversation
from app.conversation import service
from app.conversation.models import ConversationTurn
from app.conversation.schemas import TurnCreate
from app.jobs.models import WorkItem
from app.jobs.worker import run_one
from app.review.models import ReviewQuestion

# None starts a new conversation; "{key}" is replaced by the active question's correct letter.
SCRIPT = [
    ("I'm learning how computers represent numbers. I think binary uses only 0 and 1, and each position is worth double the one to its right.", "new"),
    ("Hexadecimal is like binary but with 16 symbols, so one hex digit stands for four bits, kind of like how an egg box packs 12 eggs into one unit.", None),
    ("Quiz me on this with 2 multiple-choice questions", None),
    ("{key}", None),
    ("{wrong}", None),
    ("Remind me of my egg box analogy", None),
    ("What gaps or misunderstandings do I have about number systems?", None),
    ("I think computers use binary because it's easier to store, but I'm not sure why exactly.", None),
    ("Explain two's complement with a diagram", None),
    ("Yes, save that", None),
    ("I'm learning about LLMs. Attention lets each token weigh the other tokens by how relevant they are.", "new"),
    ("Give me cue cards for what I learned recently", None),
    ("Binary uses two digits and place values double each step.", None),
    ("stop", None),
    ("Pick a gap from anything I've learned", "new"),
    ("I'm not sure, maybe it just averages them?", None),
    ("What did I say about binary?", "new"),
]


def drain(engine, limit=40):
    """Run queued work (turns and embeddings) until nothing is immediately runnable."""
    for _ in range(limit):
        if not run_one(engine):
            return


def letters(engine, conversation_id):
    with Session(engine) as db:
        state = db.get(Conversation, conversation_id).active_activity
        if not state or state.get("format") != "mcq":
            return "A", "B"
        key = db.get(ReviewQuestion, UUID(state["question_id"])).answer_key["correct_index"]
    return "ABCDE"[key], "ABCDE"[(key + 1) % len(state["options"])]


def main():
    url = make_url(os.environ["DATABASE_URL"])
    if not (url.database or "").startswith("membrain_test_"):
        raise SystemExit("Refusing to run outside a disposable membrain_test_* database")
    engine = create_engine(url)
    results, conversation = [], None
    for text, mode in SCRIPT:
        if mode == "new":
            conversation = None
        if "{" in text:
            right, wrong = letters(engine, conversation)
            text = text.format(key=right, wrong=wrong)
        started = time.monotonic()
        with Session(engine, expire_on_commit=False) as db:
            turn = service.submit(db, TurnCreate(text=text, client_message_id=uuid4(), conversation_id=conversation,
                                                 timezone="Europe/London"))
        conversation = turn.conversation_id
        while True:
            run_one(engine, job_id=turn.job_id)
            with Session(engine) as db:
                read = service.get(db, turn.id)
                job = db.get(WorkItem, turn.job_id)
                if read.status != "processing" or job.status != "pending" or job.attempts >= 5:
                    break
            time.sleep(1)
        with Session(engine) as db:
            intents = db.get(ConversationTurn, turn.id).intents
        elapsed = round(time.monotonic() - started, 1)
        results.append({"message": text, "intents": intents, "status": read.status, "error": read.error,
                        "seconds": elapsed, "reply": read.reply})
        print(f"\n>>> {text}\n[{read.status}, {elapsed}s] {json.dumps((intents or {}).get('intents'))}\n{read.reply or read.error}", flush=True)
        drain(engine)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as stream:
            json.dump(results, stream, indent=2, default=str)


if __name__ == "__main__":
    main()
