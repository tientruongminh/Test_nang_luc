PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS document (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS document_version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES document(id),
    version_no INTEGER NOT NULL,
    file_fingerprint TEXT NOT NULL,
    document_fingerprint TEXT NOT NULL,
    stable_object_key TEXT NOT NULL,
    status TEXT NOT NULL,
    failure_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id, version_no),
    UNIQUE(document_id, file_fingerprint)
);

CREATE TABLE IF NOT EXISTS artifact (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_version_id INTEGER NOT NULL REFERENCES document_version(id),
    artifact_type TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    identity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'READY',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_version_id, artifact_type, identity)
);

CREATE TABLE IF NOT EXISTS job (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_version_id INTEGER NOT NULL REFERENCES document_version(id),
    job_type TEXT NOT NULL,
    task_identity TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_version_id, job_type),
    UNIQUE(task_identity)
);

CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aggregate_type TEXT NOT NULL,
    aggregate_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
