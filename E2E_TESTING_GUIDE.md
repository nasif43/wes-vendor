# Real End-to-End Testing Procedure

This document outlines the strict, multi-role sequence required to perform a complete End-to-End (E2E) workflow test on the Vendor Management Portal (`wes-vendor`).

---

## Prerequisites: Environment & Database

The app connects to a **live Supabase PostgreSQL** database when `.env` is present. All tables (including `audit_logs`) are auto-created by `init_db()` on startup. No manual schema setup is required.

```
DATABASE_URL = postgresql+asyncpg://postgres.<project>@<pooler>/postgres  ← set in .env
SUPABASE_URL / ANON_KEY / SERVICE_ROLE_KEY                                ← set in .env
RESEND_API_KEY                                                             ← set in .env
```

---

## Test User Credentials (Seeded in Supabase)

> **Login requires only email — no password check in dev mode** (auth is session-based).

| Role              | Email                            | Full Name             |
|-------------------|----------------------------------|-----------------------|
| `requester`       | `requester@wes.test`             | Aisha Requester       |
| `purchase_person` | `purchase@wes.test`              | Bilal Purchase        |
| `management`      | `management@wes.test`            | Chowdhury Management  |
| `management`      | `muhtasimhossain43@gmail.com`    | Muhtasim Hossain      |
| `management`      | `mahmudtarek1971@gmail.com`      | Tarek Mahmud (MD)     |
| `purchase_person` | `tmtnazir@gmail.com`             | Wener Vendor (Nazir)  |
| `qc_receiver`     | `qc@wes.test`                    | Dilnoza QC Receiver   |
| `admin`           | `admin@wes.test`                 | WES Admin             |

---

## Complete Multi-Role Workflow Sequence

```
[Requester] → [Vendor (Incognito)] → [Purchase Person] → [Management] → [QC Receiver]
```

### Step 1: Requester (`REQUESTER` Role)
1. Log in as **Requester** (`requester@wes.test`).
2. Navigate to `/requisitions/new` and submit a purchase requisition (title, item description, quantity, unit, notes).
3. On `/requisitions/{req_id}/select-vendors`, select enlisted active vendors and submit.
4. Verify that unique vendor token links are generated (`/vendor-quote/{token}`) and email invitations are queued/dispatched.
5. ✅ **Audit log**: `REQUISITION_CREATED` and `VENDORS_INVITED` entries appear at `/audit`.

### Step 2: Vendor (Incognito / No Auth Session)
1. Open the unique token link (`/vendor-quote/{token}`) in an incognito/unauthenticated context.
2. Fill out and submit the quotation form:
   - Unit price
   - Delivery lead time (days)
   - Payment terms
   - Warranty & guarantee information
   - Optional: Photo upload of formal quote/invoice.
3. Verify quote status updates to `submitted` in the database.

### Step 3: Purchase Person (`PURCHASE_PERSON` Role)
1. Log in as **Purchase Person** (`purchase@wes.test`).
2. Navigate to `/quotations/inbox` and verify the incoming quote.
3. Perform sanity check (accept quote and flag any mismatches).
4. Navigate to `/quotations/compare/{req_id}` to view side-by-side quote comparison.
5. Select the winning vendor quote and submit the decision. Requisition status becomes `DECIDED`.
6. ✅ **Audit log**: `DECISION_CREATED` appears at `/audit` with `Bilal Purchase`'s name.

### Step 4: Management (`MANAGEMENT` / `ADMIN` Role)
> **Management has full access**: they can also view quotation inbox, compare quotes, and create decisions — the same as Purchase Person. The nav shows **Quotations**, **Decisions**, and **Audit** tabs.

1. Log in as **Management** (`management@wes.test` or `muhtasimhossain43@gmail.com`).
2. Navigate to `/decisions` and open the pending decision detail (`/decisions/{decision_id}`).
3. Review winning vendor details and click **Approve Decision** (or Reject).
4. Verify `management_approved = True`, the approver's full name and timestamp appear on the decision card, and email notifications are dispatched to vendors.
5. ✅ **Audit log**: `DECISION_APPROVED` or `DECISION_REJECTED` appears at `/audit` with Management's name.

### Step 5a: Receive Delivery (QC Later Flow)
> **New**: You can receive delivery first and complete QC separately. The form does **not** require the QC checkbox.

1. Log in as **QC Receiver** (`qc@wes.test`) **or Management**.
2. Navigate to `/requisitions/{req_id}/receive` (button is shown on the requisition detail for `DECIDED` status).
3. Fill out invoice details:
   - Invoice number (required)
   - Invoice URL / scan (optional)
   - Delivery image URL / photo (optional)
4. Leave `qc_done` **unchecked** to mark as received only.
5. Submit form. Verify requisition status transitions to **`DELIVERED`**.
6. ✅ **Audit log**: `DELIVERY_RECEIVED` appears at `/audit`.

### Step 5b: Complete QC (Deferred Flow)
1. Navigate back to `/requisitions/{req_id}` — the **"Complete QC Inspection"** button (amber) appears on `DELIVERED` status.
2. Click it and check the `qc_done` checkbox to confirm quality passed.
3. Submit form. Verify requisition status transitions to **`CLOSED`**, `qc_done_by` records the actor's user ID, and `qc_done_at` records the timestamp.
4. ✅ **Audit log**: `QC_COMPLETED` appears at `/audit` with the actor's full name and email.

---

## Audit Log Verification
1. Log in as **Management** or **Admin**.
2. Navigate to `/audit`.
3. You should see a chronological list of all actions with:
   - Action type (colour-coded)
   - Entity label (requisition/decision title)
   - Actor full name, email, and role at time of action
   - Timestamp

---

## Supabase Connection Check
Run this locally to verify the live database is connected and all tables exist:
```bash
cd wes-vendor
source .venv/bin/activate
python3 -c "
import asyncio
from app.database import init_db, engine
from sqlalchemy import text

async def check():
    await init_db()
    async with engine.begin() as conn:
        res = await conn.execute(text(\"SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name\"))
        print([r[0] for r in res.fetchall()])

asyncio.run(check())
"
```
Expected tables: `audit_logs`, `categories`, `decisions`, `quotations`, `requisition_vendors`, `requisitions`, `user_profiles`, `vendor_categories`, `vendors`.
