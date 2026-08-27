# API Architecture

## 1. Purpose

This backend has, until now, had exactly one caller: the PySide6 desktop
UI, talking to `app/services/*` in-process. The VINCO frontend (a
TanStack Start/React app, currently reading and writing an independent
Supabase/Postgres database directly — see the frontend integration
inspection report) is being migrated to call this backend instead of its
own database for every domain this backend already owns. `app/api/`
is the thin HTTP layer that makes that possible.

**Nothing about the business-logic layering changes.** A route handler
calls the same `app/services/*.py` function the desktop UI already
calls, with the same `Session`, the same validation, the same
`ValidationError`. The API package owns exactly three things: turning an
HTTP request into a function call, turning a return value into JSON, and
deciding whether the caller is allowed to make that call at all.

## 2. Identity and permissions: delegated to Supabase, not duplicated

This backend has no `User`, `Role`, or `Permission` model, and this
integration does not add one. The VINCO frontend already has a complete,
working RBAC system, live, in its Supabase project: `user_roles`,
`role_permissions`, `user_permissions`, `user_scopes`, `profiles`, and
the `has_permission`/`can`/`has_full_scope`/`is_project_member` SQL
functions the frontend's own Row-Level-Security policies are built on.

Building a second, parallel role/permission model in this backend would
create exactly the failure mode this codebase's other safety conventions
exist to prevent elsewhere: two independently-editable sources of truth
for the same fact, silently drifting apart. So instead:

- **`app/api/auth.py: SupabaseAuth.verify_token`** verifies a bearer
  token's signature and expiry against the same Supabase project's JWKS
  (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`). This establishes
  *identity* only — who is making the request, and whether the token is
  genuine and unexpired. It never touches permissions.
- **`SupabaseAuth.check_permission`** asks Supabase's own `can(_perm)`
  Postgres function, over PostgREST (`POST {SUPABASE_URL}/rest/v1/rpc/can`),
  forwarding the *caller's own verified token* as the request's bearer
  credential — never a service-role key. Postgres evaluates `can()` as
  that user (`auth.uid()` resolves from the forwarded token), so the
  result is exactly what the frontend's RLS already enforces for that
  user, not a re-implementation of it.
- **`app/api/deps.py: require_permission(permission)`** is a dependency
  factory every protected route uses, e.g.
  `Depends(require_permission("customers.view"))`. The permission string
  is always copied verbatim from the frontend's `app_permission` Postgres
  enum — see the naming-mismatch bug already found and fixed in
  `purchase-orders.tsx`/`approvals.tsx` for what happens when a second,
  informal vocabulary drifts from the real one.

A verification failure is always **401** (we don't know who you are); a
permission-check failure is always **403** (we know who you are, and
you're not allowed). The two are never conflated.

**Known gap:** the frontend's RLS also scopes some tables to rows a
non-full-scope user owns or created (`owner_id`/`created_by`, e.g.
`customers_select`). The backend's existing models (`Client`, etc.) have
no such columns. Today, any caller who passes the permission check sees
every row, not just their own. This is a real scope gap to close — most
likely by adding `owner_id`/`created_by` to the relevant backend models —
not something papered over by this integration. Tracked here rather than
silently assumed away.

## 3. Company/tenant context

`get_or_create_default_company` (already used by `project_service`)
still applies: this remains a single-company system, and
`app/api/deps.py: get_current_company` just resolves that one row. When
multi-company support is needed, this is the one dependency that changes
to resolve a company from the caller's context instead of assuming there
is only one.

## 4. Why Supabase stays, for now, and what "no Lovable dependency" means

**Lovable** (the code-generation/hosting/sync product) and **Supabase**
(the Postgres + Auth + Storage service the generated frontend happens to
use) are different things. The direction is:

```
VINCO frontend -> this backend's API -> our own database
```

Lovable is not in that picture at all — nothing in this design requires
Lovable's editor, its git sync, or its OAuth relay to be reachable at
runtime. Supabase, however, is deliberately *kept* for identity/RBAC in
this phase: it is not a new paid dependency (it's already in production
use), replacing it is a substantial, separate identity-system project of
its own, and attempting it inside this integration would violate "don't
introduce another paid SaaS dependency merely to replace Lovable" in the
opposite direction — trading a working system for a half-built one.
Migrating identity/RBAC into this backend's own database (so Supabase can
eventually be retired too) is a later, explicitly-scoped phase, not an
implicit side effect of connecting the frontend to this API.

The business data itself (customers, projects, quotations, purchase
orders, invoices, ...) already lives only in this backend's database
(currently SQLite) and is never read from or written to Supabase's
Postgres by this API — that duplication is exactly what this integration
exists to eliminate. Moving that database from SQLite to a
self-hosted/owned Postgres instance is also a later, separate step (the
service layer and ORM models don't change either way); this phase does
not require it.

## 5. Request flow

```
VINCO frontend (bearer token from Supabase Auth)
  -> FastAPI route (app/api/routers/*.py)
       -> require_permission(...)   [401 / 403, via Supabase]
       -> get_db()                   [Session, same transaction semantics as the desktop UI]
       -> app/services/*.py          [existing business logic, unchanged]
       -> Pydantic response model    [app/api/schemas.py]
```

`ValidationError` raised by a service function is caught at the route and
returned as HTTP 422 with the service's own message; a top-level
exception handler in `app/api/main.py` catches any instance that reaches
it uncaught, so a future route that forgets the `try`/`except` still
fails as a 422, never a 500.

## 6. What exists today

| Route | Permission | Service |
|---|---|---|
| `GET /health` | none | — |
| `GET /company/me` | any authenticated user (matches `company_settings_select`'s `USING (true)`) | `project_service.get_or_create_default_company` |
| `GET /clients` | `customers.view` | `client_service.list_clients` |
| `GET /clients/{id}` | `customers.view` | `client_service.get_client` |
| `POST /clients` | `customers.create` | `client_service.create_client` |
| `PUT /clients/{id}` | `customers.edit` | `client_service.update_client` |

Run locally: `uvicorn app.api.main:app --reload`, configured via
`VISION_SUPABASE_URL` and `VISION_SUPABASE_ANON_KEY` (both already
public/client-side values in the frontend's `.env` — no new secret is
introduced).

## 7. Next slices (same pattern, in Step 3B's stated order)

Suppliers (`Vendor`/`vendor_matching`), Projects (`project_service`),
Quotations (`quotation_service`), Purchase Orders
(`purchase_order_service`), then Invoices/Payments/Expenses. Each is:
a Pydantic schema, a router that calls the existing service functions
with the matching frontend permission string, and route-level tests
following `test_api_clients.py`'s pattern (in-memory DB + a fake
Supabase auth double). No new service-layer logic should be needed for
any of these — if one seems to be, that's a signal the frontend needs a
capability the backend doesn't have yet (see the integration report's
"missing backend APIs"), not something to improvise in a route.
