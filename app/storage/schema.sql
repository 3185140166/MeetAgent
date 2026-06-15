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

-- ========== 第五阶段：对话持久化 ==========

CREATE TABLE IF NOT EXISTS chat_sessions (
  session_id TEXT PRIMARY KEY,
  user_id    TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role       TEXT NOT NULL,   -- user / assistant
  content    TEXT NOT NULL,
  tool_calls TEXT,            -- JSON 数组，仅 assistant 消息有值
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id);

-- ========== Session Memory：会话摘要 ==========

CREATE TABLE IF NOT EXISTS session_summaries (
  session_id TEXT PRIMARY KEY,
  user_id TEXT,
  summary TEXT NOT NULL,
  message_count INTEGER DEFAULT 0,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id)
);

-- ========== Long-term Memory：跨会话长期记忆 ==========

CREATE TABLE IF NOT EXISTS memories (
  memory_id TEXT PRIMARY KEY,
  user_id TEXT,
  scope TEXT NOT NULL,          -- user / project / meeting_topic
  memory_type TEXT NOT NULL,    -- preference / fact / task / topic / decision / risk
  subject TEXT,
  content TEXT NOT NULL,
  status TEXT DEFAULT 'active', -- active / deprecated / deleted / expired
  trust_score REAL DEFAULT 0.7,
  source_type TEXT,             -- chat / meeting / extracted_meeting / manual
  source_id TEXT,               -- session_id / note_id / other id
  evidence TEXT,                -- JSON
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_memories_user_status ON memories(user_id, status);
CREATE INDEX IF NOT EXISTS idx_memories_scope_type ON memories(scope, memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_subject ON memories(subject);
CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  memory_id UNINDEXED,
  user_id UNINDEXED,
  subject,
  content
);

-- ========== Agent Task：复杂任务 / 长任务 ==========

CREATE TABLE IF NOT EXISTS agent_tasks (
  task_id TEXT PRIMARY KEY,
  session_id TEXT,
  user_id TEXT,
  question TEXT NOT NULL,
  task_type TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  plan TEXT,
  final_answer TEXT,
  error TEXT,
  current_step_index INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  started_at TEXT,
  finished_at TEXT,
  heartbeat_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_task_steps (
  step_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  step_index INTEGER NOT NULL,
  title TEXT,
  description TEXT,
  tool_name TEXT,
  tool_args TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  result TEXT,
  error TEXT,
  started_at TEXT,
  finished_at TEXT,
  FOREIGN KEY(task_id) REFERENCES agent_tasks(task_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_user ON agent_tasks(user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_agent_task_steps_task ON agent_task_steps(task_id, step_index);
