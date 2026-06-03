"""
╔══════════════════════════════════════════════════════════════╗
║          Apex POS — Cloud Backend  v1.0                     ║
║  FastAPI · SQLite (dev) → PostgreSQL (prod) ready           ║
║  Multi-Branch Sync · JWT Auth · Manager Dashboard API       ║
╚══════════════════════════════════════════════════════════════╝

Run:
    uvicorn main:app --reload --port 8000

Swagger docs:
    http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from routers import auth, sync, dashboard, inventory, branches, alerts

app = FastAPI(
    title="Apex POS Cloud API",
    description="Backend for Apex POS multi-branch system",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # تضيق في production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── init DB on startup ──────────────────────────────────────────
@app.on_event("startup")
def startup():
    init_db()

# ── routers ─────────────────────────────────────────────────────
app.include_router(auth.router,       prefix="/auth",      tags=["Auth"])
app.include_router(sync.router,       prefix="/sync",      tags=["Sync"])
app.include_router(dashboard.router,  prefix="/dashboard", tags=["Dashboard"])
app.include_router(inventory.router,  prefix="/inventory", tags=["Inventory"])
app.include_router(branches.router,   prefix="/branches",  tags=["Branches"])
app.include_router(alerts.router,     prefix="/alerts",    tags=["Alerts"])

@app.get("/")
def root():
    return {"status": "Apex POS Cloud API running", "version": "1.0.0"}
