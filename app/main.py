from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes.appointments import router as appointments_router
from app.routes.calls import router as calls_router
from app.routes.clinician import router as clinician_router
from app.routes.conversation import router as conversation_router
from app.routes.health import router as health_router
from app.routes.history import router as history_router
from app.routes.prescriptions import router as prescriptions_router
from app.routes.voice_webhook import router as voice_router

settings = get_settings()

app = FastAPI(title=settings.app_name, version='0.1.0')

# ponytail: one allow-list from env. Split per-origin if a route needs wider
# access than the others; a global list is the minimum that works.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix=settings.api_prefix)
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
