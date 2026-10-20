"""Capability journeys use only disposable data and injected task providers."""

import base64
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import select, func
from sqlalchemy.orm import Session

import test_ingestion as support
from app.ai.embeddings import Profile
from app.config import config_path, read_config
from app.jobs.models import WorkItem
from app.jobs.worker import run_one
from app.knowledge.models import Concept, ConceptEmbedding, ExplanationRevision
from app.learning.models import LearningArtifact, LearningSuggestion
from app.learning.schemas import LearningOutput
from app.learning.service import validate_evidence
from app.portability.service import export_bank, import_bank
from app.setup.models import BankSettings
from app.setup.profiles import start_migration, migration_status, decide_migration
from app.setup.schemas import SetupConfiguration
from app.setup.service import save_settings, safe_settings


class CapabilityTests(unittest.TestCase):
    setUpClass = classmethod(support.IngestionTests.setUpClass.__func__)
    tearDownClass = classmethod(support.IngestionTests.tearDownClass.__func__)
    setUp = support.IngestionTests.setUp
    tearDown = support.IngestionTests.tearDown
    api = support.IngestionTests.api
    save = support.IngestionTests.save
    process = support.IngestionTests.process
    rows = support.IngestionTests.rows

    def concept(self, text="Binary uses two symbols."):
        receipt = self.save(text)
        self.process(receipt, support.output(support.understanding("Binary", text)))
        return self.rows(Concept)[-1]

    def test_configuration_is_private_env_precedence_and_local_setup(self):
        settings = SetupConfiguration.model_validate({"chat": {"url": "http://localhost:11434/v1/chat/completions", "model": "local", "api_key": "synthetic-secret"}})
        result = save_settings(settings)
        self.assertNotIn("synthetic-secret", json.dumps(result))
        self.assertEqual(config_path().stat().st_mode & 0o777, 0o600)
        self.assertEqual(read_config()["settings"]["ORACLE_CHAT_MODEL"], "local")
        with patch.dict(os.environ, {"ORACLE_CHAT_MODEL": "environment"}):
            self.assertEqual(safe_settings()["chat"]["model"], "environment")
        self.api("PUT", "/setup", {})
        self.api("GET", "/setup")

    def test_archive_and_restore_preserve_explanations_and_search(self):
        concept = self.concept()
        self.api("PATCH", f"/concepts/{concept.id}", {"archived": True, "title": "Binary notation"})
        self.assertEqual(self.api("GET", "/concepts")["items"], [])
        self.assertEqual(len(self.api("GET", "/concepts?include_archived=true")["items"]), 1)
        self.assertEqual(len(self.rows(ExplanationRevision)), 1)
        result = self.api("PATCH", f"/concepts/{concept.id}", {"archived": False})
        self.assertEqual(result["title"], "Binary notation")
        self.assertEqual(len(self.api("GET", "/conversations")["items"]), 1)

    def test_source_import_is_versioned_citable_and_not_understanding(self):
        resource = self.api("POST", "/resources", {"kind": "article", "uri": "https://example.com/source"}, 201)
        payload = {"media_type": "text/html", "content_base64": base64.b64encode(b"<h1>Binary</h1><script>bad()</script><p>Two symbols represent digits.</p>").decode()}
        receipt = self.api("POST", f"/resources/{resource['id']}/content", payload, 202)
        repeat = self.api("POST", f"/resources/{resource['id']}/content", payload, 202)
        self.assertEqual(receipt, repeat)
        run_one(self.engine, job_id=UUID(receipt["job_id"]))
        content = self.api("GET", f"/resources/{resource['id']}/chunks")
        self.assertEqual(content["status"], "ready")
        self.assertNotIn("bad()", content["items"][0]["text"])
        self.assertIn("Two symbols", content["items"][0]["text"])
        self.assertEqual(self.rows(ExplanationRevision), [])
        self.assertEqual(content["items"][0]["end"], len(content["items"][0]["text"]))

    def test_subject_scope_quiz_history_and_reflection(self):
        concept = self.concept()
        subject = self.api("POST", "/subjects", {"title": "Computing"}, 201)
        child = self.api("POST", "/subjects", {"title": "Binary", "parent_id": subject["id"]}, 201)
        self.api("PUT", f"/subjects/{child['id']}/concepts/{concept.id}")
        self.assertEqual(self.api("GET", f"/subjects/{subject['id']}/scope")["concept_ids"], [str(concept.id)])
        session = self.api("POST", "/review-sessions", {"subject_id": subject["id"], "mode": "quiz"}, 201)
        question = self.api("POST", f"/review-sessions/{session['id']}/next")
        self.assertIn("example", question["prompt"])
        self.api("POST", f"/review-sessions/{session['id']}/attempts", {"question_id": question["id"], "response": "I recall two symbols."}, 201)
        history = self.api("GET", f"/review-sessions/{session['id']}")
        self.assertEqual(len(history["attempts"]), 1)
        reflection = self.api("GET", f"/reflection?subject_id={subject['id']}")
        self.assertEqual(reflection["reviewed_concept_ids"], [str(concept.id)])
        self.assertEqual(reflection["mastery"], "not_inferred")

    def test_learning_output_is_separate_and_adoption_creates_provenance(self):
        concept = self.concept()
        task = self.api("POST", "/learning-tasks", {"kind": "suggestions", "concept_ids": [str(concept.id)]}, 202)
        result = {"content": "A possible clarification.", "citations": [], "optional_questions": [], "uncertainty": ["No external source checked"],
                  "verification": "not_verified", "suggestions": [{"kind": "correction", "concept_id": str(concept.id),
                      "explanation_text": "I understand binary as a base-two notation.", "rationale": "Clarify notation", "evidence": "uncertain"}]}
        with patch("app.learning.service.get_chat_client", return_value=support.ScriptedClient(result)):
            run_one(self.engine, job_id=UUID(task["job_id"]))
        self.assertEqual(len(self.rows(ExplanationRevision)), 1)
        artifact = self.api("GET", f"/learning-artifacts/{task['artifact_id']}")
        suggestion = artifact["suggestions"][0]
        decision = self.api("POST", f"/learning-suggestions/{suggestion['id']}/decision", {"action": "adopt", "message": "Yes, save this clarification."})
        self.assertEqual(decision["status"], "adopted")
        revisions = self.rows(ExplanationRevision)
        self.assertEqual(len(revisions), 2)
        saved = next(r for r in revisions if r.revision_number == 2)
        self.assertEqual(saved.origin, "user_confirmed_suggestion")
        self.assertEqual(str(saved.suggestion_id), suggestion["id"])
        with Session(self.engine) as db:
            document = export_bank(db)
        with Session(self.engine) as db:
            imported = import_bank(db, document, uuid4(), False)
        with Session(self.engine) as db:
            copied = db.get(ExplanationRevision, UUID(imported["id_map"][str(saved.id)]))
            self.assertEqual(copied.suggestion_id, UUID(imported["id_map"][str(saved.suggestion_id)]))
            self.assertEqual(db.get(LearningSuggestion, copied.suggestion_id).applied_revision_id, copied.id)

    def test_hallucinated_source_quotes_are_rejected(self):
        identifier = uuid4()
        result = LearningOutput.model_validate({"content": "Comparison", "verification": "sources_compared",
            "citations": [{"chunk_id": identifier, "quote": "an invented quote"}]})
        from app.errors import Unavailable
        with self.assertRaises(Unavailable):
            validate_evidence(result, {"context": {"concepts": [], "source_chunks": [{"id": identifier, "text": "Actual source."}]}})

    def test_profile_migration_blocks_early_cutover_and_keeps_search_profile(self):
        self.concept()
        target = Profile(model="another-embedding", revision="v2", dimensions=2, document_prefix="", query_prefix="")
        with Session(self.engine, expire_on_commit=False) as db:
            migration = start_migration(db, target)
        self.assertEqual(migration["missing_explanations"], 1)
        from app.errors import Conflict
        with Session(self.engine) as db, self.assertRaises(Conflict):
            decide_migration(db, migration["id"], "cutover")
        with Session(self.engine) as db:
            job = db.scalar(select(WorkItem).where(WorkItem.kind == "profile_migration"))
        run_one(self.engine, job_id=job.id)
        with Session(self.engine) as db:
            target_job = db.scalar(select(WorkItem).where(WorkItem.kind == "embedding", WorkItem.profile_key == target.key))
            self.assertNotEqual(db.get(BankSettings, "default").active_profile_key, target.key)
        run_one(self.engine, job_id=target_job.id, embedder=lambda text, profile: [1.0, 0.0])
        with Session(self.engine) as db:
            result = decide_migration(db, migration["id"], "cutover")
            self.assertEqual(result["status"], "completed")
        with Session(self.engine) as db:
            self.assertEqual(db.get(BankSettings, "default").active_profile_key, target.key)

    def test_portability_preview_reference_mapping_and_retry(self):
        concept = self.concept()
        with Session(self.engine) as db:
            document = export_bank(db)
        self.assertNotIn("work_items", document["tables"])
        self.assertNotIn("embedding_profiles", document["tables"])
        request_id = uuid4()
        with Session(self.engine) as db:
            preview = import_bank(db, document, request_id)
            self.assertFalse(preview["writes"])
        with Session(self.engine) as db:
            result = import_bank(db, document, request_id, False)
        with Session(self.engine) as db:
            repeat = import_bank(db, document, request_id, False)
            self.assertEqual(result, repeat)
            self.assertEqual(db.scalar(select(func.count()).select_from(Concept)), 2)
            new_concept = UUID(result["id_map"][str(concept.id)])
            revision = db.scalar(select(ExplanationRevision).where(ExplanationRevision.concept_id == new_concept))
            self.assertIsNotNone(revision.capture_id)
            self.assertNotEqual(revision.capture_id, self.rows(ExplanationRevision)[0].capture_id)

    def test_map_distinguishes_confirmed_links_and_display_layout(self):
        concept = self.concept()
        result = self.api("POST", "/concept-map", {"concept_ids": [str(concept.id)], "layout": "circle", "include_similarity": False})
        self.assertEqual(result["nodes"][0]["label"], "Binary")
        self.assertEqual(result["confirmed_edges"], [])
        self.assertEqual(result["layout"]["method"], "circle")

    def test_deletion_rejects_active_and_referenced_records(self):
        concept = self.concept()
        self.api("DELETE", f"/concepts/{concept.id}", expected=409)
        self.api("PATCH", f"/concepts/{concept.id}", {"archived": True})
        self.api("DELETE", f"/concepts/{concept.id}", expected=409)
        self.assertEqual(len(self.rows(Concept)), 1)

    def test_unreferenced_resource_cleanup_requires_archive(self):
        resource = self.api("POST", "/resources", {"kind": "site", "uri": "https://example.com/unused"}, 201)
        self.api("DELETE", f"/resources/{resource['id']}", expected=409)
        self.api("PATCH", f"/resources/{resource['id']}", {"archived": True})
        self.api("DELETE", f"/resources/{resource['id']}", expected=204)
        self.api("GET", f"/resources/{resource['id']}", expected=404)

    def test_local_export_and_import_preview_accept_no_credentials(self):
        self.concept()
        document = self.api("GET", "/bank/export")
        result = self.api("POST", "/bank/import", {
            "request_id": str(uuid4()), "document": document, "preview": True})
        self.assertTrue(result["valid"])
        self.assertFalse(result["writes"])
        self.assertEqual(len(self.rows(Concept)), 1)

    def test_cancelled_migration_keeps_active_profile_and_cancels_target_work(self):
        self.concept()
        target = Profile(model="cancelled-profile", revision="v1", dimensions=2)
        with Session(self.engine) as db:
            migration = start_migration(db, target)
        with Session(self.engine) as db:
            coordinator = db.scalar(select(WorkItem).where(WorkItem.kind == "profile_migration"))
        run_one(self.engine, job_id=coordinator.id)
        with Session(self.engine) as db:
            decide_migration(db, migration["id"], "cancel")
        with Session(self.engine) as db:
            self.assertNotEqual(db.get(BankSettings, "default").active_profile_key, target.key)
            target_work = db.scalars(select(WorkItem).where(WorkItem.profile_key == target.key)).all()
            self.assertTrue(target_work)
            self.assertTrue(all(job.status == "cancelled" for job in target_work))
