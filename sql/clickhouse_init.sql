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

CREATE TABLE IF NOT EXISTS web_osint.taxonomy_versions
(
    taxonomy_version UInt32,
    created_at DateTime64(3, 'UTC'),
    created_by String,
    change_summary String,
    migration_notes String,
    parent_version Nullable(UInt32),
    artifact_id String
)
ENGINE = MergeTree
ORDER BY taxonomy_version;

CREATE TABLE IF NOT EXISTS web_osint.label_concepts
(
    label_id String,
    scheme LowCardinality(String),
    pref_label String,
    alt_labels Array(String),
    description String,
    broader_ids Array(String),
    narrower_ids Array(String),
    related_ids Array(String),
    status LowCardinality(String),
    replaced_by String,
    taxonomy_version UInt32,
    created_at DateTime64(3, 'UTC'),
    created_by String,
    metadata_json String
)
ENGINE = MergeTree
ORDER BY (scheme, label_id, taxonomy_version);

CREATE TABLE IF NOT EXISTS web_osint.semantic_annotations
(
    annotation_id String,
    evidence_id String,
    artifact_id String,
    chunk_id String,
    target_type LowCardinality(String),
    target_id String,
    selector_type LowCardinality(String),
    selector_json String,
    annotation_family LowCardinality(String),
    label_id String,
    label_scheme LowCardinality(String),
    taxonomy_version UInt32,
    value_json String,
    confidence Float32,
    score_components_json String,
    status LowCardinality(String),
    span_text String,
    produced_by_activity_id String,
    producer_name LowCardinality(String),
    producer_version String,
    input_hash String,
    created_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (annotation_family, label_id, evidence_id, created_at, annotation_id);

CREATE TABLE IF NOT EXISTS web_osint.entity_mentions
(
    mention_id String,
    evidence_id String,
    artifact_id String,
    chunk_id String,
    mention_text String,
    normalized_text String,
    entity_type LowCardinality(String),
    selector_json String,
    candidate_entity_ids Array(String),
    resolved_entity_id String,
    resolver_name LowCardinality(String),
    resolver_version String,
    confidence Float32,
    created_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (entity_type, normalized_text, evidence_id, mention_id);

CREATE TABLE IF NOT EXISTS web_osint.canonical_entities
(
    entity_id String,
    entity_type LowCardinality(String),
    canonical_name String,
    aliases Array(String),
    external_ids_json String,
    first_seen_at DateTime64(3, 'UTC'),
    last_seen_at DateTime64(3, 'UTC'),
    status LowCardinality(String),
    replaced_by String,
    metadata_json String
)
ENGINE = MergeTree
ORDER BY (entity_type, entity_id);

CREATE TABLE IF NOT EXISTS web_osint.claim_assertions
(
    claim_id String,
    evidence_id String,
    artifact_id String,
    chunk_id String,
    claim_text String,
    normalized_claim String,
    claim_type LowCardinality(String),
    speaker_entity_id String,
    subject_entity_id String,
    predicate LowCardinality(String),
    object_json String,
    polarity LowCardinality(String),
    modality LowCardinality(String),
    time_scope_json String,
    selector_json String,
    check_worthiness Float32,
    confidence Float32,
    extractor_name LowCardinality(String),
    extractor_version String,
    created_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (claim_type, subject_entity_id, created_at, claim_id);

CREATE TABLE IF NOT EXISTS web_osint.relation_assertions
(
    relation_id String,
    evidence_id String,
    artifact_id String,
    subject_entity_id String,
    relation_type LowCardinality(String),
    object_entity_id String,
    object_literal String,
    properties_json String,
    selector_json String,
    confidence Float32,
    status LowCardinality(String),
    extractor_name LowCardinality(String),
    extractor_version String,
    created_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (relation_type, subject_entity_id, object_entity_id, created_at, relation_id);

CREATE TABLE IF NOT EXISTS web_osint.benchmark_facts
(
    fact_id String,
    evidence_id String,
    table_snapshot_id String,
    row_id String,
    cell_id String,
    source_url String,
    source_domain LowCardinality(String),
    model_entity_id String,
    model_name String,
    benchmark_entity_id String,
    benchmark_name String,
    metric_name String,
    metric_canonical_key LowCardinality(String),
    value_float Nullable(Float64),
    value_text String,
    raw_value String,
    unit LowCardinality(String),
    rank Nullable(UInt32),
    direction LowCardinality(String),
    captured_at DateTime64(3, 'UTC'),
    extracted_at DateTime64(3, 'UTC'),
    selector_json String,
    extraction_method LowCardinality(String),
    confidence Float32,
    validation_flags Array(String),
    extractor_name LowCardinality(String),
    extractor_version String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(captured_at)
ORDER BY (benchmark_name, metric_canonical_key, model_entity_id, captured_at, fact_id);

CREATE TABLE IF NOT EXISTS web_osint.release_signals
(
    signal_id String,
    evidence_id String,
    source_url String,
    source_kind LowCardinality(String),
    product_entity_id String,
    model_entity_id String,
    org_entity_id String,
    signal_type LowCardinality(String),
    signal_text String,
    selector_json String,
    claimed_release_date Nullable(Date),
    observed_at DateTime64(3, 'UTC'),
    confidence Float32,
    novelty_score Float32,
    impact_score Float32,
    status LowCardinality(String),
    created_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(observed_at)
ORDER BY (signal_type, product_entity_id, observed_at, signal_id);

CREATE TABLE IF NOT EXISTS web_osint.research_signals
(
    signal_id String,
    signal_type LowCardinality(String),
    primary_entity_id String,
    topic_label_id String,
    evidence_ids Array(String),
    annotation_ids Array(String),
    signal_summary String,
    rationale String,
    novelty_score Float32,
    uncertainty_score Float32,
    impact_score Float32,
    source_strength_score Float32,
    user_interest_score Float32,
    created_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (signal_type, primary_entity_id, created_at, signal_id);

CREATE TABLE IF NOT EXISTS web_osint.research_questions
(
    question_id String,
    question_text String,
    question_type LowCardinality(String),
    trigger_signal_ids Array(String),
    seed_evidence_ids Array(String),
    seed_entity_ids Array(String),
    seed_label_ids Array(String),
    rationale String,
    priority Float32,
    expected_value Float32,
    uncertainty Float32,
    status LowCardinality(String),
    generated_by_activity_id String,
    generator_name LowCardinality(String),
    generator_version String,
    created_at DateTime64(3, 'UTC'),
    updated_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (status, priority, created_at, question_id);

CREATE TABLE IF NOT EXISTS web_osint.autonomous_tasks
(
    task_id String,
    question_id String,
    task_type LowCardinality(String),
    task_payload_json String,
    seed_evidence_ids Array(String),
    seed_entity_ids Array(String),
    priority Float32,
    budget_json String,
    dedupe_key String,
    ttl_until Nullable(DateTime64(3, 'UTC')),
    status LowCardinality(String),
    rationale String,
    created_at DateTime64(3, 'UTC'),
    updated_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (status, priority, created_at, task_id);

CREATE TABLE IF NOT EXISTS web_osint.wiki_page_versions
(
    page_id String,
    page_type LowCardinality(String),
    object_id String,
    title String,
    content_artifact_id String,
    manifest_artifact_id String,
    source_evidence_ids Array(String),
    source_annotation_ids Array(String),
    generator_name LowCardinality(String),
    generator_version String,
    content_hash String,
    confidence_summary_json String,
    generated_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(generated_at)
ORDER BY (page_type, object_id, generated_at, page_id);

CREATE TABLE IF NOT EXISTS web_osint.label_eval_results
(
    eval_run_id String,
    labeler_name LowCardinality(String),
    labeler_version String,
    taxonomy_version UInt32,
    annotation_family LowCardinality(String),
    label_id String,
    precision Float32,
    recall Float32,
    f1 Float32,
    support UInt32,
    confusion_json String,
    created_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (labeler_name, labeler_version, annotation_family, label_id);

CREATE TABLE IF NOT EXISTS web_osint.ops_canary_runs
(
    run_id String,
    status LowCardinality(String),
    started_at DateTime64(3, 'UTC'),
    finished_at DateTime64(3, 'UTC'),
    duration_ms UInt64,
    canary_token String,
    source_project LowCardinality(String),
    collector_run_id String,
    input_path String,
    input_sha256 String,
    evidence_ids Array(String),
    expected_chunks UInt32,
    observed_chunks UInt32,
    embedded_chunks UInt32,
    qdrant_points_found UInt32,
    dashboard_exact_rank Nullable(UInt32),
    dashboard_semantic_rank Nullable(UInt32),
    hydration_ok UInt8,
    result_path String,
    errors Array(String),
    details_json String,
    created_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(started_at)
ORDER BY (started_at, run_id);

CREATE TABLE IF NOT EXISTS web_osint.ops_canary_steps
(
    run_id String,
    step_name LowCardinality(String),
    ok UInt8,
    duration_ms UInt64,
    detail_json String,
    error_class LowCardinality(String),
    error_message String,
    created_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (run_id, created_at, step_name);
