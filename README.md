# Vendor Management Portal

Internal tool for creating purchase requisitions, sending them to enlisted vendors for quotation, collecting and comparing vendor responses, and distributing final decisions.

---

## 1. Spec

### Overview

An internal-use-only portal where requesters create purchase requisitions, selected vendors receive unique links to submit quotations (via image upload or structured form), purchase persons review and compare incoming quotes, and management approves final decisions.

### Core Concepts

- **Vendor** — A company enlisted internally (no self-signup). Organized into categories/groups (e.g., Laptop Vendors, Packaging Vendors). Vendors have no accounts or logins.
- **Requisition** — Created by a requester. Contains item description, quantity, unit, notes. Sent to a selected subset of enlisted vendors.
- **Vendor-Specific Links** — Each vendor+requisition pair gets a unique token-based link. The link is the identity mechanism — any quotation submitted through it is automatically attributed to that vendor. No login required.
- **Quotation Submission** — Vendors open their unique link and submit either an image (photo/scan of a quote) or fill out a structured form (price, delivery, payment terms, warranty).
- **Sanity Check** — Purchase person visually verifies that the submitted document matches the expected vendor. Manual review step, not system-enforced.
- **Comparison** — Side-by-side view of all quotations for a requisition to determine a winner.
- **Decision** — Winner is selected, management approves/rejects, outcome is distributed to the winning vendor and management via email.

### Roles

| Role | Responsibilities |
|---|---|
| Requester | Creates requisitions, selects vendors to send to |
| Purchase Person | Reviews incoming quotations, sanity checks, runs comparison, picks winner |
| Management | Approves/rejects decisions, receives final output |
| Vendor | Receives unique link, submits quotation (no account/login) |

### Workflow

```
1. Create Requisition       → Requester defines need (item, quantity, notes)
2. Select Vendors           → Requester picks enlisted vendors (filter by category)
3. Send & Generate Links    → System generates unique link per vendor, dispatches email
4. Vendor Responds          → Each vendor uses their link to submit quote
5. Intake & Sanity Check    → Purchase person reviews, flags mismatches
6. Comparison               → Side-by-side quote comparison
7. Distribute Outcome       → Winning vendor notified, management approval, distribution
```

### Key Principles

- **Internal tool, no vendor accounts.** Vendors never log in.
- **Link = Identity.** No separate auth for vendors — trust is anchored to link uniqueness.
- **Policy over enforcement.** Only enlisted vendor submissions are surfaced.
- **Human-in-the-loop verification.** Automated link attribution, manual document verification.

---

## 2. What Was Built

### Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (async, Python 3.11+) |
| Database ORM | SQLAlchemy 2.0 async + aiosqlite (dev) / asyncpg (prod) |
| Auth | Session-based with Supabase Auth (JWT) |
| Storage | Supabase Storage (quotation image uploads) |
| Email | Mailgun API via httpx |
| Frontend | Jinja2 + HTMX 2.0 + Tailwind CSS (CDN) |
| Migrations | Alembic |
| Testing | pytest (9 tests, all passing) |
| Linting | ruff |

### Features Implemented

| Module | Status | What It Does |
|---|---|---|
| **Auth** | Done | Login, signup, logout, session management |
| **Vendors** | Done | Full CRUD, category assignment, active/inactive toggle |
| **Categories** | Done | Create/delete vendor groups |
| **Requisitions** | Done | Create (title, item, qty, unit, notes), select vendors, send |
| **Vendor Quotation Form** | Done | Public form via unique token — image upload OR structured form |
| **Quotations Inbox** | Done | Purchase person view — incoming quotes with status badges |
| **Quotation Detail** | Done | View vendor info, image/form data, sanity check (accept/flag) |
| **Comparison View** | Done | Side-by-side quote comparison for a requisition |
| **Decision** | Done | Select winner, management approval workflow |
| **Email** | Done | Mailgun integration — vendor invitations + decision notifications |
| **Storage** | Done | Supabase Storage helper for file uploads |
| **Mobile UI** | Done | Bottom nav bar, responsive cards, camera capture for image uploads |
| **Tailwind + HTMX** | Done | Mobile-first design, dynamic vendor filtering, no JS build step |

### Project Structure

```
wes-vendor/
├── app/
│   ├── main.py                 # FastAPI app, lifespan, middleware, router mount
│   ├── config.py               # pydantic-settings (.env)
│   ├── database.py             # SQLAlchemy async engine + session
│   ├── dependencies.py         # Auth dependencies (get_current_user, require_role)
│   ├── auth/                   # Login, signup, logout routes + templates
│   ├── vendors/                # Vendor CRUD (models, schemas, routes, templates)
│   ├── categories/             # Category CRUD
│   ├── requisitions/           # Create → select vendors → send workflow
│   ├── quotations/             # Public vendor form + internal intake/comparison
│   ├── decisions/              # Winner selection + management approval
│   ├── email/mailgun.py        # Mailgun API client
│   ├── storage/                # Supabase Storage helpers
│   └── templates/              # Jinja2 templates (Tailwind + HTMX)
│       ├── base.html           # Main layout with mobile bottom nav
│       ├── public_base.html    # Layout for public vendor-facing pages
│       └── components/         # Reusable form macros, flash messages
├── tests/
│   └── unit/                   # 9 passing tests (SQLite, no network)
├── supabase/
│   └── schema.sql              # Full PostgreSQL schema reference
├── migrations/                 # Alembic (configured for Supabase PostgreSQL)
├── static/                     # Static assets
├── .env.example                # All environment variables documented
├── Makefile                    # dev, test, lint, typecheck, migrate
├── pyproject.toml              # Project config + tool settings
└── requirements.txt
```

### Running Tests

```bash
make test          # Unit tests (SQLite, no network)
make test-all      # All tests
make lint          # Ruff linter
make typecheck     # Mypy type checker
```

### Local Development (No Docker)

```bash
# 1. Create a free Supabase project at supabase.com
#    → Copy: project URL, anon key, service_role key, DB connection string

# 2. Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Fill in Supabase credentials

# 3. Run
make dev               # http://localhost:8000
```

The app connects to hosted Supabase for everything — no local database or Docker required.

---

## 3. What's Next

### High Priority

| Item | Description |
|---|---|
| **Email dispatch on send** | Wire up `send_vendor_invitation()` when requisition is sent — currently creates links but doesn't send emails |
| **Decision notification emails** | Wire up `send_decision_notification()` when decision is approved/rejected |
| **Distribution log table** | Implement the `distribution_logs` table from the schema for extensible output tracking (third copy target mentioned in spec) |
| **Session user in template context** | Pass `user` to all template responses so the nav bar renders correctly (currently some routes don't pass user) |
| **Supabase Auth integration** | Replace session-based auth with Supabase JWT verification for production use |
| **Fix `asyncpg` dependency** | Add `asyncpg` to requirements.txt for PostgreSQL production deployment |

### Medium Priority

| Item | Description |
|---|---|
| **Image upload to Supabase Storage** | Replace local filesystem storage with Supabase Storage for production image uploads |
| **Losing vendor notification** | Optional email to non-winning vendors after decision |
| **Requisition categories** | Allow requisitions to be filtered by category when selecting vendors |
| **Quotation form data schema** | Define and validate specific form fields beyond the current freeform JSONB |
| **User role management** | Admin page to assign roles (currently all signups are `requester`) |
| **Dashboard/stats** | Summary view of requisitions, quotations received, decisions made |

### Low Priority / Nice-to-Have

| Item | Description |
|---|---|
| **Third distribution target** | As mentioned in spec — a possible third output copy beyond vendor + management |
| **Requisition templates** | Save/load requisition templates for repeated purchases |
| **Bulk operations** | Bulk approve/reject, bulk vendor assignment |
| **Export** | Export comparison data to CSV/PDF |
| **Audit log** | Track all actions (who created, who approved, when) |
| **Dark mode** | Tailwind dark mode toggle |
| **Internationalization** | Multi-language support if needed |
| **Deployment config** | Dockerfile for Railway/Vercel deployment |

### Deployment Checklist

- [ ] Set `DATABASE_URL` to Supabase PostgreSQL connection string
- [ ] Set `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- [ ] Set `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`, `MAIL_FROM`
- [ ] Set `SECRET_KEY` to a random string
- [ ] Set `DEBUG=false` in production
- [ ] Run `make migrate` to apply schema
- [ ] Create Supabase Storage bucket for quotation images
- [ ] Configure Supabase RLS policies if needed
