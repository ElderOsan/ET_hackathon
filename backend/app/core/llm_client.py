from google import genai

from app.core.config import GEMINI_API_KEY, GEMINI_MODEL

_client: genai.Client | None = None


def get_client() -> genai.Client:
    """Lazily constructs the client on first real use, not at import time (Patch 3, Step 4)
    -- the app must be able to start, and Recorded/Safe mode must work, with no key at all."""
    global _client
    if GEMINI_API_KEY == "":
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy backend/.env.example to backend/.env and add your key "
            "(get one free, no credit card, at https://aistudio.google.com), or use Recorded-run or Safe mode, which need no key."
        )
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


MODEL = GEMINI_MODEL
