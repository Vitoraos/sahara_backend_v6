# Backend — Sahara Triage Voice Agent

FastAPI backend for the Sahara CodeSwitch Africa Challenge conversational health-triage voice agent.

## Current milestone

This version moves the backend from a scaffold to a provider-backed, persistent, frame-based voice pipeline:

1. Supabase schema + RLS migration.
2. Dependency/config boundaries.
3. Safety-first extraction + hardcoded danger-phrase gate.
4. Configurable clinical required-field policy (field names are not invented; populate them from the authoritative clinical specification).
5. OpenRouter extraction/response provider with bounded timeout/retry behavior.
6. Hardcoded English danger-phrase gate (no translation step).
7. Intron streaming STT WebSocket client.
8. Intron streaming TTS WebSocket client and audio relay.
9. Real Pipecat frame pipeline: audio frames → Intron STT → safety/triage frames → Intron TTS → audio frames.
10. Supabase-backed conversations, turns, and triage results.
11. Africa's Talking phone callback channel with explicit recording consent and turn-based recording/STT.
12. Fail-safe escalation on provider/pipeline/persistence failure.

The backend preserves the project's non-negotiable safety rule: a turn reaches `TRIAGE` only when a danger sign fires or every configured required field is present. The raw transcript is matched directly against the hardcoded danger phrases.

## Required runtime configuration

Copy `.env.example` to `.env` and populate at least:

- `INTRON_API_KEY` (shared by STT and TTS)
- `OPENROUTER_API_KEY`
- `REDIS_URL` (Upstash `rediss://` endpoint)
- `CORS_ALLOWED_ORIGINS` (comma-separated frontend origins)
- `REQUIRED_TRIAGE_FIELDS`
- `DANGER_SIGN_PHRASES`
- `SUPABASE_SERVICE_ROLE_KEY` (server-only; required for persistence)
- `SUPABASE_ANON_KEY` (required for `/auth/*/signup`)
- `BASE_URL` for Africa's Talking callbacks

Apply `migrations/005_scheduling.sql` in the Supabase SQL Editor (after 001-004).

## Signup, availability, and auto-routing

- `POST /api/auth/patient/signup {name, phone_number, email, password}` and `POST /api/auth/doctor/signup {…license_number, specialty, confirm_license}` create the Supabase Auth user, then the profile row, and return `{access_token}`. Turn **off "Confirm email"** in Supabase Auth settings or signup returns a null token (profile still created; user signs in after confirming).
- Doctor verify is dummy: any non-empty license/specialty plus the checkbox is accepted. Check a real register before production.
- Doctors set weekly windows (UTC, one start/end per weekday) via `PUT /api/clinician/availability`; days with no window are unavailable.
- After triage the voice agent auto-books the earliest free 25-minute slot across all doctors (next 7 days, UTC): the phone channel appends the time to its reply; the web client calls `POST /api/appointments/route {conversation_id}`. Patients read their time at `GET /api/appointments`.
- `GET /api/clinician/queue` embeds each appointment's patient `{name, phone_number, email}` and the voice-agent `triage_report`.

The generated triage vocabulary is a candidate community-health safety configuration and must be clinically reviewed/localized before production deployment. `REQUIRED_TRIAGE_FIELDS` and `DANGER_SIGN_PHRASES` are comma-separated configuration values.

## Phone channel

Africa's Talking Voice is callback/XML based. The implemented phone path uses explicit consent followed by short recorded turns; the same Intron STT and safety/triage logic processes each turn. AT documents `Say`, `Record`, `Dial`, and other XML voice actions, and recording supports WAV/MP3. A true live-media phone path requires an RTP/SIP bridge; the code does not fake that transport.

Inbound callback: `POST /api/voice/webhook`
Consent callback: `POST /api/voice/consent`
Recording callback: `POST /api/voice/recording`

## WebSocket

Client endpoint:

```text
WS /api/conversations/ws
```

Auth: `Authorization: Bearer <supabase_jwt>` header, or `?token=<supabase_jwt>` query param for browsers (header takes priority).

Client audio message:

```json
{
  "message_type": "INPUT_AUDIO_CHUNK",
  "audio_base_64": "...",
  "ack_id": 1
}
```

Finish an utterance:

```json
{"message_type":"COMMIT"}
```

Backend events include `SESSION_CREATED`, `PARTIAL_TRANSCRIPT`, `AUDIO_CHUNK_ACK`, `COMMITTED_TRANSCRIPT`, `TRIAGE_UPDATE`, `TTS_AUDIO_CHUNK`, `TTS_AUDIO_END`, and fail-safe `ERROR` / `ESCALATION_REQUIRED` events.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Health check: `GET /api/health`

## Tests

```bash
pytest -q
```

The current suite covers the safety gate, language profile, required-field policy, TTS chunking/audio decoding, and pipeline behavior.

## API docs

Live Swagger UI at `/docs` (ReDoc at `/redoc`, raw spec at `/openapi.json`). Regenerate the checked-in `openapi.json` after route changes:

```bash
python -c "import json, app.main; json.dump(app.main.app.openapi(), open('openapi.json','w'), indent=2)"
```

## Voice latency notes

- Turn persistence is write-behind: the frame pipeline pushes turns/triage to Redis (`sahara:turns`, `sahara:triage`) in one round-trip and speaks immediately; a background task flushes to Supabase. Without `REDIS_URL` it falls back to inline writes automatically.
- Auth tokens are cached 60s (`sahara:auth:*`); OpenRouter uses one keep-alive HTTP client per process.
- Measure before adding more caching: if Upstash RTT from your host is worse than Supabase RTT, caching reads makes things slower. Compare `PING` RTTs first.

## Important implementation boundary

The supplied project specification does not define the authoritative clinical field schema or danger-sign phrase list. Those remain configuration-driven instead of being fabricated in code. Likewise, the supplied TTS screenshot does not expose every query parameter/response field, so the TTS adapter keeps its endpoint configurable and parses the documented response message types without pretending undocumented fields are guaranteed.


## V5 runtime notes

- Browser voice uses a real Pipecat `Pipeline` + `PipelineWorker` + `WorkerRunner` graph. Pipecat currently recommends `PipelineWorker`/`WorkerRunner`; the older `PipelineTask`/`PipelineRunner` names are deprecated aliases.
- Intron STT is fed PCM16 chunks and committed per utterance. Intron terminates a committed STT stream, so the adapter reconnects on the next utterance.
- Intron TTS follows the documented `INPUT_TEXT_CHUNK` (10-100 chars) -> `FETCH_AUDIO_CHUNK` -> `READY` -> `COMMIT` flow.
- Browser interruption messages (`INTERRUPT` / `START_INTERRUPTION`) become Pipecat `InterruptionFrame`s and cancel in-flight TTS generation.
- Phone uses Africa's Talking's callback/XML voice model with explicit recording consent and short recorded speech turns. AT's documented voice callbacks are HTTP/XML; raw realtime media requires a SIP/RTP bridge.
- Supabase persistence uses the async service-role client only on the server. Do not expose the service/secret key to the browser.

### Required Intron TTS configuration

Set `INTRON_TTS_VOICE_ACCENT` and `INTRON_TTS_VOICE_GENDER` to values supported by the Intron account. The project intentionally does not guess these provider-specific values.

## Changes in this pass

- **LLM provider is OpenRouter.** `app/dialogue/llm_provider.py` calls `https://openrouter.ai/api/v1/chat/completions` (OpenAI-compatible). Set `OPENROUTER_API_KEY` plus the `OPENROUTER_*_MODEL` names.
- **Portal routes implemented** (previously empty 3-line stubs, not registered in `main.py`):
  - `GET /api/appointments` — patient's own appointments
  - `GET /api/history` — patient's conversation history with triage outcomes
  - `GET /api/prescriptions` — patient's prescription inbox
  - `POST /api/prescriptions` — clinician sends a prescription
  - `GET /api/clinician/queue` — clinician's appointment queue, urgency-sorted
  - `GET /api/clinician/patients/{id}/triage-form` — per-patient triage detail
  - `POST /api/calls/click-to-call` — clinician-initiated call, consent-gated recording
  - `POST /api/calls/patient-join/{appointment_id}` — patient-side call button
  - `POST /api/calls/{call_recording_id}/summarize` — LLM key-point extraction from a call transcript for the doctor's record
  - All are now registered in `app/main.py` and gated by `app/routes/deps.py` (`require_patient_id` / `require_clinician_id`) — this dependency, not RLS, is the real access boundary here, since the backend uses the Supabase **service-role** key which bypasses RLS.
- **Benchmark harness implemented** (`app/benchmark/`): `metrics.py` has real, tested WER (edit-distance) and clinical-entity-accuracy functions; `run_benchmark.py` and `dataset.py` give a working orchestration skeleton. **Still blocked:** Sahara's *file-upload* STT endpoint (needed to transcribe the benchmark dataset offline) is unconfirmed — only the *streaming* endpoint has been verified. See `app/benchmark/providers.py`.
- **Removed dead code:** `app/providers/` (empty orphaned package), `app/pipeline/tts_provider.py` (unused duplicate wrapper — the pipeline calls `intron_tts.py` directly), and unused `SaharaSTTProvider`/`GroqWhisperSTTProvider` stub classes in `app/pipeline/stt_providers.py`.

## Known gaps / please confirm

1. **Sahara file-upload STT** — needed for `app/benchmark/run_benchmark.py` to actually run against the AfriswitchCare dataset. Get the "Speech To Text Files Uploads" docs page and fill in `app/benchmark/providers.py`.
2. **Intron TTS endpoint specificity** — `app/pipeline/intron_tts.py` is detailed enough (chunk polling, voice params) that it looks like it came from a real docs page rather than a guess. If that page wasn't actually reviewed, confirm it before relying on it in production.
3. **Second and third benchmark models** — the challenge requires 3+ models including Sahara. Whisper/MMS (or whichever two you pick) still need concrete `STTBenchmarkProvider` implementations in `app/benchmark/providers.py`.
4. **Pipecat version pinning** — `pipecat-ai==1.8.1` in requirements.txt. The core classes used (`Pipeline`, `FrameProcessor`, `PipelineWorker`, `PipelineParams`) are confirmed against Pipecat's public docs, but run `pytest` locally with real dependencies installed before trusting the frame graph fully — this sandbox has no network access to verify it end-to-end.
