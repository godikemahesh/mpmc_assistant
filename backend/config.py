"""App configuration. Secrets come ONLY from environment variables (.env locally)."""
import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
if GROQ_API_KEY.startswith("your_"):  # placeholder copied from .env.example
    GROQ_API_KEY = ""
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TIMEOUT = int(os.getenv("GROQ_TIMEOUT", "15"))

DATA_DIR = os.path.join(BASE_DIR, "data")
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "frontend"))

MAX_TOOL_CALLS = 3                   # hard cap per agent request (prevents loops)
MAX_UPLOAD_MB = 4                    # Vercel rejects request bodies above ~4.5 MB
MAX_MESSAGE_CHARS = 4000
MAX_CODE_CHARS = 8000
MAX_MANUAL_CHUNKS = 400
DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
