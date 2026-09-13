# FastAPI → Go Migration Guide

> **Codebase**: `wes-vendor` — WENER Vendor Management Portal
> **Current stack**: FastAPI · SQLAlchemy 2.0 async · Jinja2 + HTMX · Supabase · Resend
> **Target stack**: Go · Echo v4 · Goth (OAuth/session auth) · Templ · sqlc + pgx · golang-migrate
> **Deployment target**: Vercel (Go serverless functions)
> **Report date**: 2026-08-17

---

## 1. Codebase Snapshot (Current State)

| Dimension | Count |
|---|---|
| Route modules | 11 (+ 1 orphaned duplicate — delete, do not port) |
| **Total active HTTP endpoints** | **46** |
| SQLAlchemy model files | 8 |
| DB tables | 9 |
| Jinja2 HTML templates | 30 |
| Shared components | 4 (`apple_spinner`, `flash`, `forms`, `status_badge`) |
| Total Python LOC (`app/`) | ~3,200 |
| Total Template LOC | ~3,600 |
| **Total codebase LOC** | **~6,800** |
| Unit tests | 13 |
| External integrations | 3 (Resend, Supabase Storage, Supabase PostgreSQL) |

### What Changed Since the Original Migration Report

The original report was written when the codebase was a simpler prototype. Since then:

| Change | Impact on Migration |
|---|---|
| **New `QC_RECEIVER` role added** to `UserRole` enum | Go auth middleware must include this role |
| **Delivery & QC tracking** added to `Requisition` model (`qc_done`, `qc_done_by`, `qc_done_at`, `delivery_image_url`, `invoice_url`, `invoice_number`, `payment_status`) | 7 new columns in the SQL migration; `/receive` endpoint and template to port |
| **`/receive` workflow** added (2 new routes in `requisitions/`) | New module: receive form + QC recording |
| **`/reports` module** added (lead-time analytics) | New module to port |
| **`/resend-health` endpoint** added (live Resend quota dashboard) | Optional: port or drop in Go |
| **Dashboard (`/`) expanded** with 6 KPI tiles + recent activity feed (complex aggregate queries) | Significant SQL to port in `main.go` |
| **`can_view_all_requisitions` permission flag** added to `UserProfile` | Add to Go struct and auth logic |
| **Apple Spinner component** added (intercepts all `<a>` clicks + HTMX events) | Survives intact — pure HTML/JS |
| **Audit log service** expanded with more action types | More `log_action()` call sites to port |
| **Supabase Storage** now used for TWO upload types: quotation images AND delivery photos | Upload paths differ; both must work |
| **`init_db()` DDL guard now 166 lines** (7 `ALTER TABLE` blocks) | Must all be captured in versioned SQL migrations |
| **`system_settings` key-value store** controls CC email list with 5-min in-memory TTL cache | Port the TTL cache pattern to Go |
| **`is_temporary` flag on Vendor** + temporary vendor creation workflow | New `add-temporary-vendor` route to port |
| **Requisition Kanban view** (6-column) added alongside the table view | Complex template; HTMX partials survive |
| **Actual endpoint count is 46** (not 44 as stated in original report — `/resend-health` + `/reports/` added) | — |

### LOC Breakdown by Module

| Module | Python LOC | Template LOC | Total |
|---|---|---|---|
| Core (`main.py`, `config.py`, `database.py`, `dependencies.py`) | 493 | — | 493 |
| Auth | 110 | ~230 | 340 |
| Vendors | 180 | ~420 | 600 |
| Categories | 67 | ~125 | 192 |
| **Requisitions** | **435** | **~1,650** | **~2,085** |
| Quotations (internal) | 131 | ~820 | 951 |
| Quotations (vendor/public) | 203 | ~380 | 583 |
| Decisions | 190 | ~280 | 470 |
| Reports | 68 | ~220 | 288 |
| Users | 96 | ~165 | 261 |
| Settings | 89 | ~180 | 269 |
| Audit | 34 + service.py | ~210 | 290 |
| Email Service | 334 | — | 334 |
| Storage Service | 107 | — | 107 |
| Scripts & Seeding | ~545 | — | 545 |
| Test Suite | 295 | — | 295 |
| **Total** | **~3,200** | **~3,680** | **~6,880** |

---

## 2. Full Endpoint Inventory (46 endpoints)

| # | Method | Path | Auth Requirement | Description |
|---|---|---|---|---|
| **Root & System** | | | | |
| 1 | `GET` | `/health` | Public | Healthcheck |
| 2 | `GET` | `/resend-health` | Public | Resend API quota dashboard |
| 3 | `GET` | `/` | Authenticated | Dashboard — 6 KPI tiles, recent activity, lead-time stats |
| **Auth** (`/auth`) | | | | |
| 4 | `GET` | `/auth/login` | Public | Login page |
| 5 | `POST` | `/auth/login` | Public | Form login; sets session cookie; auto-creates user profile (dev mode) |
| 6 | `GET` | `/auth/seed-db` | Public / Feature-flagged | Triggers DB seeder (disabled by default) |
| 7 | `GET` | `/auth/signup` | Public | Registration page |
| 8 | `POST` | `/auth/signup` | Public | Creates `UserProfile` (`procurement` role) |
| 9 | `GET` | `/auth/logout` | Authenticated | Clears session cookie |
| **Audit** (`/audit`) | | | | |
| 10 | `GET` | `/audit` | `management`, `admin` | 200 most recent audit log entries |
| **Vendors** (`/vendors`) | | | | |
| 11 | `GET` | `/vendors` | Authenticated | List active non-temporary vendors |
| 12 | `GET` | `/vendors/new` | Authenticated | Vendor creation form (with categories) |
| 13 | `POST` | `/vendors` | Authenticated | Create vendor + M2M categories + AuditLog |
| 14 | `GET` | `/vendors/{vendor_id}` | Authenticated | Vendor detail & update form |
| 15 | `POST` | `/vendors/{vendor_id}` | Authenticated | Update vendor + sync categories + AuditLog |
| 16 | `POST` | `/vendors/{vendor_id}/delete` | Authenticated | Delete vendor + AuditLog |
| **Categories** (`/categories`) | | | | |
| 17 | `GET` | `/categories` | Authenticated | List all categories |
| 18 | `POST` | `/categories` | Authenticated | Create category |
| 19 | `POST` | `/categories/{category_id}` | Authenticated | Update category |
| 20 | `POST` | `/categories/{category_id}/delete` | Authenticated | Delete category |
| **Requisitions** (`/requisitions`) | | | | |
| 21 | `GET` | `/requisitions` | Authenticated | List with Table / 6-column Kanban switch; role-filtered visibility |
| 22 | `GET` | `/requisitions/new` | Authenticated | Create form |
| 23 | `POST` | `/requisitions` | Authenticated | Create draft + AuditLog |
| 24 | `GET` | `/requisitions/{req_id}` | Authenticated | Detail page with vendor link statuses |
| 25 | `GET` | `/requisitions/{req_id}/select-vendors` | Authenticated | Multi-select vendor page |
| 26 | `POST` | `/requisitions/{req_id}/select-vendors` | `procurement`, `admin` | Generate tokens + send batch Resend invitations; status → `new` |
| 27 | `POST` | `/requisitions/{req_id}/add-temporary-vendor` | Authenticated | Create ad-hoc unlisted `is_temporary` vendor + token |
| 28 | `GET` | `/requisitions/{req_id}/receive` | `can_perform_qc` | QC receive form (invoice + delivery photo) |
| 29 | `POST` | `/requisitions/{req_id}/receive` | `can_perform_qc` | Record receipt, invoice number, delivery image upload; status → `received` + AuditLog |
| **Public Vendor Quotes** (`/vendor-quote`) | | | | |
| 30 | `GET` | `/vendor-quote/{token}` | Public (token-guarded) | Vendor quote submission form; shows thanks page if already submitted |
| 31 | `POST` | `/vendor-quote/{token}` | Public (token-guarded) | Multipart upload → Supabase Storage OR form data; Resend notifications |
| **Internal Quotations** (`/quotations`) | | | | |
| 32 | `GET` | `/quotations/inbox` | `can_see_quotes` | Inbox of non-draft requisitions + incoming quote counts |
| 33 | `GET` | `/quotations/detail/{rv_id}` | Authenticated | Single vendor quote detail |
| 34 | `POST` | `/quotations/detail/{rv_id}/status` | `can_see_quotes` | Manually update `RequisitionVendor.status` + AuditLog |
| 35 | `GET` | `/quotations/compare/{req_id}` | `can_see_quotes` | Side-by-side comparison matrix |
| **Decisions** (`/decisions`) | | | | |
| 36 | `GET` | `/decisions` | Authenticated | List all procurement decisions |
| 37 | `POST` | `/decisions/new/{req_id}/{vendor_id}` | `procurement`, `admin` | Select winning vendor + AuditLog + send win/loss emails |
| 38 | `GET` | `/decisions/{decision_id}` | Authenticated | Decision detail + management approval controls |
| 39 | `POST` | `/decisions/{decision_id}/approve` | `management`, `admin` or `is_management` flag | Approve/reject; sends win/loss Resend emails; transition status |
| **Reports** (`/reports`) | | | | |
| 40 | `GET` | `/reports/` | Authenticated | Lead-time analytics (decision approval → QC received) |
| **Users** (`/users`) | | | | |
| 41 | `GET` | `/users` | `has_management_authority` | User roster + permission matrix |
| 42 | `POST` | `/users/{user_id}/permissions` | `has_management_authority` | Update role + granular flags + AuditLog |
| **Settings** (`/settings`) | | | | |
| 43 | `GET` | `/settings` | `management`, `admin` | System config page (CC email list) |
| 44 | `POST` | `/settings/cc-emails/add` | `management`, `admin` | Add global CC email + invalidate cache |
| 45 | `POST` | `/settings/cc-emails/remove` | `management`, `admin` | Remove global CC email + invalidate cache |
| **Dashboard** (`GET /`) stats | | | | |
| 46 | — | — | — | 6 aggregate queries: open orders, delivered, pending payment, confirmed orders, pending decisions, avg lead-time |

> **Note:** `app/requisitions/receive_routes.py` is an orphaned file duplicating endpoints #28 and #29. It is **not imported in `main.py`** and must be **deleted, not ported**.

---

## 3. Database Architecture (9 Tables)

### Entity Relationship

```
  +------------------+         M2M          +--------------------+
  |    categories    |<===================>|      vendors       |
  |------------------|   vendor_categories  |--------------------|
  | id (PK, UUID)    |   (compound PK,      | id (PK, UUID)      |
  | name (Unique)    |    CASCADE delete)   | company_name       |
  | description      |                      | contact_email      |
  +------------------+                      | contact_person     |
                                            | phone              |
                                            | is_active          |
                                            | is_temporary  <---- NEW
                                            | created_by (FK)    |
                                            +---------+----------+
                                                      |
                                                      | 1:N
                                                      v
  +------------------+  1:N (created_by)   +---------+----------+
  |  user_profiles   |------------------->|   requisitions     |
  |------------------|  1:N (qc_done_by)  |--------------------|
  | id (PK, UUID)    |------------------->| id (PK, UUID)      |
  | email (Unique)   |                    | title              |
  | full_name        |                    | status (str enum)  |
  | role (str)       |                    | created_by (FK)    |
  | can_view_quotes  |                    | qc_done (bool) <-- NEW
  | can_do_qc        |                    | qc_done_by (FK) <- NEW
  | can_view_all_req |                    | qc_done_at <------- NEW
  | is_management    |                    | delivery_image_url  NEW
  +--------+---------+                    | invoice_url     <-- NEW
           |                              | invoice_number  <-- NEW
           |                              | payment_status  <-- NEW
           |                              +---------+----------+
           |                                        |
           |                                        | 1:N
           |                         +--------------+-----------+
           |                         |   requisition_vendors    |
           |                         |--------------------------|
           |                         | id (PK, UUID)            |
           |                         | requisition_id (FK)      |
           |                         | vendor_id (FK)           |
           |                         | unique_link_token (Uniq) |
           |                         | status ('pending', ...)  |
           |                         | link_sent_at             |
           |                         +-------------+------------+
           |                                       |
           |                                       | 1:1
           |                         +-------------+------------+
           |                         |        quotations        |
           |                         |--------------------------|
           |                         | id (PK, UUID)            |
           |                         | requisition_vendor_id FK |
           |                         | submission_type          |
           |                         | image_url                |
           |                         | form_data (JSON)         |
           |                         | notes                    |
           |                         +--------------------------+
           |
           | 1:N (decided_by / approved_by)
           v
  +--------+---------+
  |    decisions     |-----> requisition_id (FK)
  |------------------|-----> winning_vendor_id (FK)
  | id (PK, UUID)    |
  | decided_by (FK)  |
  | approved_by (FK) |
  | management_appr. |  NULL=pending, TRUE=approved, FALSE=rejected
  | approved_at      |
  +------------------+

  +------------------+     +--------------------+
  |   audit_logs     |     |  system_settings   |
  |------------------|     |--------------------|
  | id (PK, UUID)    |     | key (PK, Text)     |  <- 'cc_emails'
  | actor_id (FK)    |     | value (JSON Text)  |  <- JSON array of emails
  | actor_name       |     | updated_at         |
  | actor_email      |     +--------------------+
  | actor_role       |
  | action           |
  | entity_type      |
  | entity_id        |
  | entity_label     |
  | notes            |
  | created_at       |
  +------------------+
```

### Key Constraints

- **PKs**: UUID v4 strings (36 chars) across all tables — store as `VARCHAR(36)` in Postgres.
- **`vendor_categories`**: Compound PK `(vendor_id, category_id)`, `CASCADE` delete on both sides.
- **`requisition_vendors`**: Unique on `unique_link_token`; implicit unique on `(requisition_id, vendor_id)`.
- **`quotations`**: `requisition_vendor_id` is `UNIQUE` (strict 1:1 with `requisition_vendors`).
- **`system_settings`**: Key-value store. `key='cc_emails'` stores a JSON string array.
- **`audit_logs`**: Denormalizes actor name/email/role at event time; `actor_id` is `ON DELETE SET NULL`.
- **Requisition status**: String enum stored as `VARCHAR(50)` — **not** a native Postgres ENUM type. Values: `draft`, `new`, `in_progress`, `submitted`, `received`, `closed`.
- **`management_approved` in `decisions`**: Nullable boolean — `NULL` = pending, `TRUE` = approved, `FALSE` = rejected.

### Requisition State Machine

```
draft ---> new ---> in_progress ---> submitted ---> received ---> closed
  |          |           |                |
  +-(self)---+-(self)----+----(self)------+---> in_progress  (rejection loop)
```

Implemented in `app/requisitions/service.py` as `ALLOWED_TRANSITIONS` graph + `transition_requisition_status()`. Port as a pure function in `internal/requisitions/service.go`.

---

## 4. Auth & Permission System

| Mechanism | Python (current) | Go (target) |
|---|---|---|
| **Auth library** | Starlette `SessionMiddleware` (`itsdangerous`) | **Goth** + `gorilla/sessions` cookie store |
| **Session store** | Signed cookie, `itsdangerous` HMAC | `gorilla/sessions` cookie store (HMAC, compatible semantics) |
| **Cookie name** | `session` (max-age 7 days) | Same cookie name, same max-age |
| **Auth lookup** | `request.session.get("user_id")` -> DB fetch | Echo middleware: `c.Get("user")` after middleware fetch |
| **OAuth providers** | None (email-only, no password hashing) | Goth allows adding providers later without refactoring sessions |
| **Roles** | `procurement`, `qc_receiver`, `management`, `admin` | Same 4 strings |
| **Granular flags** | `can_view_quotations`, `can_do_qc`, `can_view_all_requisitions`, `is_management` | Same 4 boolean columns |
| **Dependency injection** | FastAPI `Depends(get_current_user)` | Echo `c.Get("user")` + per-group middleware |

### Role Properties (Port as Methods on `UserProfile` Struct)

| Property | Logic |
|---|---|
| `IsProc()` | role in `{procurement, management, admin}` OR `IsManagement` OR `CanViewQuotations` |
| `CanCreateRequisitions()` | role in `{procurement, management, admin}` OR `IsManagement` |
| `CanSeeQuotes()` | `CanViewQuotations` OR `IsManagement` OR role in `{management, admin}` |
| `CanPerformQC()` | `CanDoQC` OR `IsManagement` OR role in `{qc_receiver, management, admin}` |
| `HasManagementAuthority()` | `IsManagement` OR role in `{management, admin}` |
| `CanSeeAllRequisitions()` | `HasManagementAuthority()` OR `CanPerformQC()` OR `CanViewAllRequisitions` |

### Login Logic (No Passwords)

Current implementation stores **no passwords**. Login is email-only — if the email exists in the DB, the user is authenticated. If not found in dev mode, a profile is auto-created with role inferred from email content. This must be preserved exactly.

> **Note on Goth**: Goth is primarily an OAuth2/social login library. For this app's current email-only flow, Goth provides the session management infrastructure. The right choice because it makes adding OAuth providers (Google, GitHub, etc.) trivial in the future without changing session architecture.

---

## 5. External Integrations

| Integration | Python | Go equivalent |
|---|---|---|
| **Email** | `resend` Python SDK + `asyncio.to_thread()` | `resend-go/v2` (official Go SDK, batch supported natively) |
| **File Storage** | Raw `httpx` -> Supabase Storage REST API | Raw `net/http` — identical REST endpoints |
| **Database** | `asyncpg` (prod) / `aiosqlite` (dev) | `pgx/v5` + `pgxpool` |

### Email Flows (4 total — all must be ported)

| Flow | Trigger | Recipients |
|---|---|---|
| `build_vendor_invitation` | Vendor selected for requisition | Vendor email + CC list |
| `build_submission_notification` | Vendor submits quotation | Procurement + CC list |
| `build_submission_confirmation` | Vendor submits quotation | Vendor email (confirmation to sender) |
| `build_decision_notification` | Decision approved/rejected | Winning/losing vendor + CC list |

**CC list**: Loaded from `system_settings.cc_emails` (JSON array). In-memory TTL cache (5 min). Falls back to `DEFAULT_CC` env var. Must invalidate on Settings update. Port using a `sync.RWMutex`-protected cache struct.

### Supabase Storage — Two Upload Use Cases

| Use Case | Path format | Triggered by |
|---|---|---|
| Vendor quotation image | `quotations/{rv_id}/{uuid}.{ext}` | `POST /vendor-quote/{token}` |
| Delivery/QC photo | `delivery/{req_id}/{uuid}.jpg` | `POST /requisitions/{req_id}/receive` |

Both use the same `upload_file()` function. Port as a single `storage.UploadFile()` in Go.

---

## 6. Frontend Architecture (Survives Intact)

| Layer | Technology | Notes |
|---|---|---|
| CSS | Tailwind CSS via CDN | No build step — copy `<script>` tag into Templ layout |
| Client dynamics | HTMX 2.0.4 via CDN | All `hx-*` attributes survive unchanged |
| Apple Spinner | Inline JS in `base.html` | Intercepts all `<a>` clicks + HTMX events; port verbatim into `base.templ` |
| Flash messages | Session-stored, `hx-trigger="load delay:3s"` | Implement Go flash middleware reading `gorilla/sessions` flash |
| Kanban view | CSS Grid + HTMX | Port template structure; server-side logic is a simple status grouping |

---

## 7. Breaking Changes Inventory

### 🔴 Critical

| # | Item | Why it breaks |
|---|---|---|
| B1 | **30 Jinja2 templates -> Templ** | `{% block %}`, `{% macro %}`, `{% for %}`, `{% if %}`, `{{ request }}` are syntactically incompatible with Go. Every template must be rewritten as a `.templ` file. HTMX attributes and Tailwind classes survive. |
| B2 | **SQLAlchemy ORM + `selectinload` -> sqlc** | 8 model files with `relationship()`, lazy `selectin`, M2M helpers. All become explicit SQL queries generated by sqlc. `selectinload` becomes explicit JOINs. |
| B3 | **Active user sessions break on cutover** | `itsdangerous`-signed cookie format is incompatible with `gorilla/sessions`. Every logged-in user gets force-logged-out on deployment day. |
| B4 | **`init_db()` 166-line DDL guard -> proper migrations** | The runtime `ALTER TABLE` schema evolution hack must be converted to numbered `golang-migrate` SQL files **before** any other phase begins. |
| B5 | **`form_data` JSON column in `quotations`** | SQLAlchemy handles JSON natively. In Go/sqlc this requires `pgtype.JSONB` + a typed `QuotationFormData` Go struct for marshaling. |

### 🟠 High Risk

| # | Item | Notes |
|---|---|---|
| B6 | **FastAPI `Depends()` injection chain -> Echo middleware** | 46 protected routes each use `get_current_user` + property-based role checks. In Go: per-router-group Echo middleware (`e.Group("/vendors", AuthMiddleware, RequireManagement)`). Must be rebuilt systematically. |
| B7 | **Supabase Storage (no Go SDK)** | Replicate 3 REST calls: `GET /bucket` (list), `POST /bucket` (create), `POST /object/{bucket}/{path}` (upload) using `net/http`. |
| B8 | **Resend batch email with dynamic CC** | `resend-go/v2` supports batch. The DB-loaded CC list with TTL cache must be ported using a mutex-protected cache. |
| B9 | **Complex dashboard aggregate queries** | `GET /` runs 6 concurrent aggregate queries + lead-time calculation. Port as explicit `pgx.QueryRow()` or sqlc named queries. |
| B10 | **Requisition state machine** | `transition_requisition_status()` with `ALLOWED_TRANSITIONS` graph and inline audit logging. Port as pure Go function. |

### 🟡 Medium

| # | Item | Notes |
|---|---|---|
| B11 | Flash message middleware | Python: `request.session["flash"]`. Go: Echo middleware reading/writing `gorilla/sessions` flash key. |
| B12 | Audit log inline hooks | `log_action()` called in ~15 route handlers. Port as `audit.LogAction(ctx, db, actor, action, ...)`. |
| B13 | `pydantic-settings` config | Becomes `godotenv` + typed `Config` struct. Low effort. |
| B14 | Multipart file upload | `python-multipart` -> `c.Request().FormFile("file")` in Echo. |
| B15 | Lifespan events | `init_db()` + bucket check -> `main()` init block before `e.Start()`. |
| B16 | Temporary vendor creation | `add-temporary-vendor` creates Vendor + RequisitionVendor in one transaction. Ensure atomicity with `pgx.BeginTx()`. |
| B17 | Vercel deployment | Python: `api/index.py` ASGI adapter. Go: `api/index.go` + `vercel.json` update. |

### ✅ Survives Intact

| Component | Why |
|---|---|
| HTMX attributes in templates | Client-side JS — framework-agnostic |
| Tailwind CSS (CDN) | No server-side dependency |
| Apple Spinner JS | Pure inline JS — copy verbatim into Templ layout |
| PostgreSQL schema & all data | Language-neutral; same Supabase project |
| Supabase project (DB + Storage) | External service, unchanged |
| Resend account | External service, unchanged |
| Business logic & workflow rules | Ports directly |
| `.env` variable names | Just change the loader library |
| Static files | Move to `embed.FS` |

---

## 8. Target Go Project Structure

```
wes-vendor/
├── api/
│   └── index.go                # Vercel serverless entrypoint
├── cmd/
│   └── server/
│       └── main.go             # Echo app setup, all routes, lifespan init
├── internal/
│   ├── config/
│   │   └── config.go           # godotenv + Config struct
│   ├── db/
│   │   ├── db.go               # pgxpool setup
│   │   ├── query.sql           # All sqlc SQL queries
│   │   ├── schema.sql          # Reference schema
│   │   └── *.go                # sqlc-generated files
│   ├── auth/
│   │   ├── middleware.go       # GetCurrentUser(), RequireRole(), RequireManagement()
│   │   ├── handlers.go         # login, signup, logout, seed-db
│   │   └── models.go           # UserProfile struct, role constants, computed methods
│   ├── vendors/
│   │   └── handlers.go
│   ├── categories/
│   │   └── handlers.go
│   ├── requisitions/
│   │   ├── handlers.go
│   │   ├── receive.go          # QC/receive workflow
│   │   └── service.go          # State machine: TransitionStatus()
│   ├── quotations/
│   │   ├── internal.go         # inbox, detail, compare, status update
│   │   └── vendor.go           # Public: token-guarded form + submit
│   ├── decisions/
│   │   └── handlers.go
│   ├── reports/
│   │   └── handlers.go
│   ├── users/
│   │   └── handlers.go
│   ├── settings/
│   │   └── handlers.go
│   ├── audit/
│   │   ├── handlers.go
│   │   └── service.go          # LogAction()
│   ├── email/
│   │   └── resend.go           # 4 email builders + CC cache + send_batch
│   └── storage/
│       └── supabase.go         # EnsureBucketExists(), UploadFile(), GetPublicURL()
├── migrations/
│   ├── 0001_initial_schema.sql
│   ├── 0002_vendors_is_temporary.sql
│   ├── 0003_vendors_created_by.sql
│   ├── 0004_user_profiles_permissions.sql
│   └── 0005_requisitions_qc_delivery.sql
├── web/
│   └── templates/              # *.templ files
│       ├── layouts/
│       │   ├── base.templ      # Dark navy sidebar layout
│       │   └── public.templ    # Public vendor-facing layout
│       ├── components/
│       │   ├── spinner.templ
│       │   ├── flash.templ
│       │   ├── forms.templ
│       │   └── status_badge.templ
│       ├── auth/
│       ├── vendors/
│       ├── categories/
│       ├── requisitions/
│       ├── quotations/
│       ├── decisions/
│       ├── reports/
│       ├── users/
│       ├── settings/
│       └── audit/
├── static/                     # Static assets (embed.FS)
├── sqlc.yaml
├── go.mod
├── go.sum
├── Makefile
└── vercel.json
```

---

## 9. Recommended Go Stack

| Layer | Library | Rationale |
|---|---|---|
| HTTP router | **Echo v4** | Best-documented Goth pairing; built-in form binding matches FastAPI patterns; `c.Get("user")` for middleware context passing |
| Auth | **Goth** | Session infrastructure now; OAuth2 providers (Google, GitHub) ready for future without refactoring |
| Sessions | **gorilla/sessions** | Cookie store with HMAC signing — used by Goth internally; matches existing `SessionMiddleware` semantics |
| DB driver | **pgx/v5** + `pgxpool` | Best-in-class Postgres driver; `NullPool` equivalent: set `MaxConns=1` for serverless |
| DB queries | **sqlc** | Type-safe generated Go code from `.sql` files; replaces SQLAlchemy ORM |
| Migrations | **golang-migrate** | Drop-in Alembic replacement; sequential SQL version files |
| Templates | **Templ** | Type-safe HTML components; Go function calls instead of Jinja2 macros; compile-time safety |
| Email | **resend-go/v2** | Official Resend Go SDK; batch send supported natively |
| Storage | **supabase-community/storage-go** | Community SDK provides typed wrappers over REST endpoints, saving manual multipart/boundary handling. |
| Config | **godotenv** | Direct `.env` parity with `pydantic-settings` |
| Vercel | **vercel-go** runtime | Go serverless adapter for Vercel |

### Why Echo Over Chi

The original report recommended Chi. Echo is better for this project because:

1. **Goth + Echo is the canonical pairing** — every Goth example, the README, and the community use Echo. Chi integration requires more boilerplate.
2. **Built-in form binding** (`c.Bind()`) — FastAPI's form parsing maps directly to Echo's, reducing porting friction.
3. **`c.Get("user")`** — cleaner than Chi's request context for passing the current user through middleware.
4. **Built-in response helpers** (`c.Redirect()`, `c.HTML()`, `c.JSON()`) — FastAPI's response patterns map directly.

---

## 10. Migration Phase Plan

> **Prerequisites before writing any code:**
> 1. Create a new Go module: `go mod init github.com/org/wes-vendor`
> 2. Install tools: `go install github.com/sqlc-dev/sqlc/cmd/sqlc@latest`, `go install -tags 'postgres' github.com/golang-migrate/migrate/v4/cmd/migrate@latest`, `go install github.com/a-h/templ/cmd/templ@latest`
> 3. Write all 5 migration SQL files (P1) — this is the foundation everything else depends on.

### Phase Breakdown

| Phase | Task | Est. |
|---|---|---|
| **P0** | Go module scaffold, Echo skeleton, `godotenv` config struct, directory structure, basic `Makefile` | ~2h |
| **P1** | **Database foundation**: Write 5 `golang-migrate` SQL files, `pgxpool` setup, write all sqlc SQL queries for all 9 models, run sqlc codegen | ~6h |
| **P2** | **Auth**: `gorilla/sessions` + Goth setup, `GetCurrentUser()` Echo middleware, `RequireRole()` / `RequireManagement()` middleware, login/signup/logout handlers, `UserProfile` struct with all 6 computed methods | ~4h |
| **P3** | **Requisitions**: 9 endpoints + 5 Templ templates + state machine service + temp vendor creation + batch Resend email invitations | ~10h |
| **P4** | **Internal quotations**: 4 endpoints + 3 Templ templates (inbox, comparison matrix, detail) | ~4h |
| **P5** | **Public vendor quote**: 2 endpoints + 3 Templ templates + token validation + multipart file upload to Supabase Storage | ~3h |
| **P6** | **Vendors**: 6 endpoints + 3 Templ templates + M2M category sync + audit log calls | ~4h |
| **P7** | **Categories**: 4 endpoints + 1 Templ template | ~1h |
| **P8** | **Decisions**: 4 endpoints + 2 Templ templates | ~3h |
| **P9** | **Reports**: 1 endpoint + 1 Templ template + aggregate lead-time SQL | ~2h |
| **P10** | **Users + Settings + Audit**: 6 endpoints + 4 Templ templates | ~3h |
| **P11** | **Dashboard** (`GET /`): 6 aggregate queries + KPI Templ template | ~3h |
| **P12** | **Email service**: `resend-go/v2` setup, 4 email builders, batch send, DB-loaded CC cache with `sync.RWMutex` TTL | ~2h |
| **P13** | **Storage service**: Supabase bucket check + file upload + public URL using raw `net/http` | ~2h |
| **P14** | **Templ layouts & components**: `base.templ` (dark navy sidebar, mobile bottom nav, Apple spinner), `public.templ`, `flash.templ`, `status_badge.templ`, `forms.templ` | ~4h |
| **P15** | **Flash middleware + global error handler + health endpoints + static files** via `embed.FS` | ~1h |
| **P16** | **Test suite port**: 13 unit tests -> Go `testing` package | ~3h |
| **P17** | **Vercel deployment**: `api/index.go` serverless entrypoint, `vercel.json` update, build config | ~1.5h |
| **P18** | **Integration QA**: Run the full app, fix routing bugs, fix template rendering issues, fix DB query mismatches, verify all HTMX partials, test both upload flows | ~8h |

### Totals

| Scenario | Agent-Hours | ~Real Wall-Clock |
|---|---|---|
| Optimistic (clean first passes) | ~50h | ~4–5 hrs |
| **Realistic (normal error rate)** | **~65–75h** | **~6–9 hrs** |
| Pessimistic (high complexity in P5, P14, P18) | ~90h | ~10–13 hrs |

> **Core-First Strategy**: The plan above deliberately places Requisitions and Quotations (P3-P5) *before* basic CRUD modules like Vendors and Categories (P6-P7). This prioritizes the most complex and critical business logic (state machine, HTML component trees) early to de-risk the migration.
>
> **Recommended checkpoints**: Validate after P2 (auth), P3 (requisitions), P5 (vendor upload), P11 (dashboard), P18 (full QA).

---

## 11. Critical Implementation Notes

### 11.1 golang-migrate SQL Files (Do This First — P1)

The 166-line `init_db()` represents the full schema evolution history. Convert to 5 numbered files. The production DB already has all columns applied — these migrations bring Go's schema tracking in sync with reality. Run with `--skip-version-check` on first deploy.

```sql
-- migrations/0001_initial_schema.sql
-- Full schema: user_profiles, categories, vendors, vendor_categories,
-- requisitions, requisition_vendors, quotations, decisions,
-- audit_logs, system_settings (the full original schema without the later-added columns)

-- migrations/0002_vendors_is_temporary.sql
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS is_temporary BOOLEAN DEFAULT FALSE;

-- migrations/0003_vendors_created_by.sql
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS created_by VARCHAR(36) REFERENCES user_profiles(id);

-- migrations/0004_user_profiles_permissions.sql
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS can_view_quotations BOOLEAN DEFAULT FALSE;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS can_do_qc BOOLEAN DEFAULT FALSE;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS can_view_all_requisitions BOOLEAN DEFAULT FALSE;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS is_management BOOLEAN DEFAULT FALSE;

-- migrations/0005_requisitions_qc_delivery.sql
ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS delivery_image_url VARCHAR(512);
ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS qc_done BOOLEAN DEFAULT FALSE;
ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS qc_done_by VARCHAR(36) REFERENCES user_profiles(id);
ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS qc_done_at TIMESTAMPTZ;
ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS invoice_url VARCHAR(512);
ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS invoice_number VARCHAR(255);
ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS payment_status VARCHAR(50) DEFAULT 'pending';
```

### 11.2 UserProfile Struct & Methods (P2)

sqlc generates the DB columns but NOT the computed properties. Define them as methods:

```go
// internal/auth/models.go
type UserProfile struct {
    ID                     string
    Email                  string
    FullName               string
    Role                   string  // "procurement", "qc_receiver", "management", "admin"
    CanViewQuotations      bool
    CanDoQC                bool
    CanViewAllRequisitions bool
    IsManagement           bool
    IsActive               bool
    CreatedAt              time.Time
    UpdatedAt              time.Time
}

func (u *UserProfile) CanSeeQuotes() bool {
    return u.CanViewQuotations || u.IsManagement ||
        u.Role == "management" || u.Role == "admin"
}

func (u *UserProfile) CanPerformQC() bool {
    return u.CanDoQC || u.IsManagement ||
        u.Role == "qc_receiver" || u.Role == "management" || u.Role == "admin"
}

func (u *UserProfile) HasManagementAuthority() bool {
    return u.IsManagement || u.Role == "management" || u.Role == "admin"
}

func (u *UserProfile) CanSeeAllRequisitions() bool {
    return u.HasManagementAuthority() || u.CanPerformQC() || u.CanViewAllRequisitions
}

func (u *UserProfile) CanCreateRequisitions() bool {
    return u.IsManagement || u.Role == "procurement" ||
        u.Role == "management" || u.Role == "admin"
}
```

### 11.3 Goth + Echo Session Setup (P2)

Goth manages the session store. For email-only login (no OAuth provider yet):

```go
// cmd/server/main.go
import (
    "github.com/gorilla/sessions"
    "github.com/markbates/goth/gothic"
)

store := sessions.NewCookieStore([]byte(cfg.SecretKey))
store.MaxAge(86400 * 7)  // 7 days, matching Python
gothic.Store = store

// Auth middleware
func AuthMiddleware(next echo.HandlerFunc) echo.HandlerFunc {
    return func(c echo.Context) error {
        sess, _ := gothic.Store.Get(c.Request(), "session")
        userID, ok := sess.Values["user_id"].(string)
        if !ok || userID == "" {
            return c.Redirect(http.StatusFound, "/auth/login")
        }
        user, err := queries.GetUserByID(c.Request().Context(), userID)
        if err != nil || !user.IsActive {
            return c.Redirect(http.StatusFound, "/auth/login")
        }
        c.Set("user", &user)
        return next(c)
    }
}
```

### 11.4 CC Email Cache with TTL (P12)

Port the 5-minute TTL cache using Go idioms:

```go
type ccEmailCache struct {
    mu        sync.RWMutex
    emails    []string
    expiresAt time.Time
}

func (c *ccEmailCache) Get(ctx context.Context, q *db.Queries) []string {
    c.mu.RLock()
    if time.Now().Before(c.expiresAt) {
        emails := c.emails
        c.mu.RUnlock()
        return emails
    }
    c.mu.RUnlock()

    c.mu.Lock()
    defer c.mu.Unlock()
    // Double-check after acquiring write lock
    if time.Now().Before(c.expiresAt) {
        return c.emails
    }
    row, err := q.GetSystemSetting(ctx, "cc_emails")
    if err == nil {
        json.Unmarshal([]byte(row.Value), &c.emails)
    }
    c.expiresAt = time.Now().Add(5 * time.Minute)
    return c.emails
}

func (c *ccEmailCache) Invalidate() {
    c.mu.Lock()
    c.expiresAt = time.Time{}
    c.mu.Unlock()
}
```

### 11.5 Quotation `form_data` JSON (P1 / P6)

Define a typed struct matching the Python dict:

```go
type QuotationFormData struct {
    Price        float64 `json:"price"`
    Currency     string  `json:"currency"`
    DeliveryDays int     `json:"delivery_days"`
    PaymentTerms string  `json:"payment_terms"`
    Warranty     string  `json:"warranty"`
}
```

In sqlc, declare the `form_data` column as `json` type and use `json.Marshal`/`json.Unmarshal` in the handlers. For pgx: `pgtype.Text` with manual JSON handling, or use `pgx/v5` JSON scanning.

### 11.6 Vercel Go Serverless Entry (P17)

```go
// api/index.go
package handler

import (
    "net/http"
    "sync"
    "github.com/org/wes-vendor/cmd/server"
)

var (
    once    sync.Once
    handler http.Handler
)

func Handler(w http.ResponseWriter, r *http.Request) {
    once.Do(func() {
        handler = server.NewApp()
    })
    handler.ServeHTTP(w, r)
}
```

```json
// vercel.json
{
  "functions": {
    "api/index.go": { "runtime": "go1.22.x" }
  },
  "routes": [
    { "src": "/static/(.*)", "dest": "/static/$1" },
    { "src": "/(.*)", "dest": "/api/index.go" }
  ]
}
```

Note: Vercel serverless functions are stateless per-invocation. `pgxpool` with low `MaxConns` (1–2) is required. Consider Railway or Fly.io if connection pooling becomes an issue.

### 11.7 Jinja2 → Templ Syntax Mapping

| Jinja2 | Templ equivalent |
|---|---|
| `{% extends "base.html" %}` | Pass layout as a component parameter; call `base(user, title){ content }` |
| `{% block content %}...{% endblock %}` | `{ children... }` slot in Templ |
| `{% macro status_badge(status) %}` | `templ StatusBadge(status string) { ... }` |
| `{% for vendor in vendors %}` | `for _, vendor := range vendors { }` |
| `{% if user.can_see_quotes %}` | `if user.CanSeeQuotes() { }` |
| `{{ vendor.company_name }}` | `{ vendor.CompanyName }` |
| `{% include "components/flash.html" %}` | `@flash.Flash(flashMsg)` |
| `hx-post="/vendors"` | Unchanged — survives verbatim |
| `hx-trigger="load delay:3s"` | Unchanged |

**Automated Template Translation Workflow**: Manually porting 30 templates is tedious and error-prone. Since HTML, Tailwind, and HTMX structure remain perfectly intact, use an LLM prompt specifically designed as a Jinja2-to-Templ transpiler. Feed it files one by one asking it to *only* swap control structures (`{% if %}` → `if`) while preserving raw HTML verbatim.

### 11.8 HTMX-Aware Error Handling

The Python app relies heavily on HTMX, which expects HTML partials, not JSON, even for errors. Create a specialized Echo custom HTTP error handler (`e.HTTPErrorHandler`) that checks for the `HX-Request: true` header. If present, it should return a localized `<div class="bg-red-500 text-white p-4 rounded">...</div>` snippet rather than a JSON 500 error that HTMX would otherwise swallow silently.

---

## 12. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Template rendering bugs / missed HTMX partials | High | High | Port templates one module at a time; QA each before moving on |
| DB query regressions (ORM -> raw SQL) | High | High | Port queries alongside their unit tests; test against staging DB |
| Session/auth cutover (forced re-login) | Certain | Low (one-time) | Announce maintenance window; users re-login once |
| Supabase Storage upload regressions | Medium | High | Test both upload paths (quotation + delivery) explicitly before go-live |
| Vercel cold-start + pgxpool | Medium | Medium | Set `MaxConns=1`; use `sync.Once` for handler initialization |
| CC email cache race condition | Low | Low | Use `sync.RWMutex` pattern as shown above |
| `form_data` JSON deserialization mismatch | Medium | Medium | Write a unit test for full `QuotationFormData` round-trip |
| Requisition state machine edge cases | Medium | High | Port Python state machine unit tests to Go first; test before porting the route handler |
| Temporary vendor creation atomicity | Low | High | Wrap `INSERT INTO vendors` + `INSERT INTO requisition_vendors` in a single `pgx.BeginTx()` transaction |

---

## 13. Environment Variables (unchanged names)

```bash
# Database
DATABASE_URL=postgresql://postgres:password@db.project.supabase.co:5432/postgres

# Supabase Storage
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# Email
RESEND_API_KEY=re_xxxxxxxxx
MAIL_FROM=onboarding@resend.dev
DEFAULT_CC=email@example.com

# App
SECRET_KEY=change-this-to-random-secret-minimum-32-chars
DEBUG=true
ENABLE_SEED_ENDPOINT=false
PORT=8000
```

Load in Go: `godotenv.Load()` at startup, then `os.Getenv()` into a typed `Config` struct.

---

## 14. Files That Do NOT Need to Be Ported

| File | Reason |
|---|---|
| `app/requisitions/receive_routes.py` | Orphaned duplicate, never imported in `main.py` |
| `api/index.py` | Vercel Python entrypoint, replaced by `api/index.go` |
| `migrations/versions/` | Empty — replaced by `migrations/000*.sql` |
| `test_*.py` (root level) | Ad-hoc dev scripts, not part of the test suite |
| `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako` | Replaced by `golang-migrate` |
| `pyproject.toml`, `requirements.txt`, `runtime.txt`, `uv.lock` | Python-specific |
| `Procfile` | Heroku Python ASGI — replaced by Go binary / Vercel |
| `wes_vendor.egg-info/` | Python packaging artifact |
| `test_venv/` | Python virtual environment |
