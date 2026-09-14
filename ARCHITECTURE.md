# WES Vendor Portal — Architecture Reference

> **Living document.** Update this file after significant structural changes.

## Module Map

| Module | Responsibility |
|--------|---------------|
| `app/auth/` | UserProfile model, login/signup routes, session management |
| `app/audit/` | AuditLog model + service (`log_action`) |
| `app/categories/` | Category model (used to tag vendors) |
| `app/decisions/` | Legacy Decision model (winner selection). New code uses `work_orders/`. |
| `app/email/` | Resend email service — all builders in `resend.py` |
| `app/quotations/` | Quotation model, internal compare/inbox routes, public vendor submission routes |
| `app/requisitions/` | Core procurement models + routes |
| `app/reports/` | Reporting and stats endpoints |
| `app/settings/` | SystemSettings (CC emails, letterheads) |
| `app/storage/` | File upload abstraction (local filesystem on VPS) |
| `app/users/` | User management (CRUD by management/admin) |
| `app/vendors/` | Vendor model + management routes |
| `app/work_orders/` | WorkOrder + SupplierRating models, PDF generation, email dispatch |
| `app/main.py` | FastAPI app factory, middleware, router registration, dashboard |
| `app/database.py` | Async engine, Base, `init_db()` (schema migrations via raw SQL) |

## Naming Convention

**CRITICAL:** This codebase has a naming split:

| Layer | Term Used | Example |
|-------|-----------|--------|
| Database tables | `vendor` | `vendors`, `requisition_vendors` |
| ORM models | `Vendor`, `vendor` | `from app.vendors.models import Vendor` |
| Python routes/services | `vendor` | `vendor_id`, `winning_vendor_id` |
| **Jinja2 templates** | `supplier` | `{{ supplier.company_name }}` |
| **HTML user-visible text** | Supplier | "Select Suppliers", "Invited Suppliers" |
| **Email copy** | Supplier | "Dear Supplier," |

When passing data to templates, use the alias pattern:
```python
# routes.py
vendors = result.scalars().all()
return templates.TemplateResponse(request, "...", {
    "suppliers": vendors,  # Jinja alias: 'suppliers' = Vendor ORM objects
})
```

## Requisition Lifecycle (State Machine)

```
DRAFT → NEW → IN_PROGRESS → NEGOTIATING → AWARDED → WORK_ORDER_ISSUED → RECEIVING → CLOSED
                                         ↓
                                      CANCELLED / REJECTED
```

| Status | Who triggers | What it means |
|--------|-------------|---------------|
| `DRAFT` | Procurement creates | Created, no suppliers invited |
| `NEW` | Procurement invites suppliers | v1 quote links sent |
| `IN_PROGRESS` | First quote received | Quotes under management review |
| `NEGOTIATING` | Management shortlists + starts v2 | Rejected suppliers notified, shortlisted get v2 links |
| `AWARDED` | Management selects winner | Winner notified, procurement issues work order |
| `WORK_ORDER_ISSUED` | Procurement issues WO | Work order PDF sent to winner, delivery timer starts |
| `RECEIVING` | Receiver logs first items | Items being received |
| `CLOSED` | Receiver finalizes | Invoice generated, supplier rating saved, timer stopped |

Legacy statuses `SUBMITTED` and `RECEIVED` are kept for backward compat with existing data.

## Role Permission Matrix

| Action | Procurement | Management | QC Receiver | Admin |
|--------|:-----------:|:----------:|:-----------:|:-----:|
| Create Requisition | ✅ | ✅ | ❌ | ✅ |
| Invite Suppliers | ✅ | ❌ | ❌ | ✅ |
| View Quotation Prices | ❌* | ✅ | ❌ | ✅ |
| Compare Quotations | ❌* | ✅ | ❌ | ✅ |
| Shortlist Suppliers | ❌ | ✅ | ❌ | ✅ |
| Start Negotiation | ❌ | ✅ | ❌ | ✅ |
| Select Winner | ❌ | ✅ | ❌ | ✅ |
| Issue Work Order | ✅ | ❌ | ❌ | ✅ |
| Receive Items (QC) | ❌ | ✅ | ✅ | ✅ |
| Manage Letterheads | ❌ | ✅ | ❌ | ✅ |
| View Supplier Ratings | ✅ | ✅ | ✅ | ✅ |

*Unless `can_view_quotations` flag is set by management.*

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes (prod) | PostgreSQL connection string. Defaults to SQLite for dev. |
| `SECRET_KEY` | Yes | Session signing key. Change in production! |
| `RESEND_API_KEY` | Yes | Resend.com API key for email delivery. |
| `MAIL_FROM` | Yes | Verified sender email address. |
| `DEFAULT_CC` | No | Comma-separated default CC emails (seeded to DB). |
| `APP_URL` | Yes | Public base URL (e.g., `https://yourapp.com`). Used for file URLs. |
| `UPLOAD_DIR` | No | Local filesystem upload path. Default: `/var/wes-vendor/uploads`. |
| `DEBUG` | No | Set `false` in production (disables API docs). |

## Database Migration Strategy

Migrations are handled via `app/database.py:init_db()` using raw SQL `ALTER TABLE ADD COLUMN IF NOT EXISTS` statements (for PostgreSQL) and PRAGMA-based checks (for SQLite). This runs on every app startup — changes are idempotent.

**Adding a new column:**
```python
# In init_db(), PostgreSQL branch:
for col, defn in [
    ("new_column", "VARCHAR(255)"),
]:
    if not col_exists("table_name", col):
        await conn.execute(text(f"ALTER TABLE table_name ADD COLUMN {col} {defn}"))
```

**SQLite equivalent must also be added** in the `else:` branch.

> ⚠️ Alembic autogenerate does not work with the current async setup. Do not use it without proper async configuration.

## File Upload Storage

Files are stored on the local filesystem at `UPLOAD_DIR` and served via `/uploads/*` static route.

| Path Pattern | Contents |
|-------------|----------|
| `uploads/quotations/{link_id}/{uuid}.jpg` | Supplier quotation images |
| `uploads/deliveries/{req_id}/{uuid}.jpg` | Delivery photos |
| `uploads/invoices/{req_id}/{uuid}.pdf` | Invoice PDFs |
| `uploads/work_orders/{wo_id}/{uuid}.pdf` | Work order PDFs |
| `uploads/letterheads/{uuid}.jpg` | Company letterhead images |
