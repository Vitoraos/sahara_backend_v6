-- Preferred voice language per patient, chosen at signup from the
-- app-level allow-list (see app/dialogue/voice_map.py). Validated in the
-- API layer, not here, so the list can change without a migration.
alter table public.patients
  add column if not exists preferred_language text not null default 'en';
