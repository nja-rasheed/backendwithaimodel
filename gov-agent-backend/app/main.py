from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import Base, engine, SessionLocal

import app.models  # noqa: F401
from app.api import auth, profile, ai, services
from app.services.catalog_seed import seed_government_services
from app.api import auth, profile, ai, services, discovery
from app.api import auth, profile, ai, services, discovery, agent
from app.api import auth, profile, ai, services, discovery, agent, eligibility
from app.api import documents
from app.api import execution
from app.api import browser
Base.metadata.create_all(bind=engine)

# Auto-seed the verified service records
with SessionLocal() as db_session:
    seed_government_services(db_session)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Backend API engine for autonomous citizen bureaucracy and service assistance.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://agent-frontend-rf4w.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=[
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "ngrok-skip-browser-warning",
    ],
)

# Register Endpoints
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(ai.router)
app.include_router(services.router)
app.include_router(discovery.router)
app.include_router(agent.router)
app.include_router(eligibility.router)
app.include_router(documents.router)
app.include_router(execution.router)
app.include_router(browser.router)


@app.get("/health", tags=["System"])
def health_check():
    return {
        "status": "online",
        "service": settings.PROJECT_NAME,
        "database": "connected"
    }