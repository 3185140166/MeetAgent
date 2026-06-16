# -*- coding: utf-8 -*-
from dotenv import load_dotenv
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

APIFUSION_API_URL: str = os.environ.get("APIFUSION_API_URL", "https://apifusion.aispeech.com.cn/v1/chat/completions")
APIFUSION_API_KEY: str = os.environ.get("APIFUSION_API_KEY", "")
APIFUSION_MODEL: str = os.environ.get("APIFUSION_MODEL", "gpt-5.5")
DB_PATH: str = os.environ.get("DB_PATH", "data/meetagent.db")
TOP_K: int = int(os.environ.get("TOP_K", "8"))
ENABLE_HYBRID_SEARCH: bool = os.environ.get("ENABLE_HYBRID_SEARCH", "false").lower() in ("1", "true", "yes", "on")

# 第二阶段：结构化抽取
EXTRACT_WINDOW_CHARS: int = int(os.environ.get("EXTRACT_WINDOW_CHARS", "6000"))
EXTRACT_CONCURRENCY: int = int(os.environ.get("EXTRACT_CONCURRENCY", "5"))

# 第三阶段：向量检索
EMBED_PROVIDER: str = os.environ.get("EMBED_PROVIDER", "local")          # local | dashscope
EMBED_LOCAL_MODEL: str = os.environ.get("EMBED_LOCAL_MODEL", "BAAI/bge-small-zh-v1.5")
EMBED_MODEL_DIR: str = os.environ.get("EMBED_MODEL_DIR", "models")       # 本地模型缓存目录
EMBED_DIM: int = int(os.environ.get("EMBED_DIM", "512"))
DASHSCOPE_BASE_URL: str = os.environ.get("DASHSCOPE_BASE_URL", "")
DASHSCOPE_API_KEY: str = os.environ.get("DASHSCOPE_API_KEY", "")
DASHSCOPE_EMBEDDING_MODEL: str = os.environ.get("DASHSCOPE_EMBEDDING_MODEL", "text-embedding-v4")

# 联网搜索
TAVILY_API_KEY: str = os.environ.get("TAVILY_API_KEY", "")
TAVILY_API_URL: str = os.environ.get("TAVILY_API_URL", "https://api.tavily.com/search")
WEB_SEARCH_MAX_RESULTS: int = int(os.environ.get("WEB_SEARCH_MAX_RESULTS", "5"))
WEB_SEARCH_DEFAULT_TOPIC: str = os.environ.get("WEB_SEARCH_DEFAULT_TOPIC", "general")
WEB_SEARCH_DEFAULT_TIME_RANGE: str = os.environ.get("WEB_SEARCH_DEFAULT_TIME_RANGE", "")

# Session Memory：长会话摘要压缩
SESSION_SUMMARY_ENABLED: bool = os.environ.get("SESSION_SUMMARY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
SESSION_SUMMARY_TRIGGER_MESSAGES: int = int(os.environ.get("SESSION_SUMMARY_TRIGGER_MESSAGES", "12"))
SESSION_SUMMARY_RECENT_MESSAGES: int = int(os.environ.get("SESSION_SUMMARY_RECENT_MESSAGES", "6"))
SESSION_SUMMARY_MAX_CHARS: int = int(os.environ.get("SESSION_SUMMARY_MAX_CHARS", "1800"))

# Long-term Memory：对话结束后的记忆抽取
MEMORY_EXTRACTION_ENABLED: bool = os.environ.get("MEMORY_EXTRACTION_ENABLED", "false").lower() in ("1", "true", "yes", "on")
MEMORY_EXTRACTION_MAX_MEMORIES: int = int(os.environ.get("MEMORY_EXTRACTION_MAX_MEMORIES", "5"))
MEMORY_EXTRACTION_MIN_CONFIDENCE: float = float(os.environ.get("MEMORY_EXTRACTION_MIN_CONFIDENCE", "0.65"))
MEMORY_RETRIEVAL_ENABLED: bool = os.environ.get("MEMORY_RETRIEVAL_ENABLED", "false").lower() in ("1", "true", "yes", "on")
MEMORY_RETRIEVAL_TOP_K: int = int(os.environ.get("MEMORY_RETRIEVAL_TOP_K", "5"))

# Trusted Agent verifier. Keep enabled by default for agent QA, but fail open if
# the verifier model call has an error.
AGENT_VERIFIER_ENABLED: bool = os.environ.get("AGENT_VERIFIER_ENABLED", "true").lower() in ("1", "true", "yes", "on")
