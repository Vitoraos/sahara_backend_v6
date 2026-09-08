-- Runtime grants for the user-facing Data API.
-- The backend itself uses the server-only service key.
-- RLS remains the authorization boundary for authenticated users.

grant select on public.patients to authenticated;
grant select on public.clinicians to authenticated;
grant select on public.conversations to authenticated;
grant select on public.turns to authenticated;
grant select on public.triage_results to authenticated;
grant select on public.appointments to authenticated;
grant select on public.prescriptions to authenticated;
grant select on public.call_recordings to authenticated;
grant select on public.conversation_recording_consents to authenticated;

grant all on public.patients to service_role;
grant all on public.clinicians to service_role;
grant all on public.conversations to service_role;
grant all on public.turns to service_role;
grant all on public.triage_results to service_role;
grant all on public.appointments to service_role;
grant all on public.prescriptions to service_role;
grant all on public.call_recordings to service_role;
grant all on public.conversation_recording_consents to service_role;

-- Verification queries (run in Supabase SQL Editor as an administrator):
-- select relname, relrowsecurity from pg_class where relname in
-- ('patients','clinicians','conversations','turns','triage_results','appointments','prescriptions','call_recordings','conversation_recording_consents');
-- select schemaname, tablename, policyname, cmd from pg_policies
-- where schemaname='public' order by tablename, policyname;
