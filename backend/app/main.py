import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import agent, appointments, calls, health, knowledge, leads, summaries, vapi
from app.core.config import ENV_FILE, settings

# Make application INFO logs visible in the uvicorn console.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Backend API for SalesPilot AI - Autonomous AI Sales Voice Agent",
)

# Allow the React frontend (running on a different port) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# All API routes are mounted under the /api prefix.
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(agent.router, prefix="/api/agent", tags=["agent"])
app.include_router(vapi.router, prefix="/api/vapi", tags=["vapi"])
app.include_router(leads.router, prefix="/api/leads", tags=["leads"])
app.include_router(calls.router, prefix="/api/calls", tags=["calls"])
app.include_router(summaries.router, prefix="/api/summaries", tags=["summaries"])
app.include_router(appointments.router, prefix="/api/appointments", tags=["appointments"])
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["knowledge"])

# --- Startup diagnostics: report what is configured, never the actual values ---
logger.info("Loaded environment file: %s", ENV_FILE)
logger.info(
    "MongoDB configured: %s (database=%s)",
    settings.mongodb_configured,
    settings.MONGODB_DB_NAME,
)
logger.info(
    "Gemini API key configured: %s (model=%s)",
    bool(settings.GEMINI_API_KEY.strip()),
    settings.GEMINI_MODEL,
)
logger.info(
    "Vapi configured: %s (assistant set=%s, webhook secret set=%s, public url set=%s)",
    settings.vapi_configured,
    bool(settings.VAPI_ASSISTANT_ID.strip()),
    settings.vapi_secret_configured,
    bool(settings.PUBLIC_BASE_URL.strip()),
)
if not settings.vapi_secret_configured:
    logger.warning(
        "VAPI_WEBHOOK_SECRET is not set; the /api/vapi endpoints are unprotected. "
        "Set it before exposing this backend publicly."
    )


@app.get("/")
def root():
    """Root endpoint used to confirm the server is up."""
    return {
        "message": f"{settings.APP_NAME} API is running",
        "docs": "/docs",
        "health": "/api/health",
        "agent_chat": "/api/agent/chat",
        "vapi_webhook": "/api/vapi/webhook",
        "vapi_llm": "/api/vapi/llm/chat/completions",
        "leads": "/api/leads",
        "calls": "/api/calls",
        "summaries": "/api/summaries",
        "appointments": "/api/appointments",
        "knowledge": "/api/knowledge/documents",
    }
