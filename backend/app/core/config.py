import os

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Patch 3, Step 4: no longer raises at import time. A missing key must not crash the app --
# Recorded-run and Safe-mode use no key and no network at all, and the UI needs to be able
# to say so rather than fail to start. The absence is instead surfaced the moment a LIVE
# call is actually attempted (app/core/llm_client.py::get_client), as a clear, catchable
# error rather than an unstartable process.
