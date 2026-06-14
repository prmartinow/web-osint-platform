CREATE DATABASE IF NOT EXISTS web_osint;

CREATE TABLE IF NOT EXISTS web_osint.evidence_events
(
    event_id String,
    schema_version LowCardinality(String),
    collector_run_id String,
    source_project LowCardinality(String),
    capture_method LowCardinality(String),
    source_kind LowCardinality(String),
    evidence_id String,
    canonical_url String,
    author_handle String,
    domain String,
    title String,
    text String,
    topics Array(String),
    entities Array(String),
    links Array(String),
    has_media UInt8,
    has_ocr UInt8,
    posted_at Nullable(DateTime64(3, 'UTC')),
    captured_at DateTime64(3, 'UTC'),
    ingested_at DateTime64(3, 'UTC') DEFAULT now64(3),
    raw_json String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(captured_at)
ORDER BY (source_project, source_kind, captured_at, evidence_id);

CREATE TABLE IF NOT EXISTS web_osint.evidence_latest
(
    evidence_id String,
    source_kind LowCardinality(String),
    canonical_url String,
    author_handle String,
    domain String,
    title String,
    text_best String,
    topics Array(String),
    entities Array(String),
    first_seen_at DateTime64(3, 'UTC'),
    last_seen_at DateTime64(3, 'UTC'),
    updated_at DateTime64(3, 'UTC') DEFAULT now64(3),
    raw_json String
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (source_kind, evidence_id);

CREATE TABLE IF NOT EXISTS web_osint.entities
(
    entity_id String,
    entity_name String,
    entity_type LowCardinality(String),
    evidence_id String,
    source_kind LowCardinality(String),
    source_project LowCardinality(String),
    confidence Float32,
    extracted_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(extracted_at)
ORDER BY (entity_type, entity_name, extracted_at, evidence_id);

CREATE TABLE IF NOT EXISTS web_osint.claims
(
    claim_id String,
    claim_text String,
    evidence_id String,
    source_kind LowCardinality(String),
    source_project LowCardinality(String),
    polarity LowCardinality(String),
    confidence Float32,
    topics Array(String),
    entities Array(String),
    extracted_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(extracted_at)
ORDER BY (source_project, extracted_at, claim_id);

CREATE TABLE IF NOT EXISTS web_osint.topics_labels
(
    label_id String,
    evidence_id String,
    source_project LowCardinality(String),
    label_name String,
    label_type LowCardinality(String),
    confidence Float32,
    assigned_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(assigned_at)
ORDER BY (label_type, label_name, assigned_at, evidence_id);

CREATE TABLE IF NOT EXISTS web_osint.source_activity_daily
(
    day Date,
    source_kind LowCardinality(String),
    source_project LowCardinality(String),
    author_handle String,
    domain String,
    topic String,
    evidence_count UInt64,
    media_count UInt64,
    ocr_count UInt64,
    updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(day)
ORDER BY (day, source_project, source_kind, author_handle, domain, topic);

CREATE TABLE IF NOT EXISTS web_osint.model_timeline_events
(
    timeline_event_id String,
    event_kind LowCardinality(String),
    model_name String,
    provider_name String,
    category LowCardinality(String),
    event_title String,
    event_summary String,
    event_date Date,
    evidence_ids Array(String),
    confidence Float32,
    updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (event_date, provider_name, model_name, timeline_event_id);

CREATE TABLE IF NOT EXISTS web_osint.collector_runs
(
    collector_run_id String,
    source_project LowCardinality(String),
    capture_method LowCardinality(String),
    started_at DateTime64(3, 'UTC'),
    finished_at Nullable(DateTime64(3, 'UTC')),
    status LowCardinality(String),
    records_seen UInt64,
    records_emitted UInt64,
    challenge UInt8,
    partial UInt8,
    notes String,
    updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (source_project, capture_method, started_at, collector_run_id);
