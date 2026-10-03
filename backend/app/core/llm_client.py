from google import genai

from app.core.config import GEMINI_API_KEY, GEMINI_MODEL

_client = genai.Client(api_key=GEMINI_API_KEY)


def get_client() -> genai.Client:
    return _client


MODEL = GEMINI_MODEL
