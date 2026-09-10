from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes.appointments import router as appointments_router
from app.routes.auth import router as auth_router
from app.routes.calls import router as calls_router
from app.routes.clinician import router as clinician_router
from app.routes.conversation import router as conversation_router
from app.routes.health import router as health_router
from app.routes.history import router as history_router
from app.routes.prescriptions import router as prescriptions_router
from app.routes.voice_webhook import router as voice_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    summary="Conversational health-triage voice agent: Supabase-backed triage, scheduling, and clinician workflows.",
    description=(
        "Patient signup and voice triage (browser WebSocket or Africa's Talking phone channel), "
        "automatic doctor-slot routing, clinician queues with embedded triage reports, "
        "prescriptions, and consent-gated call workflows.\n\n"
        "Auth: Supabase session JWT as `Authorization: Bearer <token>` (use the Authorize button). "
        "The browser voice channel is a WebSocket and is documented in the README message catalog; "
        "phone callbacks accept `application/x-www-form-urlencoded` and return TwiML XML."
    ),
    servers=[
        {"url": "https://api.sahara.example.com", "description": "Production"},
        {"url": "http://localhost:8000", "description": "Local development"},
    ],
    openapi_tags=[
        {"name": "auth", "description": "Patient and doctor signup."},
        {"name": "conversation", "description": "Browser voice WebSocket channel."},
        {"name": "voice", "description": "Africa's Talking phone callbacks (form-data in, TwiML XML out)."},
        {"name": "appointments", "description": "Patient appointments and triage auto-routing."},
        {"name": "clinician", "description": "Doctor availability, queue, and triage reports."},
        {"name": "prescriptions", "description": "Clinician-issued prescriptions and patient inbox."},
        {"name": "history", "description": "Patient conversation history with triage outcomes."},
        {"name": "calls", "description": "Consent-gated doctor-patient calls and summaries."},
        {"name": "health", "description": "Service health."},
    ],
)

# ponytail: one allow-list from env. Split per-origin if a route needs wider
# access than the others; a global list is the minimum that works.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(conversation_router, prefix=settings.api_prefix)
app.include_router(voice_router, prefix=settings.api_prefix)
app.include_router(appointments_router, prefix=settings.api_prefix)
app.include_router(history_router, prefix=settings.api_prefix)
app.include_router(prescriptions_router, prefix=settings.api_prefix)
app.include_router(clinician_router, prefix=settings.api_prefix)
app.include_router(calls_router, prefix=settings.api_prefix)


@app.get('/')
async def root() -> dict[str, str]:
    return {'service': settings.app_name, 'status': 'ok'}
