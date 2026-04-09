import os

DB_URL = os.getenv("DB_URL", "mysql+pymysql://root:123456@db:3306/chatbot_db")
BOOK_SERVICE_URL = os.getenv("BOOK_SERVICE_URL", "http://book-service:8000")
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8000")
BOOK_DETAIL_BASE_URL = os.getenv("BOOK_DETAIL_BASE_URL", "")
MAX_CONTEXT_CHUNKS = int(os.getenv("MAX_CONTEXT_CHUNKS", "5"))
LLM_API_BASE_URL = os.getenv("LLM_API_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "20"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "220"))
