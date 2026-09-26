from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


FLOW = ("extract", "dedup", "chunk", "embed", "analyze")


@dataclass(frozen=True)
class UploadResult:
    document_id: int
    document_version_id: int
    version_no: int
    status: str
    stable_object_key: str


def sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def connect(schema_path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(Path(schema_path).read_text(encoding="utf-8"))
    return db


class ObjectStore(dict[str, bytes]):
    def put_if_absent(self, key: str, data: bytes) -> None:
        self.setdefault(key, data)


class DocumentPipeline:
    def __init__(self, db: sqlite3.Connection, store: ObjectStore) -> None:
        self.db = db
        self.store = store

    @staticmethod
    def stable_object_key(file_fingerprint: str) -> str:
        return f"objects/{file_fingerprint}.pdf"

    @staticmethod
    def extract_text(pdf_bytes: bytes) -> str:
        text = pdf_bytes.decode("utf-8", errors="ignore").strip()
        if not text or "POISON" in text:
            raise ValueError("empty_or_poison_document")
        return " ".join(text.split())

    def upload(
        self,
        filename: str,
        pdf_bytes: bytes,
        document_key: str,
        *,
        crash_after_object_write: bool = False,
        crash_after_version_insert: bool = False,
    ) -> UploadResult:
        file_fingerprint = sha256(pdf_bytes)
        object_key = self.stable_object_key(file_fingerprint)
        self.store.put_if_absent(object_key, pdf_bytes)
        try:
            extracted_text = self.extract_text(pdf_bytes)
        except ValueError:
            extracted_text = None
        if extracted_text is not None:
            text_key = f"texts/{sha256(extracted_text)}.txt"
            self.store.put_if_absent(text_key, extracted_text.encode("utf-8"))
        if crash_after_object_write:
            raise RuntimeError("simulated_crash_after_object_write")

        with self.db:
            document_id = self._get_or_create_document(document_key)
            existing = self.db.execute(
                "SELECT id, version_no, status FROM document_version WHERE document_id = ? AND file_fingerprint = ?",
                (document_id, file_fingerprint),
            ).fetchone()
            if existing:
                return UploadResult(document_id, existing["id"], existing["version_no"], existing["status"], object_key)

            next_version = self._next_version(document_id)
            document_fingerprint = sha256(f"{document_key}:{file_fingerprint}")
            if extracted_text is None:
                version_id = self._create_version(
                    document_id, next_version, file_fingerprint, document_fingerprint,
                    object_key, "FAILED_NO_RETRY", "empty_or_poison_document",
                )
                if crash_after_version_insert:
                    raise RuntimeError("simulated_crash_after_version_insert")
                self.db.execute(
                    """
                    INSERT INTO job(document_version_id, job_type, task_identity, status, attempt_count)
                    VALUES (?, 'extract', ?, 'FAILED_NO_RETRY', 1)
                    """,
                    (version_id, self.task_identity(document_fingerprint, "extract")),
                )
                return UploadResult(document_id, version_id, next_version, "FAILED_NO_RETRY", object_key)

            version_id = self._create_version(
                document_id, next_version, file_fingerprint, document_fingerprint,
                object_key, "READY", None,
            )
            if crash_after_version_insert:
                raise RuntimeError("simulated_crash_after_version_insert")
            self._create_artifacts(version_id, extracted_text)
            self._create_jobs_and_outbox(version_id, filename, document_fingerprint)
            return UploadResult(document_id, version_id, next_version, "READY", object_key)

    def _create_version(
        self, document_id: int, version_no: int, file_fingerprint: str,
        document_fingerprint: str, object_key: str, status: str, failure_reason: str | None,
    ) -> int:
        cursor = self.db.execute(
            """
            INSERT INTO document_version(
                document_id, version_no, file_fingerprint, document_fingerprint,
                stable_object_key, status, failure_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (document_id, version_no, file_fingerprint, document_fingerprint, object_key, status, failure_reason),
        )
        return int(cursor.lastrowid)

    def _get_or_create_document(self, document_key: str) -> int:
        self.db.execute("INSERT OR IGNORE INTO document(document_key) VALUES (?)", (document_key,))
        row = self.db.execute("SELECT id FROM document WHERE document_key = ?", (document_key,)).fetchone()
        return int(row["id"])

    def _next_version(self, document_id: int) -> int:
        row = self.db.execute(
            "SELECT COALESCE(MAX(version_no), 0) + 1 AS next_version FROM document_version WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        return int(row["next_version"])

    def _create_artifacts(self, version_id: int, extracted_text: str) -> None:
        extracted_fp = sha256(extracted_text)
        chunk_text = extracted_text[:500]
        chunk_fp = sha256(f"0:{chunk_text}")
        embedding_identity = f"embedding:text-embedding-3-small:v1:{chunk_fp}"
        analysis_identity = f"analysis:prompt-v1:gpt-4.1-mini:config-v1:{chunk_fp}"
        artifacts = [
            ("extracted_text", extracted_fp, f"extract:{extracted_fp}"),
            ("chunk", chunk_fp, f"chunk:0:{chunk_fp}"),
            ("embedding", sha256(embedding_identity), embedding_identity),
            ("analysis", sha256(analysis_identity), analysis_identity),
        ]
        self.db.executemany(
            "INSERT INTO artifact(document_version_id, artifact_type, fingerprint, identity) VALUES (?, ?, ?, ?)",
            [(version_id, kind, fingerprint, identity) for kind, fingerprint, identity in artifacts],
        )

    @staticmethod
    def task_identity(document_fingerprint: str, job_type: str) -> str:
        return f"task:{job_type}:pipeline-v1:{document_fingerprint}"

    def _create_jobs_and_outbox(self, version_id: int, filename: str, document_fingerprint: str) -> None:
        self.db.executemany(
            """
            INSERT INTO job(document_version_id, job_type, task_identity, status, attempt_count)
            VALUES (?, ?, ?, 'PENDING', 0)
            """,
            [(version_id, step, self.task_identity(document_fingerprint, step)) for step in FLOW],
        )
        payload = json.dumps({"document_version_id": version_id, "source_filename": filename}, sort_keys=True)
        self.db.execute(
            """
            INSERT INTO outbox(aggregate_type, aggregate_id, event_type, payload)
            VALUES ('document_version', ?, 'DOCUMENT_VERSION_READY', ?)
            """,
            (version_id, payload),
        )


class JobRunner:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def run(self, document_version_id: int, job_type: str, *, fail: bool = False) -> str:
        job = self.db.execute(
            """
            SELECT id, task_identity, status, attempt_count
            FROM job
            WHERE document_version_id = ? AND job_type = ?
            """,
            (document_version_id, job_type),
        ).fetchone()
        if job is None:
            raise LookupError(f"missing_job:{job_type}")
        if job["status"] == "SUCCEEDED":
            return job["task_identity"]
        next_attempt = int(job["attempt_count"]) + 1
        status = "FAILED_RETRYABLE" if fail else "SUCCEEDED"
        self.db.execute(
            "UPDATE job SET status = ?, attempt_count = ? WHERE id = ?",
            (status, next_attempt, job["id"]),
        )
        self.db.commit()
        if fail:
            raise RuntimeError(f"simulated_{job_type}_failure")
        return job["task_identity"]

    def dispatch_outbox(self, outbox_id: int, *, fail: bool = False) -> None:
        with self.db:
            row = self.db.execute("SELECT status FROM outbox WHERE id = ?", (outbox_id,)).fetchone()
            if row is None:
                raise LookupError("missing_outbox_event")
            if fail:
                raise RuntimeError("simulated_outbox_dispatch_failure")
            self.db.execute("UPDATE outbox SET status = 'SENT' WHERE id = ?", (outbox_id,))
