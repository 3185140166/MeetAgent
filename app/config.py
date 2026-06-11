# -*- coding: utf-8 -*-
from dotenv import load_dotenv
import os

load_dotenv()

APIFUSION_API_URL: str = os.environ.get("APIFUSION_API_URL", "https://apifusion.aispeech.com.cn/v1/chat/completions")
APIFUSION_API_KEY: str = os.environ.get("APIFUSION_API_KEY", "")
APIFUSION_MODEL: str = os.environ.get("APIFUSION_MODEL", "gpt-5.5")
DB_PATH: str = os.environ.get("DB_PATH", "data/meetagent.db")
TOP_K: int = int(os.environ.get("TOP_K", "8"))

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
