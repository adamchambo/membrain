"""Practice sessions inside a conversation: cue cards, open questions and multiple choice.

Questions are generated from a frozen, resolved scope. Multiple-choice keys are stored on
the question row and never placed in conversation state or replies until answered.
Feedback keeps two judgments apart: recall against the saved explanation, and factual
correctness by general knowledge, so a consistently recalled mistake is not called right.
"""

import json
import random
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.captures.models import Conversation
from app.conversation.ai_schemas import AnswerAssessment, BlindAnswer, MultipleChoiceOutput, OpenQuestionOutput
from app.conversation.interpret import Intent
from app.conversation.learning import diagnostic_answer, for_model, nothing_saved, saved_view, scope_for, teach
from app.conversation.needs import record
from app.conversation.processor import TurnRun
from app.conversation.prompts import ANSWER_PROMPT, MCQ_CHECK_PROMPT, MCQ_PROMPT, PROMPT_VERSION, QUESTION_PROMPT
from app.errors import Unavailable
from app.review.models import ReviewAttempt, ReviewAttemptConcept, ReviewQuestion, ReviewScopeConcept, ReviewSession

LETTERS = "ABCDE"
DEFAULT_COUNT = 5
FORMAT_NAMES = {"mcq": "multiple-choice questions", "cue_card": "cue cards", "teach_back": "teach-back questions",
                "open": "questions"}


def make_question(run: TurnRun, fmt: str, view: dict, avoid: list[str]) -> dict:
    """Generate one question about view; multiple choice must survive a blind answer check.

    The check answers the question without the key; disagreement means the key or the
    options are unreliable, so after two attempts the question becomes an open one.
    """
    if fmt == "mcq":
        for _ in range(2):
            try:
                output = run.ask(MCQ_PROMPT, {"saved": for_model(view), "avoid": avoid}, MultipleChoiceOutput,
                                 failure="The model could not write a multiple-choice question")
                blind = run.ask(MCQ_CHECK_PROMPT, {"question": output.question, "options": output.options}, BlindAnswer,
                                failure="The model could not check the question")
            except Unavailable:
                continue
            if blind.index == output.correct_index:
                order = list(range(len(output.options)))
                random.shuffle(order)
                options = [output.options[i] for i in order]
                return {"format": "mcq", "question": output.question, "options": options,
                        "key": {"correct_index": order.index(output.correct_index), "rationale": output.rationale,
                                "blind_check": "agreed"}}
        fmt = "open"
    output = run.ask(QUESTION_PROMPT, {"format": fmt, "saved": for_model(view), "avoid": avoid}, OpenQuestionOutput,
                     failure="The model could not write a practice question")
    return {"format": fmt, "question": output.question, "options": None, "key": None}


def render(state: dict) -> str:
    lines = [f"Question {state['number']} of {state['target']}: {state['question']}"]
    for letter, option in zip(LETTERS, state.get("options") or []):
        lines.append(f"  {letter}) {option}")
    hint = {"mcq": "Reply with a letter, or answer in your own words.",
            "cue_card": "Answer from memory; I'll show your saved explanation afterwards."}.get(state["format"], "Answer in your own words.")
    return "\n".join(lines) + "\n" + hint


def add_question(db: Session, session_id: UUID, view: dict, generated: dict, model_key: str, conversation_id: UUID,
                 number: int, target: int, scope_text: str) -> dict:
    question = ReviewQuestion(review_session_id=session_id, concept_id=UUID(view["concept_id"]), revision_id=UUID(view["revision_id"]),
        snapshot={key: view[key] for key in ("concept_id", "title", "revision_id", "explanation")} | {"mode": generated["format"]},
        prompt=generated["question"], model_key=model_key, prompt_version=PROMPT_VERSION, format=generated["format"],
        options=generated["options"], answer_key=generated["key"])
    db.add(question)
    db.flush()
    state = {"type": "practice", "session_id": str(session_id), "question_id": str(question.id), "concept_id": view["concept_id"],
             "format": generated["format"], "question": generated["question"], "options": generated["options"],
             "number": number, "target": target, "scope": scope_text}
    db.get(Conversation, conversation_id).active_activity = state
    return state


def start(run: TurnRun, index: int, intent: Intent, count: int) -> None:
    """Resolve topic/time scope, freeze it in a session, and ask the first question."""
    fmt = intent.format or "open"
    run.note("Finding the material to practise")
    scope = scope_for(run, intent)
    if not scope.concept_ids:
        reply = nothing_saved(scope, "Tell me what you understand about it and I'll save it; then we can practise.")
        run.complete(index, lambda db: {"kind": "practice", "concept_ids": [], "reply": reply})
        return
    available = len(scope.concept_ids)
    target = min(intent.count, 20) if intent.count else (min(DEFAULT_COUNT, available) if fmt == "cue_card" else min(DEFAULT_COUNT, max(3, available)))
    with Session(run.engine) as db:
        view = saved_view(db, scope.concept_ids[0], run.timezone)
    run.note("Writing your first question")
    generated = make_question(run, fmt, view, [])

    def apply(db):
        if run.active and run.active.get("type") == "practice":
            previous = db.get(ReviewSession, UUID(run.active["session_id"]))
            if previous and previous.finished_at is None:
                previous.finished_at = datetime.now(timezone.utc)
        session = ReviewSession(requested_scope=json.dumps(scope.as_json()), mode=fmt, conversation_id=run.conversation_id,
                                target_count=target)
        db.add(session)
        db.flush()
        for concept_id in scope.concept_ids:
            db.add(ReviewScopeConcept(review_session_id=session.id, concept_id=concept_id))
        state = add_question(db, session.id, view, generated, run.client.model_key, run.conversation_id, 1, target, scope.description)
        size = f"{available} saved explanation{'s' if available != 1 else ''}"
        noun = FORMAT_NAMES[fmt] if target != 1 else FORMAT_NAMES[fmt][:-1]
        intro = f"Here {'is' if target == 1 else 'are'} {target} {noun} from {scope.description} ({size})."
        if scope.considered > available:
            intro += f" I used the {available} most relevant of {scope.considered}."
        return {"kind": "practice", "session_id": str(session.id), "concept_ids": [str(x) for x in scope.concept_ids],
                "scope": scope.as_json(), "reply": intro + "\n\n" + render(state)}
    run.complete(index, apply)


def chosen_option(response: str, options: list[str]) -> int | None:
    """Map "B", "b)", "option B" or an option's exact text to its index; None when unclear."""
    match = re.fullmatch(r"\s*(?:option\s+)?\(?([A-Ea-e])\)?[.)!]?\s*", response)
    if match and LETTERS.index(match.group(1).upper()) < len(options):
        return LETTERS.index(match.group(1).upper())
    text = response.strip().casefold().rstrip(".!")
    exact = [i for i, option in enumerate(options) if option.casefold().rstrip(".") == text]
    return exact[0] if len(exact) == 1 else None


def next_concept(db: Session, session_id: UUID) -> UUID | None:
    """Rotate through the frozen scope: the concept asked least often in this session."""
    scope = db.scalars(select(ReviewScopeConcept.concept_id).where(ReviewScopeConcept.review_session_id == session_id)).all()
    counts = dict(db.execute(select(ReviewQuestion.concept_id, func.count()).where(ReviewQuestion.review_session_id == session_id)
                             .group_by(ReviewQuestion.concept_id)).all())
    order = json.loads(db.get(ReviewSession, session_id).requested_scope).get("concept_ids", [])
    rank = {UUID(x): i for i, x in enumerate(order)}
    return min(scope, key=lambda x: (counts.get(x, 0), rank.get(x, len(rank)))) if scope else None


def answer(run: TurnRun, index: int, intent: Intent, count: int) -> None:
    """Record the answer to the active question, give feedback and continue the session."""
    state = run.active
    if not state:
        teach(run, index, Intent(action="teach", topic=None), count)
        return
    if state["type"] == "diagnostic":
        diagnostic_answer(run, index, intent, count)
        return
    with Session(run.engine) as db:
        question = db.get(ReviewQuestion, UUID(state["question_id"]))
        session = db.get(ReviewSession, question.review_session_id)
        snapshot, prompt, fmt, options, key = question.snapshot, question.prompt, question.format, question.options, question.answer_key
        avoid = list(db.scalars(select(ReviewQuestion.prompt).where(ReviewQuestion.review_session_id == session.id)).all())
        number, target = state["number"], session.target_count or DEFAULT_COUNT
        upcoming = next_concept(db, session.id) if number < target else None
        upcoming_view = saved_view(db, upcoming, run.timezone) if upcoming else None
    run.note("Checking your answer")
    chosen = chosen_option(run.message, options) if fmt == "mcq" else None
    payload = {"format": fmt, "question": prompt, "saved": snapshot, "response": run.message}
    if fmt == "mcq":
        payload |= {"options": options, "chosen_index": chosen,
                    "key": {"correct_index": key["correct_index"], "correct_option": options[key["correct_index"]],
                            "rationale": key["rationale"]}}
    assessment = run.ask(ANSWER_PROMPT, payload, AnswerAssessment, failure="The model could not assess your answer")
    if fmt == "mcq":
        if chosen is None and assessment.chosen_index is not None and assessment.chosen_index < len(options):
            chosen = assessment.chosen_index
        factual = "unresolved" if chosen is None else "correct" if chosen == key["correct_index"] else "incorrect"
    else:
        factual = assessment.factual
    generated = None
    if upcoming_view:
        run.note("Writing the next question")
        generated = make_question(run, session.mode, upcoming_view, avoid)

    def apply(db):
        current = db.scalar(select(ReviewQuestion).where(ReviewQuestion.id == UUID(state["question_id"])).with_for_update())
        if current.answered_at is not None:
            return {"kind": "answer", "reply": "That question already has an answer recorded."}
        feedback = {"recall": assessment.recall, "factual": factual, "factual_basis": "answer_key" if fmt == "mcq" else "model_knowledge",
                    "feedback": assessment.feedback, "chosen_index": chosen, "saved_conflict": assessment.saved_conflict,
                    "correctness": "not_verified", "model_key": run.client.model_key, "prompt_version": PROMPT_VERSION}
        attempt = ReviewAttempt(review_session_id=current.review_session_id, question_id=current.id, format=fmt,
                                prompt=current.prompt, response=run.message, feedback=json.dumps(feedback))
        db.add(attempt)
        db.flush()
        db.add(ReviewAttemptConcept(review_attempt_id=attempt.id, concept_id=current.concept_id))
        current.answered_at = datetime.now(timezone.utc)
        if factual in ("incorrect", "partially_correct"):
            record(db, concept_id=current.concept_id, kind="gap", summary=f"Difficulty answering: {current.prompt}"[:600],
                   evidence="observed_in_answer", event="answered", turn_id=run.turn_id,
                   payload={"attempt_id": str(attempt.id), "factual": factual})
        if assessment.saved_conflict:
            record(db, concept_id=current.concept_id, kind="misconception", summary=assessment.saved_conflict[:600],
                   evidence="model_suspected", revision_id=current.revision_id, event="suspected", turn_id=run.turn_id,
                   payload={"attempt_id": str(attempt.id), "source": "practice feedback"})
        lines = [feedback_text(fmt, options, key, chosen, factual, assessment, snapshot)]
        practice_session = db.get(ReviewSession, current.review_session_id)
        if generated and upcoming_view:
            following = add_question(db, practice_session.id, upcoming_view, generated, run.client.model_key, run.conversation_id,
                                     number + 1, target, state.get("scope", ""))
            lines.append(render(following))
        else:
            practice_session.finished_at = datetime.now(timezone.utc)
            db.get(Conversation, run.conversation_id).active_activity = None
            lines.append(summary(db, practice_session.id))
        return {"kind": "answer", "attempt_id": str(attempt.id), "concept_ids": [str(current.concept_id)], "reply": "\n\n".join(lines)}
    run.complete(index, apply)


def feedback_text(fmt, options, key, chosen, factual, assessment: AnswerAssessment, snapshot: dict) -> str:
    lines = []
    if fmt == "mcq":
        right = f"{LETTERS[key['correct_index']]}) {options[key['correct_index']]}"
        if chosen is None:
            lines.append(f"I couldn't tell which option you meant. The answer is {right}.")
        elif factual == "correct":
            lines.append(f"Correct: {right}.")
        else:
            lines.append(f"Not quite: you chose {LETTERS[chosen]}) {options[chosen]}. The answer is {right}.")
        lines.append(assessment.feedback)
    else:
        verdict = {"correct": "correct", "partially_correct": "partly correct", "incorrect": "not correct",
                   "unresolved": "hard to judge"}[factual]
        lines.append(f"{assessment.feedback}\nBy general knowledge, your answer looks {verdict}.")
        if fmt == "cue_card":
            lines.append(f"Your saved explanation: “{snapshot['explanation']}”")
        recall = {"consistent": "matches", "partial": "partly matches", "different": "differs from",
                  "unclear": "is hard to compare with"}.get(assessment.recall)
        if recall:
            lines.append(f"Your answer {recall} what you saved earlier.")
    if assessment.saved_conflict:
        lines.append(f"Your saved explanation may need a look: {assessment.saved_conflict} "
                     "Tell me how you understand it now and I'll save the new version.")
    return "\n".join(lines)


def summary(db: Session, session_id: UUID) -> str:
    attempts = db.scalars(select(ReviewAttempt).where(ReviewAttempt.review_session_id == session_id)).all()
    results = [json.loads(a.feedback).get("factual") for a in attempts if a.feedback]
    correct = sum(result == "correct" for result in results)
    partial = sum(result == "partially_correct" for result in results)
    text = f"That's the end of this set: {correct} of {len(results)} answers correct"
    text += f", {partial} partly correct." if partial else "."
    return text + " That reflects today's answers, not overall mastery."


def stop(run: TurnRun, index: int, intent: Intent, count: int) -> None:
    state = run.active

    def apply(db):
        conversation = db.get(Conversation, run.conversation_id)
        conversation.active_activity = None
        if state and state["type"] == "practice":
            session = db.get(ReviewSession, UUID(state["session_id"]))
            if session.finished_at is None:
                session.finished_at = datetime.now(timezone.utc)
            return {"kind": "stop", "reply": "Stopped. " + summary(db, session.id)}
        return {"kind": "stop", "reply": "Stopped." if state else "There's no active question to stop."}
    run.complete(index, apply)
