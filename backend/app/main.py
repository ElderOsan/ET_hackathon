from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router

app = FastAPI(title="Renewable Energy Orchestrator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Packaging (B2): a judge runs run.bat/run.sh and gets Python only -- no Node, no separate
# dev server. frontend/dist/ is a committed, pre-built artifact (see .gitignore's note next
# to it); mounted here, after every /api route, so API routes are never shadowed. Guarded by
# .exists() so our own dev checkouts (vite on :5173, dist/ absent or stale) still start clean
# -- dev mode is entirely unaffected by this block.
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
