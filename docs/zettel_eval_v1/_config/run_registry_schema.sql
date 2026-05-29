-- run_registry_schema.sql
-- Local SQLite registry for eval runs + per-LLM-call telemetry (Sub-5 sweep).
-- Lives at docs/zettel_eval_v1/_data/eval_history.sqlite on operator laptop.
-- Companion to git-tracked JSON snapshots under runs/<run-id>/. The SQLite
-- registry is the queryable INDEX; the JSON snapshots are the human-readable
-- source of truth. Pattern: Simon Willison / Datasette / llm CLI tool.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- One row per zettel_eval_v1 run (run-001-baseline, run-002-claude, ...).
CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,                       -- "001-baseline", "002-claude", ...
    started_at          TEXT NOT NULL,                          -- ISO 8601 UTC
    finished_at         TEXT,                                   -- ISO 8601 UTC; NULL while in-flight
    git_sha             TEXT NOT NULL,
    git_dirty           INTEGER NOT NULL DEFAULT 0,             -- bool
    harness_version     TEXT NOT NULL,                          -- semver of zettel_eval_v1
    python_version      TEXT NOT NULL,
    hostname            TEXT,
    dataset_id          TEXT NOT NULL,                          -- "eval-v1.0", etc.
    dataset_sha256      TEXT NOT NULL,                          -- content-addressed manifest sha
    config_sha256       TEXT NOT NULL,                          -- sha of resolved config tuple
    rubric_sha256       TEXT NOT NULL,
    failure_taxonomy_sha256  TEXT,
    notes               TEXT
);

-- One row per LLM call inside a run (atomic_facts call, judge call, NLI call, ...).
-- Schema aligns with OpenTelemetry GenAI Semantic Conventions (stable since 2025).
CREATE TABLE IF NOT EXISTS llm_calls (
    call_id                 TEXT PRIMARY KEY,
    run_id                  TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    parent_call_id          TEXT REFERENCES llm_calls(call_id) ON DELETE SET NULL,
    workspace_zettel_id     TEXT,                               -- which of the 47 zettels this call serves
    source_type             TEXT,                               -- github | youtube | ...
    operation               TEXT NOT NULL,                      -- "extract" | "judge" | "nli" | "summarize" | "canary"
    provider                TEXT NOT NULL,                      -- "google" | "anthropic" | "huggingface"
    request_model           TEXT NOT NULL,                      -- what we asked for
    response_model          TEXT,                               -- what they served; KEY drift signal
    request_id              TEXT,                               -- provider's request id
    finish_reasons          TEXT,                               -- JSON array
    input_tokens            INTEGER,
    output_tokens           INTEGER,
    cached_tokens           INTEGER DEFAULT 0,
    thoughts_tokens         INTEGER DEFAULT 0,
    unit_price_in_usd_per_mtok   REAL,
    unit_price_out_usd_per_mtok  REAL,
    cost_usd                REAL,
    latency_ms              INTEGER,
    ttft_ms                 INTEGER,
    started_at              TEXT NOT NULL,
    finished_at             TEXT NOT NULL,
    cache_hit               INTEGER NOT NULL DEFAULT 0,
    cache_key_sha256        TEXT,
    error                   TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_run ON llm_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_source ON llm_calls(source_type);
CREATE INDEX IF NOT EXISTS idx_llm_calls_op ON llm_calls(operation);
CREATE INDEX IF NOT EXISTS idx_llm_calls_response_model ON llm_calls(response_model);

-- One row per zettel x run with the composite + per-axis result.
CREATE TABLE IF NOT EXISTS zettel_results (
    run_id                  TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    workspace_zettel_id     TEXT NOT NULL,
    source_type             TEXT NOT NULL,
    composite               REAL,
    composite_uncapped      REAL,
    rubric_total            REAL,
    finesure_faithfulness   REAL,
    finesure_completeness   REAL,
    finesure_conciseness    REAL,
    g_eval_coherence        INTEGER,
    g_eval_fluency          INTEGER,
    nli_mean_entailment     REAL,
    nli_max_contradict      REAL,
    nli_contradicted_count  INTEGER,
    faithfulness_combined   REAL,
    hallucination_cap_hit   INTEGER DEFAULT 0,
    failure_class_vector    TEXT,                               -- JSON {EntE: int, PredE: int, ...}
    top_error_class_1       TEXT,
    top_error_class_2       TEXT,
    top_error_class_3       TEXT,
    PRIMARY KEY (run_id, workspace_zettel_id)
);
CREATE INDEX IF NOT EXISTS idx_zettel_results_src ON zettel_results(source_type);

-- Canary set drift hashes (Sub-4 + Sub-5).
CREATE TABLE IF NOT EXISTS canary_hashes (
    canary_run_id           TEXT NOT NULL,                      -- "2026-05-28T03:00Z" or any cadence id
    canary_item_id          TEXT NOT NULL,                      -- canary_001 ... canary_007
    judge                   TEXT NOT NULL,                      -- "primary" | "secondary"
    request_model           TEXT NOT NULL,
    response_model          TEXT,
    response_sha256         TEXT NOT NULL,
    started_at              TEXT NOT NULL,
    PRIMARY KEY (canary_run_id, canary_item_id, judge)
);

-- Annotation responses (round-1, round-2-retest, pairwise).
CREATE TABLE IF NOT EXISTS annotations (
    annotation_id           TEXT PRIMARY KEY,
    annotator               TEXT NOT NULL,                      -- operator handle
    round                   TEXT NOT NULL,                      -- "1" | "retest" | "pairwise"
    workspace_zettel_id     TEXT,                               -- NULL for pairwise rows; pair_left/right used instead
    pair_left_zettel_id     TEXT,
    pair_right_zettel_id    TEXT,
    pair_preference         TEXT,                               -- "left" | "right" | "tie"
    faithfulness_1_to_5     INTEGER,
    coverage_1_to_5         INTEGER,
    conciseness_1_to_5      INTEGER,
    coherence_1_to_5        INTEGER,
    comment                 TEXT,
    annotation_started_at   TEXT,
    annotation_finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_annot_round ON annotations(round);
CREATE INDEX IF NOT EXISTS idx_annot_zettel ON annotations(workspace_zettel_id);
