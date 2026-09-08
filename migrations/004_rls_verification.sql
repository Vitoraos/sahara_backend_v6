-- Optional administrator-side verification. Run after 001-003 in Supabase SQL Editor.
-- This does not disable RLS and does not mutate patient data.

do $$
declare
  required_table text;
  rls_enabled boolean;
  missing_count integer;
begin
  foreach required_table in array array[
    'patients','clinicians','conversations','turns','triage_results',
    'appointments','prescriptions','call_recordings','conversation_recording_consents'
  ] loop
    select c.relrowsecurity into rls_enabled
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = required_table;

    if coalesce(rls_enabled, false) = false then
      raise exception 'RLS is not enabled on public.%', required_table;
    end if;
  end loop;

  select count(*) into missing_count
  from (values
    ('patients','patients_select_own'),
    ('clinicians','clinicians_select_self'),
    ('conversations','conversations_patient_select'),
    ('turns','turns_patient_select'),
    ('triage_results','triage_results_patient_select'),
    ('appointments','appointments_patient_select'),
    ('prescriptions','prescriptions_patient_select'),
    ('call_recordings','call_recordings_patient_select'),
    ('conversation_recording_consents','conversation_recording_consents_patient_select'),
    ('conversations','conversations_clinician_select'),
    ('turns','turns_clinician_select'),
    ('triage_results','triage_results_clinician_select'),
    ('appointments','appointments_clinician_select'),
    ('prescriptions','prescriptions_clinician_select'),
    ('call_recordings','call_recordings_clinician_select'),
    ('conversation_recording_consents','conversation_recording_consents_clinician_select')
  ) as expected(tablename, policyname)
  where not exists (
    select 1 from pg_policies p
    where p.schemaname = 'public'
      and p.tablename = expected.tablename
      and p.policyname = expected.policyname
  );

  if missing_count > 0 then
    raise exception 'One or more required RLS policies are missing';
  end if;
end $$;
