CREATE TABLE IF NOT EXISTS meetings (
  note_id TEXT PRIMARY KEY,
  user_id TEXT,
  title TEXT,
  create_time TEXT,
  duration_minutes REAL,
  language TEXT,
  audio_id TEXT,
  audio_path TEXT,
  raw_json_path TEXT,
  asr_result_length INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT PRIMARY KEY,
  note_id TEXT NOT NULL,
  user_id TEXT,
  chunk_index INTEGER NOT NULL,
  speaker TEXT,
  text TEXT NOT NULL,
  search_text TEXT NOT NULL,
  char_count INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(note_id) REFERENCES meetings(note_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
  chunk_id UNINDEXED,
  note_id UNINDEXED,
  user_id UNINDEXED,
  search_text
);

-- ========== 第二阶段：结构化会议记忆 ==========

CREATE TABLE IF NOT EXISTS meeting_summaries (
  note_id TEXT PRIMARY KEY,
  summary TEXT,
  topics TEXT,        -- JSON 数组
  key_points TEXT,    -- JSON 数组
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(note_id) REFERENCES meetings(note_id)
);

CREATE TABLE IF NOT EXISTS action_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  note_id TEXT NOT NULL,
  content TEXT NOT NULL,
  owner TEXT,
  due TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(note_id) REFERENCES meetings(note_id)
);

CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  note_id TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(note_id) REFERENCES meetings(note_id)
);

CREATE TABLE IF NOT EXISTS risks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  note_id TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(note_id) REFERENCES meetings(note_id)
);

CREATE TABLE IF NOT EXISTS entities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  note_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,   -- person / project / customer / product
  name TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(note_id) REFERENCES meetings(note_id)
);

CREATE INDEX IF NOT EXISTS idx_action_items_note ON action_items(note_id);
CREATE INDEX IF NOT EXISTS idx_decisions_note ON decisions(note_id);
CREATE INDEX IF NOT EXISTS idx_risks_note ON risks(note_id);
CREATE INDEX IF NOT EXISTS idx_entities_note ON entities(note_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type, name);
