-- Signup profiles, doctor weekly availability, and booking safety.
-- Apply after 001-004 in Supabase SQL Editor (service_role / postgres).

-- Profiles created by the new /auth/*/signup endpoints.
alter table public.patients
  add column if not exists email text unique;

alter table public.clinicians
  add column if not exists email text unique,
  add column if not exists license_number text,
  add column if not exists specialty text;

-- One availability window per doctor per weekday (0=Monday..6=Sunday, UTC).
-- A day with no row means the doctor is unavailable that day.
create table if not exists public.doctor_availability (
  id uuid primary key default gen_random_uuid(),
  doctor_id uuid not null references public.clinicians(id) on delete cascade,
  weekday integer not null check (weekday between 0 and 6),
  start_time time not null,
  end_time time not null,
  check (start_time < end_time),
  unique (doctor_id, weekday)
);

-- Anti-double-book: the router retries the next slot on conflict.
create unique index if not exists appointments_doctor_slot_key
  on public.appointments(doctor_id, scheduled_at)
  where status <> 'cancelled';

alter table public.doctor_availability enable row level security;

-- Doctors read their own windows via the Data API.
create policy doctor_availability_clinician_select on public.doctor_availability
  for select using (doctor_id = public.current_clinician_id());

grant select on public.doctor_availability to authenticated;
grant all on public.doctor_availability to service_role;
