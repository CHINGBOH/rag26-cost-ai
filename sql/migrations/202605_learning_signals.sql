-- #94 学习模块深度演进 — 信号表 + 雷达表 + 改进事件表
-- Idempotent: IF NOT EXISTS everywhere

-- ──────────────────────────────────────────────────────
-- 外部技术雷达（I5：External Signal Port）
-- ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tech_radar (
  id            BIGSERIAL PRIMARY KEY,
  source        TEXT NOT NULL,
  external_id   TEXT,
  title         TEXT NOT NULL,
  summary       TEXT,
  url           TEXT,
  published_at  TIMESTAMPTZ,
  fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  score         INT NOT NULL DEFAULT 0,
  tags          TEXT[],
  status        TEXT NOT NULL DEFAULT 'new'
                  CHECK (status IN ('new', 'reviewing', 'adopted', 'dismissed')),
  reviewer      TEXT,
  decision_note TEXT,
  related_issue INT,
  CONSTRAINT tech_radar_source_extid_unique UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_tech_radar_fetched ON tech_radar(fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_tech_radar_status  ON tech_radar(status);
CREATE INDEX IF NOT EXISTS idx_tech_radar_source  ON tech_radar(source);

-- ──────────────────────────────────────────────────────
-- 改进事件（I2 Feedback Reachability + I4 双轨）
-- 每条事件必须显式标 source 和 affected_route，否则违反不变量
-- ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS improvement_events (
  id                  BIGSERIAL PRIMARY KEY,
  source              TEXT NOT NULL
                        CHECK (source IN ('auto', 'human', 'external')),
  actor               TEXT NOT NULL,
  source_feedback_id  BIGINT REFERENCES rag_feedback(id) ON DELETE SET NULL,
  source_radar_id     BIGINT REFERENCES tech_radar(id) ON DELETE SET NULL,
  source_run_id       TEXT,
  affected_route      TEXT NOT NULL
                        CHECK (affected_route IN
                          ('R1_navigator_dict', 'R2_path_default',
                           'R3_planner_examples', 'R4_rerank_weights',
                           'R5_tool_priority')),
  patch_payload       JSONB NOT NULL,
  rationale           TEXT,
  applied_at          TIMESTAMPTZ,
  reverted_at         TIMESTAMPTZ,
  reversible_by       TEXT NOT NULL DEFAULT 'rollback_event',
  ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_improve_ts        ON improvement_events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_improve_route     ON improvement_events(affected_route);
CREATE INDEX IF NOT EXISTS idx_improve_source    ON improvement_events(source);
CREATE INDEX IF NOT EXISTS idx_improve_feedback  ON improvement_events(source_feedback_id);

-- ──────────────────────────────────────────────────────
-- 合约违规（S8 结构化）
-- ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS signal_contract_violation (
  id              BIGSERIAL PRIMARY KEY,
  run_id          TEXT,
  session_id      TEXT,
  contract_name   TEXT NOT NULL,
  violation_code  TEXT NOT NULL,
  payload         JSONB,
  ts              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_violation_ts       ON signal_contract_violation(ts DESC);
CREATE INDEX IF NOT EXISTS idx_violation_contract ON signal_contract_violation(contract_name);
CREATE INDEX IF NOT EXISTS idx_violation_code     ON signal_contract_violation(violation_code);

-- ──────────────────────────────────────────────────────
-- 用户重问检测（S12，I2 关键支撑）
-- ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS signal_repeat_question (
  id             BIGSERIAL PRIMARY KEY,
  session_id     TEXT NOT NULL,
  original_turn  INT NOT NULL,
  repeat_turn    INT NOT NULL,
  similarity     REAL NOT NULL,
  ts             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_repeat_ts ON signal_repeat_question(ts DESC);

-- ──────────────────────────────────────────────────────
-- 拓扑边遍历时间戳（I1 + I6 自检根据）
-- 每次代码经过某条边都更新一次（upsert）
-- ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS topology_edge_log (
  edge_id            TEXT PRIMARY KEY,    -- e.g. 'query->analyzer'
  from_node          TEXT NOT NULL,
  to_node            TEXT NOT NULL,
  last_traversed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  traversal_count    BIGINT NOT NULL DEFAULT 0
);

-- 预填规范的 12 节点图（形态可变，但这些边的语义必须存在）
INSERT INTO topology_edge_log(edge_id, from_node, to_node, last_traversed_at, traversal_count)
VALUES
  ('query->analyzer',          'query',          'analyzer',     NOW(), 0),
  ('analyzer->navigator',      'analyzer',       'navigator',    NOW(), 0),
  ('navigator->retriever',     'navigator',      'retriever',    NOW(), 0),
  ('retriever->tool',          'retriever',      'tool',         NOW(), 0),
  ('tool->verifier',           'tool',           'verifier',     NOW(), 0),
  ('verifier->synthesize',     'verifier',       'synthesize',   NOW(), 0),
  ('synthesize->user',         'synthesize',     'user',         NOW(), 0),
  ('user->feedback',           'user',           'feedback',     NOW(), 0),
  ('feedback->learner',        'feedback',       'learner',      NOW(), 0),
  ('learner->architect',       'learner',        'architect',    NOW(), 0),
  ('architect->navigator_dict','architect',      'navigator_dict', NOW(), 0),
  ('architect->path_default',  'architect',      'path_default', NOW(), 0),
  ('architect->planner_few',   'architect',      'planner_few',  NOW(), 0),
  ('architect->rerank_w',      'architect',      'rerank_w',     NOW(), 0),
  ('architect->tool_priority', 'architect',      'tool_priority',NOW(), 0),
  ('external->architect',      'external_signal','architect',    NOW(), 0)
ON CONFLICT (edge_id) DO NOTHING;
