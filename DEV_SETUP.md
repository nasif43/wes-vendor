# Developer Setup Guide

Quick-start guide for resuming development on a new machine.

## Prerequisites

- Python 3.11+
- `uv` package manager (recommended) or `pip`
- PostgreSQL 14+ (for production-like dev) or SQLite (default for quick dev)

## Quick Start

```bash
# 1. Clone and checkout the right branch
git clone git@github.com:nasif43/wes-vendor.git
cd wes-vendor
git checkout vps-deployment

# 2. Create virtual environment and install dependencies
uv sync
# OR with pip:
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — minimum required:
#   SECRET_KEY=any-random-string
#   RESEND_API_KEY=re_your_key  (or leave as dummy to skip emails)
#   APP_URL=http://localhost:8000

# 4. Start the dev server (SQLite auto-created)
make dev
# Server starts at http://localhost:8000
# Schema migrations run automatically on startup

# 5. Create your first user
# Visit http://localhost:8000/auth/signup
```

## Test Users (Recommended Seed)

For testing all role scenarios, create these users via `/auth/signup` or the admin panel:

| Email | Role | Purpose |
|-------|------|---------|
| `procurement@wes.com` | Procurement | Creates requisitions, invites suppliers |
| `management@wes.com` | Management | Reviews quotes, shortlists, selects winners |
| `qc@wes.com` | QC Receiver | Receives items, logs QC results |
| `admin@wes.com` | Admin | Full access |

## Development Database

| Env | Database | How to reset |
|-----|----------|--------------|
| Dev (default) | SQLite `dev.db` | `rm dev.db && make dev` |
| Dev (postgres) | Set `DATABASE_URL` in `.env` | `dropdb wes_vendor && createdb wes_vendor && make dev` |

Schema changes are applied automatically on startup via `app/database.py:init_db()`.

## Useful Make Commands

```bash
make dev        # Start uvicorn with hot reload on port 8000
make test       # Run full test suite
make test-unit  # Run unit tests only (fast)
make lint       # Run ruff linter
```

## Switching Devices

Everything needed to resume:
1. `git pull origin vps-deployment` — get latest code
2. `uv sync` — sync dependencies
3. `cp .env.example .env` + fill in your values — or copy your existing `.env`
4. `make dev` — start server
5. Read `CHECKPOINT.md` — see current status and known issues
6. Read `ARCHITECTURE.md` — understand module layout
7. Read `LIFECYCLE.md` — understand the procurement flow

## Key Files to Know

| File | Purpose |
|------|---------|
| `app/database.py` | DB schema migrations (raw SQL in `init_db()`) |
| `app/requisitions/service.py` | State machine (`ALLOWED_TRANSITIONS`) |
| `app/email/resend.py` | All email builders |
| `app/work_orders/service.py` | Work order PDF generation + rating creation |
| `app/main.py` | Router registration — add new routers here |
| `CHECKPOINT.md` | Current dev status and known issues |
