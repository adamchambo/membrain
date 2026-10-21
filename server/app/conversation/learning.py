"""Recall, teaching, adoption and diagnosis recipes.

Replies quote the user's saved words verbatim from the database; the model contributes
only clearly labelled reminders, teaching and assessments, stored as learning artifacts.
"""

import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.captures.models import Conversation
from app.conversation.ai_schemas import DiagnoseOutput, DiagnosticAssessment, RecallOutput, TeachOutput
from app.conversation.interpret import Intent
from app.conversation.models import ConversationTurn
from app.conversation.needs import HEDGE, rank, record
from app.conversation.processor import TurnRun
from app.conversation.prompts import DIAGNOSE_PROMPT, DIAGNOSTIC_ANSWER_PROMPT, PROMPT_VERSION, RECALL_PROMPT, TEACH_PROMPT
from app.conversation.scope import Scope, resolve, zone
from app.discovery.service import latest_revisions
from app.jobs.service import enqueue_embedding
from app.knowledge.models import CaptureConcept, Concept, ExplanationRevision
from app.knowledge.service import latest_revision
from app.learning.models import LearningArtifact, LearningNeed, LearningNeedEvent, LearningSuggestion
from app.learning.organisation import assign

ANALOGY = re.compile(r"\b(like a|like an|like the|as if|imagine|think of (it|them|this) as|analogy|similar to|just as|picture)\b", re.I)
SAVED_CHARACTERS = 1200


def saved_view(db: Session, concept_id: UUID, timezone_name: str, characters: int = SAVED_CHARACTERS) -> dict | None:
    concept = db.get(Concept, concept_id)
    revision = latest_revision(db, concept_id)
    if concept is None or revision is None:
        return None
    count = db.scalar(select(func.count()).select_from(ExplanationRevision).where(
        ExplanationRevision.concept_id == concept_id, ExplanationRevision.retracted_at.is_(None)))
    body = revision.body if len(revision.body) <= characters else revision.body[:characters] + " …"
    return {"concept_id": str(concept.id), "title": concept.title, "revision_id": str(revision.id), "explanation": body,
            "full_explanation": revision.body, "saved_on": revision.created_at.astimezone(zone(timezone_name)).strftime("%-d %b %Y"),
            "revisions": count, "origin": revision.origin}


def for_model(view: dict) -> dict:
    return {key: view[key] for key in ("concept_id", "title", "explanation", "saved_on")}


def scope_for(run: TurnRun, intent: Intent) -> Scope:
    """Resolve intent's topic, "this" reference and period against the bank."""
    use_context = intent.refers_to_context or (not intent.topic and intent.period == "none")
    context_ids = run.context_ids() if use_context and not intent.topic else None
    vector = run.vector(intent.topic) if intent.topic else None
    with Session(run.engine) as db:
        return resolve(db, topic=intent.topic, refers_to_context=intent.refers_to_context, period=intent.period,
                       days=intent.days, timezone_name=run.timezone, conversation_id=run.conversation_id,
                       context_ids=context_ids, topic_vector=vector)


def nothing_saved(scope: Scope, follow_up: str) -> str:
    about = f" about {scope.topic}" if scope.topic else ""
    when = f" {scope.period_phrase}" if scope.period_phrase else ""
    return (f"I couldn't find any saved explanations{about}{when}. That only means nothing is recorded, "
            f"not that you don't know it. {follow_up}")


def artifact(db: Session, kind: str, inputs: dict, content: str, model_key: str, questions: list[str] | None = None) -> LearningArtifact:
    """Store generated material in the existing LearningOutput shape so artifact reads stay valid;
    structured judgments live in learning needs, events and suggestions instead."""
    output = {"content": content, "optional_questions": questions or [], "citations": [], "suggestions": [],
              "verification": "not_verified", "uncertainty": []}
    item = LearningArtifact(kind=kind, inputs=inputs, output=output, model_key=model_key, prompt_version=PROMPT_VERSION)
    db.add(item)
    db.flush()
    return item


def recall(run: TurnRun, index: int, intent: Intent, count: int) -> None:
    """Remind the user of their own explanation and analogy, then assess it separately."""
    run.note("Finding what you saved")
    scope = scope_for(run, intent)
    keyword = intent.analogy.strip() if intent.analogy is not None else None
    with Session(run.engine) as db:
        ids = list(scope.concept_ids)
        missing_analogy = None
        analogy_ids: list[UUID] = []
        if keyword:
            latest = latest_revisions()
            pattern = "%" + keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            matches = db.scalars(select(ExplanationRevision.concept_id).join(latest, (latest.c.concept_id == ExplanationRevision.concept_id)
                & (latest.c.number == ExplanationRevision.revision_number)).join(Concept, Concept.id == ExplanationRevision.concept_id)
                .where(Concept.archived_at.is_(None), ExplanationRevision.body.ilike(pattern, escape="\\"))).all()
            # The named analogy identifies the concept even when topic matching is imperfect.
            analogy_ids = [x for x in ids if x in matches] or list(matches)
            if not analogy_ids:
                missing_analogy = f"I couldn't find a saved analogy mentioning “{keyword}”."
        views = [view for view in (saved_view(db, x, run.timezone) for x in dict.fromkeys(analogy_ids + ids)) if view][:4]
        if keyword == "" and views and not any(ANALOGY.search(v["full_explanation"]) for v in views):
            missing_analogy = "I couldn't find an analogy in what you've saved here, so here's your explanation instead."
    if not views:
        reply = (missing_analogy + " " if missing_analogy else "") + nothing_saved(
            scope, "Tell me how you understand it and I'll save it in your words.")
        run.complete(index, lambda db: {"kind": "recall", "concept_ids": [], "reply": reply})
        return
    excerpts = []
    for view in views:
        for sentence in re.split(r"(?<=[.!?])\s+", view["full_explanation"]):
            if (keyword and keyword.casefold() in sentence.casefold()) or (keyword == "" and ANALOGY.search(sentence)):
                excerpts.append(sentence)
    run.note("Putting your explanation back together")
    output = run.ask(RECALL_PROMPT, {"request": run.message, "saved": [for_model(v) for v in views],
                     "analogy_excerpts": excerpts[:4]}, RecallOutput, failure="The model could not compose a reminder")
    issue = output.issue_excerpt if output.issue_excerpt and any(output.issue_excerpt in v["full_explanation"] for v in views) else None

    reply = recall_reply(views, output, missing_analogy)

    def apply(db):
        item = artifact(db, "recall", {"question": run.message, "scope": scope.as_json(), "turn_id": str(run.turn_id),
                        "revision_ids": [v["revision_id"] for v in views], "assessment": output.assessment},
                        reply, run.client.model_key)
        if issue and output.assessment in ("inaccurate", "partly_accurate"):
            owner = next(v for v in views if issue in v["full_explanation"])
            record(db, concept_id=UUID(owner["concept_id"]), kind="misconception", evidence="model_suspected",
                   summary=(output.breaks_down or [output.reminder])[0][:600], excerpt=issue, revision_id=UUID(owner["revision_id"]),
                   artifact_id=item.id, event="suspected", turn_id=run.turn_id, payload={"source": "recall"})
        return {"kind": "recall", "artifact_id": str(item.id), "concept_ids": [v["concept_id"] for v in views], "reply": reply}
    run.complete(index, apply)


def quote(view: dict, characters: int = 600) -> str:
    body = view["full_explanation"]
    body = body if len(body) <= characters else body[:characters] + " …"
    source = ("You adopted this explanation from Membrain" if view["origin"] == "user_confirmed_suggestion"
              else "You saved this")
    return f"{source} about {view['title']} ({view['saved_on']}):\n  “{body}”"


def bullets(title: str, items: list[str]) -> str:
    return title + "\n" + "\n".join(f"  - {item}" for item in items)


def recall_reply(views: list[dict], output: RecallOutput, missing: str | None) -> str:
    parts = [missing] if missing else []
    # One sentence can support several concepts; quote it once under all their titles.
    quoted: dict[str, dict] = {}
    for view in views[:3]:
        if view["full_explanation"] in quoted:
            first = quoted[view["full_explanation"]]
            first["title"] = f"{first['title']} and {view['title']}"
        else:
            quoted[view["full_explanation"]] = dict(view)
    parts.extend(quote(view) for view in quoted.values())
    parts.append(output.reminder)
    if output.holds:
        parts.append(bullets("What holds up:", output.holds))
    if output.breaks_down:
        parts.append(bullets("Where it breaks down:", output.breaks_down))
    verdict = {"accurate": "By general knowledge, this looks accurate.",
               "partly_accurate": "By general knowledge, this is partly accurate.",
               "inaccurate": "By general knowledge, part of this looks inaccurate.",
               "unresolved": "I can't judge its accuracy confidently."}[output.assessment]
    if output.assessment != "accurate":
        verdict += " Your saved explanation is unchanged; if your understanding has moved on, tell me and I'll save the new version."
    parts.append(verdict)
    return "\n\n".join(parts)


def teach(run: TurnRun, index: int, intent: Intent, count: int) -> None:
    """Generate teaching material anchored to what the user already saved; never bank it."""
    run.note("Preparing an explanation")
    scope = scope_for(run, intent) if intent.topic or intent.refers_to_context else Scope()
    with Session(run.engine) as db:
        views = [view for view in (saved_view(db, x, run.timezone, 800) for x in scope.concept_ids[:3]) if view]
    output = run.ask(TEACH_PROMPT, {"request": run.message, "topic": intent.topic, "style": intent.style or "explain",
                     "saved": [for_model(v) for v in views]}, TeachOutput, failure="The model could not prepare an explanation")

    def apply(db):
        item = artifact(db, "lesson", {"question": run.message, "topic": intent.topic, "style": intent.style or "explain",
                        "turn_id": str(run.turn_id), "concept_ids": [v["concept_id"] for v in views],
                        "revision_ids": [v["revision_id"] for v in views], "summary": output.summary},
                        output.content, run.client.model_key, [output.check_question] if output.check_question else None)
        parts = [output.content]
        if output.check_question:
            parts.append("Check yourself: " + output.check_question)
        parts.append("If that matches how you'd put it, say “save that”; or tell me your own version and I'll save your words.")
        return {"kind": "teach", "artifact_id": str(item.id), "topic": intent.topic, "summary": output.summary,
                "concept_ids": [v["concept_id"] for v in views], "reply": "\n\n".join(parts)}
    run.complete(index, apply)


def adopt(run: TurnRun, index: int, intent: Intent, count: int) -> None:
    """Save the latest teaching summary as the user's explanation, with explicit provenance."""
    with Session(run.engine) as db:
        source = None
        for turn in db.scalars(select(ConversationTurn).where(ConversationTurn.conversation_id == run.conversation_id,
                               ConversationTurn.sequence < run.sequence).order_by(ConversationTurn.sequence.desc()).limit(2)).all():
            source = next((e for e in turn.effects.values() if e.get("kind") == "teach"), None)
            if source:
                break
    if source is None:
        reply = ("I'm not sure which explanation you mean. Tell me the idea in your own words and I'll save it.")
        run.complete(index, lambda db: {"kind": "adopt", "reply": reply})
        return

    def apply(db):
        item = db.get(LearningArtifact, UUID(source["artifact_id"]))
        summary = source["summary"]
        targets = source.get("concept_ids") or []
        conversation = db.get(Conversation, run.conversation_id)
        if len(targets) == 1 and (concept := db.get(Concept, UUID(targets[0]))) and concept.archived_at is None:
            created = False
        else:
            title = (source.get("topic") or summary.split(".")[0]).strip()[:255]
            concept, created = Concept(title=title[:1].upper() + title[1:]), True
            db.add(concept)
            db.flush()
        suggestion = LearningSuggestion(artifact_id=item.id, kind="correction", status="adopted", decision_note=run.message[:4000],
            decided_at=datetime.now(timezone.utc), payload={"kind": "correction", "concept_id": str(concept.id),
            "rationale": "Adopted in conversation from Membrain's explanation", "explanation_text": summary,
            "evidence": "uncertain", "citations": []})
        db.add(suggestion)
        db.flush()
        number = db.scalar(select(func.max(ExplanationRevision.revision_number)).where(ExplanationRevision.concept_id == concept.id)) or 0
        revision = ExplanationRevision(concept_id=concept.id, capture_id=run.capture_id, revision_number=number + 1, body=summary,
                                       origin="user_confirmed_suggestion", suggestion_id=suggestion.id)
        db.add(revision)
        db.flush()
        suggestion.applied_revision_id = revision.id
        if db.get(CaptureConcept, (run.capture_id, concept.id)) is None:
            db.add(CaptureConcept(capture_id=run.capture_id, concept_id=concept.id))
        if conversation.subject_id:
            assign(db, conversation.subject_id, concept.id, run.capture_id)
        enqueue_embedding(db, revision.id)
        note = "as a new concept" if created else "as the latest version"
        return {"kind": "adopt", "banked": [{"concept_id": str(concept.id), "title": concept.title, "revision_id": str(revision.id),
                "created": created, "subjects": []}],
                "reply": f"Saved that explanation of “{concept.title}” {note}, marked as adopted from my explanation "
                         f"rather than written or recalled by you:\n  “{summary}”"}
    run.complete(index, apply)


def diagnose(run: TurnRun, index: int, intent: Intent, count: int) -> None:
    """Suggest specific suspected misconceptions or gaps, then ask one diagnostic question."""
    run.note("Looking through your saved explanations")
    whole = intent.whole_bank or (not intent.topic and not intent.refers_to_context and intent.period == "none")
    with Session(run.engine) as db:
        if whole:
            candidates, considered = rank(db)
            ids = [c["concept_id"] for c in candidates]
            scope = Scope(concept_ids=ids, considered=considered, basis="bank")
        else:
            candidates = []
    if not whole:
        scope = scope_for(run, intent)
        ids = scope.concept_ids[:6]
    if not ids:
        reply = nothing_saved(scope, "Tell me how you understand it and I'll look for gaps in your explanation.") if not whole else \
            "Your bank has no saved explanations yet. Tell me something you've learned and I'll save it."
        run.complete(index, lambda db: {"kind": "diagnose", "reply": reply})
        return
    with Session(run.engine) as db:
        views = [view for view in (saved_view(db, x, run.timezone, 700) for x in ids) if view]
        evidence = [{"concept_id": str(n.concept_id), "kind": n.kind, "evidence": n.evidence, "summary": n.summary[:300]}
                    for n in db.scalars(select(LearningNeed).where(LearningNeed.concept_id.in_(ids),
                                        LearningNeed.status.in_(["open", "exploring"]))).all()][:8]
        asked = db.scalars(select(LearningNeedEvent.payload).join(LearningNeed, LearningNeed.id == LearningNeedEvent.need_id)
            .where(LearningNeed.concept_id.in_(ids), LearningNeedEvent.kind == "asked")
            .order_by(LearningNeedEvent.created_at.desc()).limit(6)).all()
    payload = {"request": run.message, "saved": [for_model(v) for v in views], "evidence": evidence,
               "already_asked": [item["question"] for item in asked if item.get("question")]}
    if whole:
        payload["candidates"] = [{"concept_id": str(c["concept_id"]), "title": c["title"], "reasons": c["reasons"]} for c in candidates]
        payload["instruction"] = "Choose the single most useful candidate to check now and focus findings on it."
    output = run.ask(DIAGNOSE_PROMPT, payload, DiagnoseOutput, failure="The model could not assess your explanations")
    by_id = {v["concept_id"]: v for v in views}
    findings = [f for f in output.findings if str(f.concept_id) in by_id]
    question_concept = str(output.question.concept_id) if str(output.question.concept_id) in by_id else \
        (str(findings[0].concept_id) if findings else views[0]["concept_id"])

    def apply(db):
        item = artifact(db, "diagnosis", {"question": run.message, "scope": scope.as_json(), "turn_id": str(run.turn_id),
                        "revision_ids": [v["revision_id"] for v in views],
                        "candidates": [{**c, "concept_id": str(c["concept_id"]), "revision_id": str(c["revision_id"])} for c in candidates]},
                        "", run.client.model_key, [output.question.text])
        asked_need = None
        lines = []
        if whole:
            chosen = by_id[question_concept]
            reason = output.reason or "; ".join(next((c["reasons"] for c in candidates if str(c["concept_id"]) == question_concept), []))
            lines.append(f"I looked across all {scope.considered} saved concepts and picked “{chosen['title']}”"
                         + (f": {reason}" if reason else "."))
        for finding in findings:
            view = by_id[str(finding.concept_id)]
            excerpt = finding.user_excerpt if finding.user_excerpt and finding.user_excerpt in view["full_explanation"] else None
            hedged = bool(excerpt and HEDGE.search(excerpt))
            need = record(db, concept_id=finding.concept_id, kind=finding.kind, summary=finding.summary,
                          evidence="user_uncertain" if hedged else "model_suspected", excerpt=excerpt,
                          revision_id=UUID(view["revision_id"]), artifact_id=item.id, event="suspected", turn_id=run.turn_id,
                          payload={"why": finding.why, "confidence": finding.confidence})
            if str(finding.concept_id) == question_concept and asked_need is None:
                asked_need = need
            label = "Possible misconception" if finding.kind == "misconception" else "Possible gap"
            line = f"{label} in “{view['title']}” ({finding.confidence} confidence, my suspicion from general knowledge):"
            if excerpt:
                line += f" you wrote “{excerpt}”."
            lines.append(f"{line} {finding.why}")
        if not findings:
            lines.append("I didn't spot a specific error in what you saved. A question can still show whether something is missing.")
        if asked_need is None:
            asked_need = record(db, concept_id=UUID(question_concept), kind="gap", summary=("Checking with: " + output.question.text)[:600],
                                evidence="model_suspected", artifact_id=item.id, event="suspected", turn_id=run.turn_id,
                                payload={"source": "diagnostic question"})
        db.add(LearningNeedEvent(need_id=asked_need.id, kind="asked", turn_id=run.turn_id, payload={"question": output.question.text}))
        asked_need.status = "exploring"
        conversation = db.get(Conversation, run.conversation_id)
        conversation.active_activity = {"type": "diagnostic", "need_id": str(asked_need.id), "concept_id": question_concept,
                                        "question": output.question.text, "format": "diagnostic"}
        lines.append("Question to check: " + output.question.text)
        reply = "\n\n".join(lines)
        item.output = {**item.output, "content": reply}
        return {"kind": "diagnose", "artifact_id": str(item.id), "concept_ids": [v["concept_id"] for v in views], "reply": reply}
    run.complete(index, apply)


def diagnostic_answer(run: TurnRun, index: int, intent: Intent, count: int) -> None:
    """Assess an answer to the active diagnostic and add it to that need's history."""
    state = run.active
    run.note("Thinking about your answer")
    with Session(run.engine) as db:
        need = db.get(LearningNeed, UUID(state["need_id"]))
        view = saved_view(db, need.concept_id, run.timezone, 800) if need else None
        need_view = {"kind": need.kind, "summary": need.summary, "user_excerpt": need.user_excerpt} if need else None
    output = run.ask(DIAGNOSTIC_ANSWER_PROMPT, {"question": state["question"], "need": need_view,
                     "saved": for_model(view) if view else None, "response": run.message}, DiagnosticAssessment,
                     failure="The model could not assess your answer")

    def apply(db):
        conversation = db.get(Conversation, run.conversation_id)
        current = db.get(LearningNeed, UUID(state["need_id"]))
        lines = [output.feedback]
        if current is not None:
            db.add(LearningNeedEvent(need_id=current.id, kind="answered", turn_id=run.turn_id,
                                     payload={"response": run.message, "outcome": output.outcome, "feedback": output.feedback}))
            current.updated_at = datetime.now(timezone.utc)
            if output.outcome == "difficulty_observed":
                current.evidence, current.status = "observed_in_answer", "exploring"
                lines.append("I've noted this as something to revisit.")
            elif output.outcome == "improvement_observed":
                current.status = "improved"
                lines.append("Noted as improvement observed; one answer isn't proof of mastery.")
        conversation.active_activity = None
        lines.append("If your understanding has changed, tell me in your own words and I'll save it.")
        return {"kind": "diagnostic_answer", "concept_ids": [view["concept_id"]] if view else [], "reply": "\n\n".join(lines)}
    run.complete(index, apply)


HELP = """You can just talk to me. For example:
- “I'm learning how LLMs work. I understand that …” saves your explanation in your words and files it automatically.
- “Remind me how fractions work, using my pizza analogy.”
- “What gaps or misunderstandings do I have about maths?” or “Pick a gap from anything I've learned.”
- “Give me cue cards for what I learned recently about binary.” or “A multiple-choice quiz on LLMs.”
- “Explain attention with a diagram.” Then “save that” or “I get it now: …”.
Commands: /new starts a new conversation, /menu opens the classic menus, /undo retracts what your last message saved, /help, /quit."""


def help_reply(run: TurnRun, index: int, intent: Intent, count: int) -> None:
    run.complete(index, lambda db: {"kind": "help", "reply": HELP})
