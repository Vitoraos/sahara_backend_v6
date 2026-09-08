-- Initial schema from BACKEND_BUILD_PROMPT.md.
-- RLS is enabled on all patient/clinician data tables.

create extension if not exists pgcrypto;

create table if not exists patients (
  id uuid primary key default gen_random_uuid(),
  phone_number text not null unique,
  name text,
  auth_user_id uuid not null unique,
  created_at timestamptz not null default now()
);

create table if not exists clinicians (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  phone_number text not null,
  auth_user_id uuid not null unique,
  created_at timestamptz not null default now()
);

create table if not exists conversations (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid not null references patients(id),
  channel text not null check (channel in ('web', 'call')),
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  status text not null
);

create table if not exists turns (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references conversations(id) on delete cascade,
  turn_number integer not null check (turn_number > 0),
  transcript text not null,
  translated_text text,
  extracted_fields jsonb not null default '{}'::jsonb,
  detected_language jsonb not null default '{}'::jsonb,
  asr_provider text not null,
  created_at timestamptz not null default now(),
  unique (conversation_id, turn_number)
);

create table if not exists triage_results (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null unique references conversations(id) on delete cascade,
  urgency_tier text not null,
  danger_signs jsonb not null default '[]'::jsonb,
  summary text not null,
  created_at timestamptz not null default now()
);

create table if not exists appointments (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid not null references patients(id),
  conversation_id uuid references conversations(id),
  tier text not null,
  scheduled_at timestamptz not null,
  doctor_id uuid references clinicians(id),
  status text not null,
  notified_via text
);

create table if not exists prescriptions (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid not null references patients(id),
  doctor_id uuid not null references clinicians(id),
  medication text not null,
  dosage text not null,
  instructions text not null,
  issued_at timestamptz not null default now(),
  status text not null
);

create table if not exists call_recordings (
  id uuid primary key default gen_random_uuid(),
  appointment_id uuid not null references appointments(id),
  consent_recorded_at timestamptz not null,
  recording_url text,
  transcript text,
  key_points_summary text,
  created_at timestamptz not null default now()
);

create table if not exists benchmark_runs (
  id uuid primary key default gen_random_uuid(),
  model_name text not null,
  language_pair text not null,
  wer double precision not null,
  entity_accuracy double precision not null,
  run_at timestamptz not null default now()
);

alter table patients enable row level security;
alter table clinicians enable row level security;
alter table conversations enable row level security;
alter table turns enable row level security;
alter table triage_results enable row level security;
alter table appointments enable row level security;
alter table prescriptions enable row level security;
alter table call_recordings enable row level security;

-- benchmark_runs is intentionally excluded from RLS per the supplied schema requirement.

-- Patient identity helper.
create or replace function public.current_patient_id()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select id from public.patients where auth_user_id = auth.uid() limit 1;
$$;

-- Clinician identity helper.
create or replace function public.current_clinician_id()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select id from public.clinicians where auth_user_id = auth.uid() limit 1;
$$;

-- Patients: own patient row only.
create policy patients_select_own on patients
  for select using (auth_user_id = auth.uid());

-- Clinicians: own clinician row only.
create policy clinicians_select_self on clinicians
  for select using (auth_user_id = auth.uid());

-- Patient-owned conversation access.
create policy conversations_patient_select on conversations
  for select using (patient_id = public.current_patient_id());

-- Patient-owned turns access through conversation.
create policy turns_patient_select on turns
  for select using (
    exists (
      select 1 from conversations c
      where c.id = turns.conversation_id
        and c.patient_id = public.current_patient_id()
    )
  );

-- Patient-owned triage result access.
create policy triage_results_patient_select on triage_results
  for select using (
    exists (
      select 1 from conversations c
      where c.id = triage_results.conversation_id
        and c.patient_id = public.current_patient_id()
    )
  );

-- Patient appointment access.
create policy appointments_patient_select on appointments
  for select using (patient_id = public.current_patient_id());

-- Patient prescription access.
create policy prescriptions_patient_select on prescriptions
  for select using (patient_id = public.current_patient_id());

-- Patient call-recording access through appointment.
create policy call_recordings_patient_select on call_recordings
  for select using (
    exists (
      select 1 from appointments a
      where a.id = call_recordings.appointment_id
        and a.patient_id = public.current_patient_id()
    )
  );

-- Clinician access is scoped to patients assigned to that clinician's queue.
create policy conversations_clinician_select on conversations
  for select using (
    exists (
      select 1 from appointments a
      where a.patient_id = conversations.patient_id
        and a.doctor_id = public.current_clinician_id()
    )
  );

create policy turns_clinician_select on turns
  for select using (
    exists (
      select 1 from conversations c
      join appointments a on a.patient_id = c.patient_id
      where c.id = turns.conversation_id
        and a.doctor_id = public.current_clinician_id()
    )
  );

create policy triage_results_clinician_select on triage_results
  for select using (
    exists (
      select 1 from conversations c
      join appointments a on a.patient_id = c.patient_id
      where c.id = triage_results.conversation_id
        and a.doctor_id = public.current_clinician_id()
    )
  );

create policy appointments_clinician_select on appointments
  for select using (doctor_id = public.current_clinician_id());

create policy prescriptions_clinician_select on prescriptions
  for select using (doctor_id = public.current_clinician_id());

create policy call_recordings_clinician_select on call_recordings
  for select using (
    exists (
      select 1 from appointments a
      where a.id = call_recordings.appointment_id
        and a.doctor_id = public.current_clinician_id()
    )
  );
