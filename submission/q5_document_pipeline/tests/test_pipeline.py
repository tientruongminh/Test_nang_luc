from __future__ import annotations

import unittest
from pathlib import Path

from q5_document_pipeline.src.pipeline import DocumentPipeline, JobRunner, ObjectStore, connect


SCHEMA = Path(__file__).resolve().parents[1] / "schema.sql"


class DocumentPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = connect(SCHEMA)
        self.store = ObjectStore()
        self.pipeline = DocumentPipeline(self.db, self.store)
        self.runner = JobRunner(self.db)

    def test_duplicate_same_content_different_filename_is_not_new_version(self) -> None:
        first = self.pipeline.upload("a.pdf", b"PDF page one", "customer-contract")
        second = self.pipeline.upload("renamed.pdf", b"PDF page one", "customer-contract")
        self.assertEqual(first.document_version_id, second.document_version_id)
        self.assertEqual(first.stable_object_key, second.stable_object_key)
        self.assertNotIn("renamed.pdf", second.stable_object_key)
        count = self.db.execute("SELECT COUNT(*) AS c FROM document_version").fetchone()["c"]
        self.assertEqual(count, 1)

    def test_modified_pdf_creates_new_document_version_and_downstream_jobs(self) -> None:
        first = self.pipeline.upload("a.pdf", b"PDF page one", "customer-contract")
        second = self.pipeline.upload("a.pdf", b"PDF page one MODIFIED", "customer-contract")
        self.assertEqual(first.document_id, second.document_id)
        self.assertEqual((first.version_no, second.version_no), (1, 2))
        jobs = self.db.execute(
            "SELECT job_type FROM job WHERE document_version_id = ? ORDER BY job_type",
            (second.document_version_id,),
        ).fetchall()
        self.assertEqual([row["job_type"] for row in jobs], ["analyze", "chunk", "dedup", "embed", "extract"])
        outbox = self.db.execute("SELECT COUNT(*) AS c FROM outbox WHERE aggregate_id = ?", (second.document_version_id,)).fetchone()
        self.assertEqual(outbox["c"], 1)

    def test_crash_after_object_write_can_retry_without_duplicate_object(self) -> None:
        with self.assertRaises(RuntimeError):
            self.pipeline.upload("a.pdf", b"PDF stable bytes", "policy", crash_after_object_write=True)
        self.assertEqual(len(self.store), 2)
        self.assertTrue(any(key.startswith("texts/") for key in self.store))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM document_version").fetchone()[0], 0)
        retry = self.pipeline.upload("b.pdf", b"PDF stable bytes", "policy")
        self.assertEqual(len(self.store), 2)
        self.assertEqual(retry.version_no, 1)

    def test_empty_or_poison_document_does_not_retry_forever(self) -> None:
        result = self.pipeline.upload("empty.pdf", b"   ", "empty-doc")
        self.assertEqual(result.status, "FAILED_NO_RETRY")
        self.assertIsNotNone(result.document_version_id)
        repeated = self.pipeline.upload("renamed.pdf", b"   ", "empty-doc")
        self.assertEqual(repeated.document_version_id, result.document_version_id)
        job = self.db.execute(
            "SELECT status, attempt_count, task_identity FROM job WHERE document_version_id = ?",
            (result.document_version_id,),
        ).fetchone()
        self.assertEqual((job["status"], job["attempt_count"]), ("FAILED_NO_RETRY", 1))
        self.assertTrue(job["task_identity"].startswith("task:extract:pipeline-v1:"))
        count = self.db.execute("SELECT COUNT(*) AS c FROM job").fetchone()["c"]
        self.assertEqual(count, 1)

    def test_same_bytes_under_different_document_keys_have_distinct_versions(self) -> None:
        first = self.pipeline.upload("shared.pdf", b"Same PDF bytes", "policy-a")
        second = self.pipeline.upload("shared.pdf", b"Same PDF bytes", "policy-b")
        self.assertNotEqual(first.document_id, second.document_id)
        self.assertNotEqual(first.document_version_id, second.document_version_id)
        self.assertEqual(first.stable_object_key, second.stable_object_key)
        self.assertEqual(len(self.store), 2)

    def test_job_task_identity_is_stable_across_retryable_failure(self) -> None:
        upload = self.pipeline.upload("a.pdf", b"PDF content for embedding", "embedding-doc")
        original = self.db.execute(
            "SELECT task_identity FROM job WHERE document_version_id = ? AND job_type = 'embed'",
            (upload.document_version_id,),
        ).fetchone()["task_identity"]
        with self.assertRaisesRegex(RuntimeError, "simulated_embed_failure"):
            self.runner.run(upload.document_version_id, "embed", fail=True)
        retry_identity = self.runner.run(upload.document_version_id, "embed")
        job = self.db.execute(
            "SELECT status, attempt_count, task_identity FROM job WHERE document_version_id = ? AND job_type = 'embed'",
            (upload.document_version_id,),
        ).fetchone()
        self.assertEqual(retry_identity, original)
        self.assertEqual(job["task_identity"], original)
        self.assertEqual((job["status"], job["attempt_count"]), ("SUCCEEDED", 2))

    def test_failure_after_version_insert_rolls_back_without_orphan_rows(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "simulated_crash_after_version_insert"):
            self.pipeline.upload(
                "a.pdf",
                b"PDF transaction rollback evidence",
                "rollback-doc",
                crash_after_version_insert=True,
            )
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM document_version").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM job").fetchone()[0], 0)
        retry = self.pipeline.upload("a.pdf", b"PDF transaction rollback evidence", "rollback-doc")
        self.assertEqual(retry.version_no, 1)

    def test_outbox_dispatch_failure_leaves_event_pending_for_retry(self) -> None:
        upload = self.pipeline.upload("a.pdf", b"PDF ready event", "outbox-doc")
        outbox = self.db.execute(
            "SELECT id, status FROM outbox WHERE aggregate_id = ?",
            (upload.document_version_id,),
        ).fetchone()
        with self.assertRaisesRegex(RuntimeError, "simulated_outbox_dispatch_failure"):
            self.runner.dispatch_outbox(outbox["id"], fail=True)
        pending = self.db.execute("SELECT status FROM outbox WHERE id = ?", (outbox["id"],)).fetchone()["status"]
        self.assertEqual(pending, "PENDING")
        self.runner.dispatch_outbox(outbox["id"])
        sent = self.db.execute("SELECT status FROM outbox WHERE id = ?", (outbox["id"],)).fetchone()["status"]
        self.assertEqual(sent, "SENT")


if __name__ == "__main__":
    unittest.main()
