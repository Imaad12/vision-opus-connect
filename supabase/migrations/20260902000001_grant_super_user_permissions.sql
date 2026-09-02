-- Grants the "Super User" role (added in 20260902000000) every existing
-- application permission EXCEPT the admin.* ones -- "full application
-- access", not "system-level control". That distinction is the whole
-- point of keeping it separate from "Super Admin" (which still gets
-- every permission, admin.* included, via the existing catch-all insert
-- in 20260818103534_*.sql's "DEFAULT ROLE PERMISSIONS" section).
--
-- Idempotent: ON CONFLICT DO NOTHING means re-running this migration
-- (e.g. if `supabase db push` is ever re-applied) is a no-op the second
-- time, never a duplicate-row error.
INSERT INTO public.role_permissions (role, permission)
SELECT 'super_user', p
FROM unnest(enum_range(NULL::public.app_permission)) AS p
WHERE p::text NOT LIKE 'admin.%'
ON CONFLICT DO NOTHING;
