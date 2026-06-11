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
