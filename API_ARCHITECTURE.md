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
| `GET /clients`, `GET /clients/{id}` | `customers.view` | `client_service` |
| `POST /clients` | `customers.create` | `client_service.create_client` |
| `PUT /clients/{id}` | `customers.edit` | `client_service.update_client` |
| `GET /vendors`, `GET /vendors/{id}` | `suppliers.view` | `vendor_service` (new, mirrors `client_service`) |
| `POST /vendors` | `suppliers.create` | `vendor_service.create_vendor` |
| `PUT /vendors/{id}` | `suppliers.edit` | `vendor_service.update_vendor` |
| `GET /projects`, `GET /projects/{id}` | `projects.view` | `project_service` |
| `POST /projects` | `projects.create` | `project_service.create_project` |
| `PUT /projects/{id}` | `projects.edit` | `project_service.update_project` |
| `GET /quotations` | `quotations.view` | `quotation_service.list_quotation_versions` |
| `GET /quotations/{id}`, `GET /quotations/{id}/versions` | `quotations.view` | `quotation_service` |
| `POST /projects/{id}/quotations` | `quotations.create` | `quotation_service.create_quotation` |
| `POST /quotations/{id}/revisions` | `quotations.create` | `quotation_service.create_quotation_revision` |
| `GET /quotation-versions/{id}`, `.../boq-lines` | `quotations.view` | `quotation_service` (BOQ lines: read-only) |
| `POST /quotation-versions/{id}/submit` | `quotations.submit` | `quotation_service.mark_submitted` |
| `POST /quotation-versions/{id}/lose`, `.../withdraw` | `quotations.edit` | `quotation_service.mark_lost` / `mark_withdrawn` |
| `POST /quotation-versions/{id}/award` | `quotations.approve` | `quotation_service.mark_awarded` |
| `GET /projects/{id}/quotations` | `quotations.view` | `quotation_service.list_quotations_for_project` |
| `GET /projects/{id}/contract`, `GET /contracts/{id}` | `contracts.view` | new `contract_service` |
| `POST /projects/{id}/contracts` | `contracts.create` | `contract_service.create_contract` (project must be `AWARDED`) |
| `POST /contracts/{id}/activate`, `.../complete`, `.../terminate` | `contracts.edit` | `contract_service` |

`QuotationRead` now nests `project: {id, name, project_code, client: {id, name}}`,
read from the same eager-loaded relationships `list_quotation_versions`
already uses — this is what lets a quotation list show project/client
names without a second round trip.

`Contract` (new model) is created once, only from an `AWARDED` project,
copying `value`/`currency` from `Project` at that moment rather than
referencing it live — see the model's docstring. No amendment/versioning
states; a post-signing value change is a `ProjectVariation`, same as it
already is for `Project.contract_value` itself.

Run locally: `uvicorn app.api.main:app --reload`, configured via
`VISION_SUPABASE_URL` and `VISION_SUPABASE_ANON_KEY` (both already
public/client-side values in the frontend's `.env` — no new secret is
introduced).

### 6.1 Known field/shape gaps (not papered over)

- **Vendors/`suppliers.tsx`**: the frontend form collects `category`,
  `cr_number`, `city`, `payment_terms_days` (a number), a three-state
  `status`, `rating`, `iban`, `address`, `name_ar` — none of which exist
  on `Vendor`. The API exposes exactly what `Vendor` has
  (`vendor_type`, `name`, contact fields, `tax_number`, `payment_terms`
  as free text, `is_active`, `notes`). Wiring the frontend's supplier
  *form* needs one of: extend `Vendor` with the missing columns, or trim
  the form. Not decided here.
- **Projects/`projects.tsx`**: the frontend form also collects
  `manager_id`, `location`, `budget_cost`, `progress_percent`, and a
  directly-editable `contract_value`. `contract_value` is deliberately
  never settable through `create_project`/`update_project` — it is set
  exactly once by `quotation_service.mark_awarded` — so an API that
  accepted it from this form and silently dropped it would be worse than
  not wiring the field at all. `ProjectStatus`'s real values differ
  entirely from the frontend's; returned as-is, not silently renamed.
- **Quotations/`quotations.tsx`**: the frontend models one flat
  `quotations` row per quote plus separate `quotation_items`/
  `quotation_approvals` tables. The backend keeps `Quotation` (identity)
  and `QuotationVersion` (the priced, dated, status-carrying, *immutable*
  revision) separate by design — collapsing that to fit the frontend's
  flat shape would remove the audit trail `quotation_service` exists to
  protect. This API exposes the real versioned shape; reconciling it
  with the existing quotation UI is the next dedicated piece of work,
  not something to shortcut here. There is also no distinct "approval"
  step in the backend beyond submit/award — `QuotationStatus` doesn't
  have one — so no approval endpoint was invented.

## 7. Next slices

Purchase Orders is intentionally not next — see the standing PO-naming
decision (backend `PurchaseOrder` = client-award evidence vs. the
frontend's outbound-supplier-order concept) that must be resolved before
any wiring there. After that: Invoices/Payments/Expenses (no dedicated
service module yet — one would need to be added first, following
`vendor_service.py`'s pattern), then the quotation-shape and
vendor/project-field reconciliations above, each of which is a real,
scoped decision rather than an API afterthought.
