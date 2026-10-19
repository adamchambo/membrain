"""Behavior tests against an explicitly disposable, migrated PostgreSQL database."""

import asyncio
import json
import os
import unittest
import threading
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.ai.embeddings import configured_profile, embed
from app.captures.ai_schemas import CaptureOutput
from app.captures.formatter import CaptureAI
from app.captures.formatter import get_formatter
from app.captures.ai_schemas import FormatCandidate
from app.captures.models import AIProposal, Capture
from app.database import get_db
from app.discovery.service import vector_search
from app.errors import Unavailable
from app.jobs.models import WorkItem
from app.jobs.worker import claim, process_capture, run_one
from app.knowledge.models import Concept, ConceptEmbedding, ExplanationRevision, Resource
from app.main import app
from app.models import Base
from app.review.ai_schemas import FeedbackOutput


def output(*items, topic=None, questions=None, answered_id=None):
    return {"schema_version": "capture.v1", "topic_title": topic,
            "understandings": list(items), "clarifications": questions or [],
            "answered_clarification_id": str(answered_id) if answered_id else None}


def understanding(title, explanation, source=None, concept_id=None):
    return {"title": title, "explanation_text": explanation, "source_excerpts": [source or explanation],
            "uncertainty": [], "existing_concept_id": str(concept_id) if concept_id else None}


class ScriptedClient:
    model_key = "test-chat"

    def __init__(self, response):
        self.response = response
        self.messages = []

    def generate(self, system_prompt, user_input):
        self.messages.append((system_prompt, json.loads(user_input)))
        return json.dumps(self.response)


async def asgi_call(method, url, body=None, headers=None):
    path, _, query = url.partition("?")
    sent = []
    raw = json.dumps(body).encode() if body is not None else b""

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    async def send(message):
        sent.append(message)

    await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
               "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": query.encode(),
               "root_path": "", "headers": [(b"content-type", b"application/json")] + [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()],
               "server": ("test", 80), "client": ("test", 1234)}, receive, send)
    status = next(item["status"] for item in sent if item["type"] == "http.response.start")
    content = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    return status, json.loads(content) if content else None


class OutputTests(unittest.TestCase):
    def test_duplicate_targets_and_false_verification_are_invalid(self):
        item = understanding("Binary", "I use two symbols")
        with self.assertRaises(ValueError):
            CaptureOutput.model_validate(output(item, item))
        with self.assertRaises(ValueError):
            FeedbackOutput(recall="consistent", feedback="Good", correctness="verified")

    def test_embedding_prefix_dimension_and_finite_values(self):
        with patch.dict(os.environ, {"ORACLE_EMBEDDINGS_URL": "http://test/embeddings", "ORACLE_EMBEDDING_REVISION": "weights-v1", "ORACLE_EMBEDDING_DIMENSIONS": "3"}):
            profile = configured_profile()
            with patch("app.ai.embeddings.post_json", return_value={"data": [{"embedding": [3, 4, 0]}]}) as transport:
                self.assertEqual(embed("my explanation", profile), [0.6, 0.8, 0.0])
                self.assertEqual(transport.call_args.args[1]["input"], "search_document: my explanation")
                embed("my question", profile, query=True)
                self.assertEqual(transport.call_args.args[1]["input"], "search_query: my question")
            for vector in ([0, 0, 0], [1, 2], [float("nan"), 0, 1], [True, 0, 1]):
                with patch("app.ai.embeddings.post_json", return_value={"data": [{"embedding": vector}]}):
                    with self.assertRaises(Unavailable):
                        embed("text", profile)
            self.assertNotEqual(profile.key, profile.model_copy(update={"revision": "weights-v2"}).key)


class IngestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.getenv("ORACLE_TEST_DATABASE_URL")
        if not url:
            raise unittest.SkipTest("Set ORACLE_TEST_DATABASE_URL or use tests/run_postgres.py")
        if not (make_url(url).database or "").startswith("oracle_test_"):
            raise RuntimeError("Refusing tests outside a database named oracle_test_*")
        cls.engine = create_engine(url)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        # The database-name guard above is required before any fixture writes.
        names = ", ".join(self.engine.dialect.identifier_preparer.quote(name) for name in Base.metadata.tables)
        with self.engine.begin() as db:
            db.execute(text(f"TRUNCATE {names} CASCADE"))
        self.config_directory = tempfile.TemporaryDirectory()
        self.settings = patch.dict(os.environ, {"ORACLE_CONFIG_FILE": self.config_directory.name + "/config.json", "ORACLE_CHAT_COMPLETIONS_URL": "", "ORACLE_CHAT_MODEL": "",
            "ORACLE_EMBEDDINGS_URL": "http://test/embeddings", "ORACLE_EMBEDDING_REVISION": "test-weights-v1",
            "ORACLE_EMBEDDING_DIMENSIONS": "3"})
        self.settings.start()

        def session_dependency():
            with Session(self.engine, expire_on_commit=False) as db:
                yield db
        app.dependency_overrides[get_db] = session_dependency

    def tearDown(self):
        app.dependency_overrides.clear()
        self.settings.stop()
        self.config_directory.cleanup()

    def api(self, method, path, body=None, expected=200):
        status, result = asyncio.run(asgi_call(method, "/api/v1" + path, body))
        self.assertEqual(status, expected, result)
        return result

    def save(self, raw, conversation=None, **values):
        return self.api("POST", "/captures/ingest", {"raw_text": raw, "conversation_id": conversation, **values}, 201)

    def process(self, receipt, result):
        client = ScriptedClient(result)
        self.assertTrue(run_one(self.engine, job_id=UUID(receipt["processing_job_id"]), processor=CaptureAI(client)))
        return client

    def rows(self, model):
        with Session(self.engine) as db:
            return db.scalars(select(model)).all()

    def test_topic_is_saved_verbatim_without_invented_understanding(self):
        raw = "  I'm learning about computers.  "
        receipt = self.save(raw)
        self.assertTrue(receipt["saved"])
        self.assertEqual(self.rows(Capture)[0].raw_text, raw)
        self.process(receipt, output(topic="Computers"))
        self.assertEqual(self.rows(Concept), [])
        history = self.api("GET", f"/conversations/{receipt['conversation_id']}")
        self.assertEqual(history["title"], "Computers")
        self.assertEqual(history["captures"][0]["status"], "processed")

    def test_multiconcept_auto_bank_and_idempotent_request_and_worker(self):
        request_id = str(uuid4())
        receipt = self.save("Binary uses two symbols. Python is a programming language.", request_id=request_id)
        repeat = self.save("Binary uses two symbols. Python is a programming language.", request_id=request_id)
        self.assertEqual(receipt, repeat)
        self.process(receipt, output(understanding("Binary", "Binary uses two symbols."),
                                     understanding("Python", "Python is a programming language.")))
        self.assertEqual(len(self.rows(ExplanationRevision)), 2)
        proposal = self.rows(AIProposal)[0]
        self.assertEqual(proposal.application_mode, "automatic")
        self.assertIsNone(proposal.reviewed_at)
        self.assertEqual(proposal.prompt_version, "capture.v1")
        self.assertFalse(run_one(self.engine, job_id=UUID(receipt["processing_job_id"])))
        self.api("POST", "/captures/ingest", {"raw_text": "different", "request_id": request_id}, 409)

    def test_invalid_source_rolls_back_every_derived_record(self):
        receipt = self.save("I think binary uses two symbols.")
        self.process(receipt, output(understanding("Binary", "I think binary uses two symbols."),
                                     understanding("Memory", "Memory uses transistors.", source="not in the message")))
        self.assertEqual(self.rows(Concept), [])
        self.assertEqual(self.rows(AIProposal), [])
        self.assertEqual(self.rows(Capture)[0].status, "pending")
        self.assertEqual(self.rows(WorkItem)[0].status, "pending")

    def test_missing_model_does_not_lose_message_or_exhaust_retries(self):
        receipt = self.save("Learning computers")
        run_one(self.engine, job_id=UUID(receipt["processing_job_id"]))
        job = self.rows(WorkItem)[0]
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.attempts, 0)
        self.assertIn("not configured", job.last_error)
        self.assertEqual(len(self.rows(Capture)), 1)

    def test_unknown_concept_ids_cannot_create_partial_records(self):
        receipt = self.save("Binary uses two symbols.")
        self.process(receipt, output(understanding("Binary", "Binary uses two symbols.", concept_id=uuid4())))
        self.assertEqual(self.rows(ExplanationRevision), [])
        self.assertEqual(self.rows(Concept), [])

    def test_undo_before_processing_cancels_work(self):
        receipt = self.save("I am learning computers.")
        self.api("POST", f"/captures/{receipt['capture_id']}/undo", expected=204)
        self.assertFalse(run_one(self.engine, job_id=UUID(receipt["processing_job_id"])))
        self.assertEqual(self.rows(Capture)[0].status, "archived")
        self.assertEqual(self.rows(Concept), [])

    def test_compatible_http_transport_end_to_end(self):
        seen = []

        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append((self.path, data))
                if self.path == "/embeddings":
                    body = {"data": [{"embedding": [3, 4, 0]}]}
                else:
                    result = output(understanding("Binary", "Binary uses two symbols."))
                    body = {"choices": [{"message": {"content": json.dumps(result)}}]}
                encoded = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with patch.dict(os.environ, {"ORACLE_CHAT_COMPLETIONS_URL": base + "/chat", "ORACLE_CHAT_MODEL": "test-chat",
                                        "ORACLE_EMBEDDINGS_URL": base + "/embeddings"}):
                receipt = self.save("Binary uses two symbols.")
                self.assertEqual(len(self.rows(Capture)), 1)
                self.assertEqual(seen, [])  # The save request never waits for inference.
                run_one(self.engine, job_id=UUID(receipt["processing_job_id"]))
                embedding_job = next(x for x in self.rows(WorkItem) if x.kind == "embedding")
                run_one(self.engine, job_id=embedding_job.id)
                result = self.api("GET", "/search?q=two+symbols&mode=semantic")
                self.assertEqual(len(result["items"]), 1)
                self.assertEqual(result["pending_explanations"], 0)
                self.assertEqual(seen[1][1]["input"], "search_document: Binary uses two symbols.")
                self.assertEqual(seen[2][1]["input"], "search_query: two symbols")
                self.assertEqual(self.rows(WorkItem)[0].status, "succeeded")
                related = self.api("GET", f"/concepts/{result['items'][0]['id']}/related")
                self.assertTrue(related["semantic_available"])
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_resources_are_saved_even_without_a_model(self):
        receipt = self.save("Bookmark https://example.org/computers")
        self.assertEqual(len(receipt["resource_ids"]), 1)
        self.process(receipt, output())
        self.assertEqual(len(self.rows(Resource)), 1)
        self.assertEqual(self.rows(Concept), [])

    def test_followup_updates_existing_understanding_and_can_be_undone(self):
        first = self.save("I think binary uses two symbols.")
        self.process(first, output(understanding("Binary", "I think binary uses two symbols."),
            questions=[{"question": "Which symbols?", "source_excerpt": "two symbols"}]))
        concept = self.rows(Concept)[0]
        question = next(x for x in self.rows(AIProposal) if x.kind == "clarification")
        second = self.save("Those symbols are zero and one.", first["conversation_id"])
        client = self.process(second, output(understanding("Binary", "I think binary uses zero and one.",
            source="Those symbols are zero and one.", concept_id=concept.id), answered_id=question.id))
        self.assertEqual(client.messages[0][1]["context"]["existing_concepts"][0]["id"], str(concept.id))
        self.assertEqual(client.messages[0][1]["context"]["pending_clarifications"][0]["id"], str(question.id))
        self.api("POST", f"/captures/{first['capture_id']}/undo", expected=409)
        self.api("POST", f"/captures/{second['capture_id']}/undo", expected=204)
        detail = self.api("GET", f"/concepts/{concept.id}")
        self.assertEqual(detail["latest_revision"]["body"], "I think binary uses two symbols.")
        self.assertEqual(len(self.rows(ExplanationRevision)), 2)
        self.assertIsNotNone(next(x for x in self.rows(ExplanationRevision) if x.revision_number == 2).retracted_at)
        self.assertEqual(next(x for x in self.rows(AIProposal) if x.id == question.id).status, "pending")

    def test_failed_work_can_be_retried_without_duplicate_banking(self):
        receipt = self.save("Binary uses two symbols.")
        job_id = UUID(receipt["processing_job_id"])
        invalid = output(understanding("Binary", "Binary uses two symbols.", source="invented source"))
        for _ in range(5):
            self.process(receipt, invalid)
            with Session(self.engine) as db, db.begin():
                db.get(WorkItem, job_id).available_at = datetime.now(timezone.utc)
        self.assertEqual(self.api("GET", f"/jobs/{job_id}")["status"], "failed")
        self.api("POST", f"/jobs/{job_id}/retry")
        self.process(receipt, output(understanding("Binary", "Binary uses two symbols.")))
        self.assertEqual(len(self.rows(ExplanationRevision)), 1)

    def test_original_format_and_manual_bank_routes_still_work(self):
        class LegacyFormatter:
            model_key = "test-legacy"

            def format(self, raw_text):
                return FormatCandidate(candidate_title="Binary", explanation_text=raw_text)

        app.dependency_overrides[get_formatter] = lambda: LegacyFormatter()
        capture = self.api("POST", "/captures", {"raw_text": "Binary uses two symbols."}, 201)
        proposal = self.api("POST", f"/captures/{capture['id']}/format", expected=201)
        banked = self.api("POST", f"/captures/{capture['id']}/bank", {"new_title": "Binary",
            "explanation_text": proposal["payload"]["explanation_text"], "formatting_proposal_id": proposal["id"]}, 201)
        self.assertEqual(banked["origin"], "ai_formatted_user_input")
        self.assertEqual(banked["embedding_status"], "pending")

    def test_expired_worker_cannot_apply_a_stale_result(self):
        receipt = self.save("Binary uses two symbols.")
        job_id = UUID(receipt["processing_job_id"])
        _, old_token, _ = claim(self.engine, job_id)
        with Session(self.engine) as db, db.begin():
            db.get(WorkItem, job_id).lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        _, new_token, _ = claim(self.engine, job_id)
        processor = CaptureAI(ScriptedClient(output(understanding("Binary", "Binary uses two symbols."))))
        process_capture(self.engine, job_id, old_token, processor)
        self.assertEqual(self.rows(Concept), [])
        process_capture(self.engine, job_id, new_token, processor)
        self.assertEqual(len(self.rows(Concept)), 1)

    def test_vectors_filter_profile_latest_revision_and_undone_explanations(self):
        receipt = self.save("Binary uses two symbols.")
        self.process(receipt, output(understanding("Binary", "Binary uses two symbols.")))
        concept = self.rows(Concept)[0]
        jobs = [x for x in self.rows(WorkItem) if x.kind == "embedding"]
        run_one(self.engine, job_id=jobs[0].id, embedder=lambda text, profile: [1, 0, 0])
        profile = configured_profile()
        with Session(self.engine) as db:
            self.assertEqual(len(vector_search(db, [1, 0, 0], profile.key, 10)), 1)
            self.assertEqual(vector_search(db, [1, 0, 0], "different-profile", 10), [])
        self.api("POST", f"/concepts/{concept.id}/revisions", {"explanation_text": "I changed my understanding."}, 201)
        with Session(self.engine) as db:
            self.assertEqual(vector_search(db, [1, 0, 0], profile.key, 10), [])
        with patch("app.discovery.service.embed", return_value=[1, 0, 0]):
            result = self.api("GET", "/search?q=binary&mode=hybrid")
            self.assertEqual(result["pending_explanations"], 1)

    def test_review_persists_question_answer_and_retryable_feedback(self):
        receipt = self.save("Binary uses two symbols.")
        self.process(receipt, output(understanding("Binary", "Binary uses two symbols.")))
        concept = self.rows(Concept)[0]
        session = self.api("POST", "/review-sessions", {"concept_ids": [str(concept.id)]}, 201)
        question = self.api("POST", f"/review-sessions/{session['id']}/next")
        repeated = self.api("POST", f"/review-sessions/{session['id']}/next")
        self.assertEqual(question["id"], repeated["id"])
        body = {"question_id": question["id"], "response": "Two symbols"}
        attempt = self.api("POST", f"/review-sessions/{session['id']}/attempts", body, 201)
        retry = self.api("POST", f"/review-sessions/{session['id']}/attempts", body, 201)
        self.assertEqual(attempt["id"], retry["id"])
        self.assertIsNone(attempt["feedback"])
        assessor = lambda snapshot, prompt, response: {"recall": "partial", "feedback": "You recalled the symbols.", "correctness": "not_verified"}
        run_one(self.engine, job_id=UUID(attempt["feedback_job_id"]), assessor=assessor)
        finished = self.api("GET", f"/review-attempts/{attempt['id']}")
        self.assertEqual(finished["feedback"]["correctness"], "not_verified")
        self.assertEqual(len(self.rows(ExplanationRevision)), 1)


if __name__ == "__main__":
    unittest.main()
