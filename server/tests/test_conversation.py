"""Conversational turns against a disposable database, with a scripted model per prompt."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

import test_ingestion as support
from app.captures.models import Capture, Conversation
from app.captures.prompts.formatting import CAPTURE_PROMPT
from app.conversation import prompts
from app.conversation.interpret import ROUTER_PROMPT, Intent, RouterOutput, guard, route, shortcut
from app.conversation.models import ConversationTurn
from app.conversation.scope import period_bounds
from app.jobs.models import WorkItem
from app.jobs.worker import run_one
from app.knowledge.models import Concept, ExplanationRevision
from app.learning.models import LearningNeed, LearningNeedEvent, LearningSuggestion, Subject, SubjectConcept
from app.portability.service import V2_COLUMNS, V2_TABLES, export_bank, import_bank
from app.review.models import ReviewAttempt, ReviewQuestion, ReviewSession

NAMES = {ROUTER_PROMPT: "router", CAPTURE_PROMPT: "capture", prompts.RECALL_PROMPT: "recall", prompts.TEACH_PROMPT: "teach",
         prompts.DIAGNOSE_PROMPT: "diagnose", prompts.QUESTION_PROMPT: "question", prompts.MCQ_PROMPT: "mcq",
         prompts.MCQ_CHECK_PROMPT: "mcq_check", prompts.ANSWER_PROMPT: "answer",
         prompts.DIAGNOSTIC_ANSWER_PROMPT: "diagnostic_answer"}


class Model:
    """Answers by prompt name; a list is consumed in order, a callable receives the payload."""
    model_key = "test-chat"

    def __init__(self, **responses):
        self.responses, self.calls = responses, []

    def generate(self, system_prompt, user_input):
        name, payload = NAMES[system_prompt], json.loads(user_input)
        self.calls.append((name, payload))
        value = self.responses[name]
        if isinstance(value, list):
            value = value.pop(0)
        if callable(value):
            value = value(payload)
        return value if isinstance(value, str) else json.dumps(value)

    def count(self, name):
        return sum(call[0] == name for call in self.calls)


def intents(*items):
    return {"intents": list(items)}


def capture(*items, topic=None, subject=None):
    return {"schema_version": "capture.v2", "topic_title": topic, "topic_subject": subject, "understandings": list(items),
            "clarifications": [], "answered_clarification_id": None}


def item(title, text, subjects=(), concept_id=None):
    return {**support.understanding(title, text, concept_id=concept_id), "subjects": list(subjects)}


class ConversationTests(unittest.TestCase):
    setUpClass = classmethod(support.IngestionTests.setUpClass.__func__)
    tearDownClass = classmethod(support.IngestionTests.tearDownClass.__func__)
    setUp = support.IngestionTests.setUp
    tearDown = support.IngestionTests.tearDown
    api = support.IngestionTests.api
    rows = support.IngestionTests.rows

    def submit(self, text, conversation=None, message_id=None, tz="UTC"):
        return self.api("POST", "/turns", {"text": text, "client_message_id": message_id or str(uuid4()),
                                           "conversation_id": conversation, "timezone": tz}, 202)

    def run_turn(self, turn, model):
        with Session(self.engine) as db, db.begin():
            db.execute(update(WorkItem).where(WorkItem.id == UUID(turn["job_id"]))
                       .values(available_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        run_one(self.engine, job_id=UUID(turn["job_id"]), client=model)
        return self.api("GET", f"/turns/{turn['id']}")

    def send(self, text, model, conversation=None, tz="UTC"):
        return self.run_turn(self.submit(text, conversation, tz=tz), model)

    def bank(self, title, text, conversation=None, subjects=()):
        model = Model(router=intents({"action": "bank"}), capture=capture(item(title, text, subjects)))
        return self.send(text, model, conversation)

    def test_turn_is_saved_verbatim_before_inference_and_idempotent(self):
        message_id = str(uuid4())
        first = self.submit("  I think binary uses two symbols.  ", message_id=message_id)
        repeat = self.submit("  I think binary uses two symbols.  ", message_id=message_id)
        self.assertEqual(first["id"], repeat["id"])
        self.assertEqual(first["status"], "processing")
        self.assertEqual(self.rows(Capture)[0].raw_text, "  I think binary uses two symbols.  ")
        self.api("POST", "/turns", {"text": "Something else", "client_message_id": message_id}, 409)
        self.assertEqual(len(self.rows(ConversationTurn)), 1)

    def test_bank_files_automatic_subject_and_topic_carries_forward(self):
        model = Model(router=intents({"action": "bank"}), capture=capture(
            item("Gradient descent", "Gradient descent moves weights downhill on the loss.", ["Machine learning"]),
            topic="Machine learning", subject={"title": "Machine learning", "aliases": ["ML"]}))
        turn = self.send("I'm learning machine learning. Gradient descent moves weights downhill on the loss.", model)
        self.assertEqual(turn["status"], "completed", turn)
        self.assertIn("Gradient descent", turn["reply"])
        self.assertIn("filed under Machine learning", turn["reply"])
        subject = self.rows(Subject)[0]
        self.assertEqual((subject.title, subject.origin), ("Machine learning", "automatic"))
        self.assertIn("ML", subject.aliases)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Conversation, UUID(turn["conversation_id"])).subject_id, subject.id)
        follow = Model(router=intents({"action": "bank"}),
                       capture=capture(item("Backpropagation", "Backpropagation computes gradients layer by layer.")))
        self.send("Backpropagation computes gradients layer by layer.", follow, turn["conversation_id"])
        self.assertEqual(follow.calls[1][1]["context"]["conversation_subject"], "Machine learning")
        memberships = self.rows(SubjectConcept)
        self.assertEqual(len(memberships), 2)
        self.assertEqual({m.origin for m in memberships}, {"automatic"})
        self.assertTrue(all(m.capture_id for m in memberships))

    def test_mixed_bank_and_mcq_keeps_key_private_and_grades_by_key(self):
        model = Model(router=intents({"action": "bank"}, {"action": "practice", "refers_to_context": True, "format": "mcq", "count": 1}),
                      capture=capture(item("Binary", "Binary uses two symbols, 0 and 1.")),
                      mcq={"question": "How many symbols does binary use?", "options": ["One", "Two", "Ten", "Sixteen"],
                           "correct_index": 1, "rationale": "PRIVATE-RATIONALE"},
                      mcq_check={"index": 1})
        turn = self.send("Binary uses two symbols, 0 and 1. Quiz me on this with one multiple-choice question.", model)
        self.assertEqual(turn["status"], "completed", turn)
        self.assertIn("Question 1 of 1", turn["reply"])
        self.assertNotIn("PRIVATE-RATIONALE", json.dumps(turn))
        self.assertNotIn("correct_index", json.dumps(turn))
        self.assertEqual(sorted(turn["active_question"]["options"]), ["One", "Sixteen", "Ten", "Two"])
        question = self.rows(ReviewQuestion)[0]
        letter = "ABCDE"[question.answer_key["correct_index"]]
        self.assertEqual(question.options[question.answer_key["correct_index"]], "Two")
        # The model's factual judgment disagrees; the stored key decides multiple choice.
        answer = Model(answer={"chosen_index": None, "recall": "consistent", "factual": "incorrect", "feedback": "Two symbols."})
        result = self.send(letter, answer, turn["conversation_id"])
        self.assertEqual(answer.count("router"), 0)
        self.assertIn("Correct:", result["reply"])
        self.assertIn("1 of 1 answers correct", result["reply"])
        self.assertIsNone(result["active_question"])
        feedback = json.loads(self.rows(ReviewAttempt)[0].feedback)
        self.assertEqual((feedback["factual"], feedback["factual_basis"], feedback["recall"]), ("correct", "answer_key", "consistent"))
        self.assertIsNotNone(self.rows(ReviewSession)[0].finished_at)

    def test_recall_quotes_saved_words_and_says_when_analogy_is_missing(self):
        text = "Fractions are like slices of a pizza: the denominator is how many slices."
        self.bank("Fractions", text)
        model = Model(router=intents({"action": "recall", "topic": "fractions", "analogy": "cake"}),
                      recall={"reminder": "You pictured fractions as pizza slices.", "holds": ["Equal parts"], "breaks_down": [],
                              "assessment": "accurate", "issue_excerpt": None})
        missing = self.send("Remind me how fractions work using my cake analogy", model)
        self.assertIn("couldn't find a saved analogy mentioning “cake”", missing["reply"])
        self.assertIn(f"“{text}”", missing["reply"])
        model = Model(router=intents({"action": "recall", "topic": "fractions", "analogy": "pizza"}),
                      recall={"reminder": "You pictured fractions as pizza slices.", "holds": [], "breaks_down": ["Slices must be equal"],
                              "assessment": "partly_accurate", "issue_excerpt": "the denominator is how many slices"})
        found = self.send("Remind me of my pizza analogy for fractions", model)
        self.assertNotIn("couldn't find", found["reply"])
        self.assertEqual(model.calls[1][1]["analogy_excerpts"], [text])
        self.assertIn("Your saved explanation is unchanged", found["reply"])
        need = self.rows(LearningNeed)[0]
        self.assertEqual((need.kind, need.evidence, need.user_excerpt), ("misconception", "model_suspected", "the denominator is how many slices"))
        self.assertEqual(len(self.rows(ExplanationRevision)), 1)

    def test_bank_wide_diagnosis_ranks_hedged_explanations_and_tracks_need_history(self):
        self.bank("Binary", "Binary uses two symbols.")
        hedged = "I think attention maybe averages every word equally."
        self.bank("Attention", hedged)
        attention = next(c for c in self.rows(Concept) if c.title == "Attention")

        def diagnose(payload):
            self.assertEqual(payload["candidates"][0]["title"], "Attention")
            return {"findings": [{"concept_id": str(attention.id), "kind": "misconception", "summary": "Attention weights are not equal",
                                  "why": "Weights depend on query-key similarity.", "user_excerpt": "maybe averages every word equally",
                                  "confidence": "medium"}],
                    "question": {"concept_id": str(attention.id), "text": "How does attention decide which words matter?"}, "reason": ""}
        turn = self.send("Pick a gap from anything I've learned", Model(router=intents({"action": "diagnose", "whole_bank": True}), diagnose=diagnose))
        self.assertIn("I looked across all 2 saved concepts", turn["reply"])
        self.assertIn("my suspicion", turn["reply"])
        self.assertEqual(turn["active_question"]["type"], "diagnostic")
        need = self.rows(LearningNeed)[0]
        self.assertEqual((need.evidence, need.status), ("user_uncertain", "exploring"))
        answer = Model(router=intents({"action": "answer"}),
                       diagnostic_answer={"outcome": "difficulty_observed", "feedback": "Attention weights vary by relevance."})
        result = self.send("It averages them I guess", answer, turn["conversation_id"])
        self.assertIsNone(result["active_question"])
        need = self.rows(LearningNeed)[0]
        self.assertEqual((need.evidence, need.status), ("observed_in_answer", "exploring"))
        self.assertEqual(sorted(e.kind for e in self.rows(LearningNeedEvent)), ["answered", "asked", "suspected"])

    def test_period_uses_user_timezone_and_absence_is_not_ignorance(self):
        now = datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc)
        since, until, phrase = period_bounds("last_week", None, "America/Los_Angeles", now)
        self.assertEqual((since.isoformat(), until.isoformat(), phrase),
                         ("2026-10-12T00:00:00-07:00", "2026-10-19T00:00:00-07:00", "last week"))
        since, _, _ = period_bounds("today", None, "Pacific/Auckland", now)
        self.assertEqual(since.isoformat(), "2026-10-21T00:00:00+13:00")
        self.bank("Binary", "Binary uses two symbols.")
        with Session(self.engine) as db, db.begin():
            db.execute(update(ExplanationRevision).values(created_at=datetime.now(timezone.utc) - timedelta(days=10)))
        recent = self.send("Cue cards for what I learned recently", Model(router=intents({"action": "practice", "period": "recent", "format": "cue_card"})))
        self.assertIn("over the past 7 days", recent["reply"])
        self.assertIn("not that you don't know it", recent["reply"])
        wider = self.send("Cue cards from the last two weeks", Model(router=intents({"action": "practice", "period": "last_n_days", "days": 14,
                          "format": "cue_card"}), question={"question": "Explain binary in your own words."}))
        self.assertIn("Here is 1 cue card from everything you've saved over the past 14 days", wider["reply"])

    def test_later_turn_waits_for_earlier_turn(self):
        first = self.submit("Help")
        second = self.submit("Help again", first["conversation_id"])
        self.assertEqual(second["sequence"], 2)
        model = Model(router=intents({"action": "help"}))
        waiting = self.run_turn(second, model)
        self.assertEqual(waiting["status"], "processing")
        self.assertEqual(model.calls, [])
        self.assertEqual(self.run_turn(first, model)["status"], "completed")
        self.assertEqual(self.run_turn(second, model)["status"], "completed")

    def test_failed_intent_keeps_completed_effects_and_retry_does_not_repeat_them(self):
        model = Model(router=intents({"action": "bank"}, {"action": "teach", "topic": "binary"}),
                      capture=capture(item("Binary", "Binary uses two symbols.")),
                      teach=["not json", "still not json", {"content": "Binary is base two.", "summary": "Binary is base two.", "check_question": None}])
        turn = self.send("Binary uses two symbols. Explain binary.", model)
        self.assertEqual(turn["status"], "processing")
        with Session(self.engine) as db, db.begin():
            db.execute(update(WorkItem).where(WorkItem.id == UUID(turn["job_id"])).values(status="failed", attempts=5))
        failed = self.api("GET", f"/turns/{turn['id']}")
        self.assertEqual(failed["status"], "failed")
        self.assertIn("Saved your explanation", failed["reply"])
        self.api("POST", f"/turns/{turn['id']}/retry")
        done = self.run_turn(turn, model)
        self.assertEqual(done["status"], "completed", done)
        self.assertIn("Binary is base two.", done["reply"])
        self.assertEqual((model.count("router"), model.count("capture")), (1, 1))
        self.assertEqual(len(self.rows(ExplanationRevision)), 1)

    def test_adopting_teaching_records_confirmed_suggestion_provenance(self):
        lesson = {"content": "Attention weighs words by relevance.", "summary": "Attention weighs each word by its relevance to the current word.",
                  "check_question": "What decides the weights?"}
        turn = self.send("Explain attention", Model(router=intents({"action": "teach", "topic": "attention"}), teach=lesson))
        self.assertIn("say “save that”", turn["reply"])
        self.assertEqual(self.rows(ExplanationRevision), [])
        adopted = self.send("Yes, save that", Model(router=intents({"action": "adopt"})), turn["conversation_id"])
        revision = self.rows(ExplanationRevision)[0]
        self.assertEqual((revision.origin, revision.body), ("user_confirmed_suggestion", lesson["summary"]))
        self.assertEqual(str(revision.capture_id), adopted["capture_id"])
        suggestion = self.rows(LearningSuggestion)[0]
        self.assertEqual((suggestion.status, suggestion.applied_revision_id), ("adopted", revision.id))
        artifact = self.api("GET", f"/learning-artifacts/{suggestion.artifact_id}")
        self.assertEqual(artifact["output"]["content"], lesson["content"])

    def test_portability_round_trips_turns_and_imports_v1(self):
        self.bank("Gradient descent", "Gradient descent moves downhill.", subjects=["Machine learning"])
        pending = self.submit("Unprocessed message", str(self.rows(Conversation)[0].id))
        with Session(self.engine) as db:
            document = export_bank(db)
        self.assertEqual(document["format"], "membrain.bank.v2")
        self.assertEqual(len(document["tables"]["conversation_turns"]), 2)
        with Session(self.engine) as db:
            report = import_bank(db, document, uuid4(), False)
        copied = UUID(report["id_map"][pending["id"]])
        copied_capture = UUID(report["id_map"][pending["capture_id"]])
        with Session(self.engine) as db:
            self.assertIsNotNone(db.scalar(select(WorkItem).where(WorkItem.dedup_key == f"turn:{copied}")))
            self.assertIsNone(db.scalar(select(WorkItem).where(WorkItem.capture_id == copied_capture)))
        legacy = {"format": "membrain.bank.v1", "tables": {
            name: [{key: value for key, value in row.items() if key not in V2_COLUMNS.get(name, {}) and not
                    (name == "subject_concepts" and key == "created_at")} for row in rows]
            for name, rows in document["tables"].items() if name not in V2_TABLES}}
        with Session(self.engine) as db:
            report = import_bank(db, legacy, uuid4(), False)
        with Session(self.engine) as db:
            subject = db.get(Subject, UUID(report["id_map"][str(self.rows(Subject)[0].id)]))
            self.assertEqual((subject.origin, subject.aliases), ("user", []))
            self.assertEqual(db.scalar(select(func.count()).select_from(ConversationTurn)), 4)


class RouterTests(unittest.TestCase):
    def test_option_letters_and_stop_skip_inference(self):
        active = {"type": "practice", "format": "mcq", "question": "Q", "options": ["a", "b", "c"]}
        self.assertEqual(shortcut("b)", active).intents[0].action, "answer")
        self.assertEqual(shortcut("stop", active).intents[0].action, "stop")
        self.assertIsNone(shortcut("b", None))

    def test_invalid_model_output_never_drops_a_statement(self):
        failing = Model(router="no json here")
        self.assertEqual(route(failing, "I think recursion calls itself.", {}).intents[0].action, "bank")
        self.assertEqual(failing.count("router"), 2)

    def test_guard_drops_inferred_diagnosis_and_adds_missed_bank(self):
        labelled = RouterOutput(intents=[Intent(action="bank"), Intent(action="diagnose")])
        self.assertEqual([i.action for i in guard("Actually, I now think X. I'm not sure about Y.", labelled).intents], ["bank"])
        practice = RouterOutput(intents=[Intent(action="practice", format="mcq")])
        self.assertEqual([i.action for i in guard("I think sorting is O(n log n). Quiz me.", practice).intents], ["bank", "practice"])
        cue = RouterOutput(intents=[Intent(action="practice", period="recent")])
        self.assertEqual([i.action for i in guard("Give me cue cards for things I learned recently", cue).intents], ["practice"])

    def test_placeholder_slot_values_are_absent(self):
        intent = Intent.model_validate({"action": "practice", "format": "none", "count": 0, "style": "", "topic": "it", "analogy": "none"})
        self.assertEqual((intent.format, intent.count, intent.style, intent.topic, intent.analogy), (None, None, None, None, None))
        self.assertTrue(intent.refers_to_context)
        self.assertEqual(Intent.model_validate({"action": "recall", "analogy": ""}).analogy, "")
