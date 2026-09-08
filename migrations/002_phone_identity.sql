-- Phone callers are authenticated by the telephony provider's caller number.
-- They can later be linked to Supabase Auth by populating auth_user_id.
alter table public.patients
  alter column auth_user_id drop not null;

-- Preserve one Supabase-auth identity per patient while allowing multiple
-- phone-only patients to exist with NULL auth_user_id.
alter table public.patients drop constraint if exists patients_auth_user_id_key;
drop index if exists patients_auth_user_id_key;
create unique index if not exists patients_auth_user_id_key
  on public.patients(auth_user_id)
  where auth_user_id is not null;


create table if not exists public.conversation_recording_consents (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null unique references public.conversations(id) on delete cascade,
  consented boolean not null,
  consent_recorded_at timestamptz not null default now()
);

alter table public.conversation_recording_consents enable row level security;

create policy conversation_recording_consents_patient_select
on public.conversation_recording_consents
for select using (exists (
  select 1 from public.conversations c
  where c.id = conversation_recording_consents.conversation_id
    and c.patient_id = public.current_patient_id()
));

create policy conversation_recording_consents_clinician_select
on public.conversation_recording_consents
for select using (exists (
  select 1 from public.conversations c
  join public.appointments a on a.patient_id = c.patient_id
  where c.id = conversation_recording_consents.conversation_id
    and a.doctor_id = public.current_clinician_id()
));
