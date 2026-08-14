# Development Checkpoint

This document summarizes the recent development session, tracking all changes made to the base application, bug fixes applied, and known issues/breaking changes to address in the future.

## 1. Features & Schema Changes Implemented

- **New Role (`QC_RECEIVER`)**: Added to `UserRole` enum. This role separates quality control operations from generic management.
- **Delivery & QC Tracking**: Added multiple new columns to the `Requisition` model:
  - `qc_done` (Boolean)
  - `qc_done_by` (String)
  - `qc_done_at` (DateTime)
  - `delivery_image_url` (String)
  - `invoice_url` (String)
  - `invoice_number` (String)
  - `payment_status` (String, default `pending`)
- **Receive & QC Workflow**: Created the `/receive` route and a new template (`requisitions/receive.html`) allowing Management/QC roles to mark a decided requisition as received, providing a delivery image, invoice, and tracking who did the QC check.
- **Reporting & Stats**: 
  - Added a `/reports` endpoint to track delivery times (from Decided -> QC Done) and overall operational stats.
  - Implemented 4 new WENER-styled dashboard tiles on `index.html` (Open Orders, Delivered, Pending Payment, Generate Reports).
- **Apple-Style UX Loading Spinners**: Added `apple_spinner.html` component to `base.html` that intercepts network requests, HTMX swaps, and link clicks, providing visual feedback on low-resource environments.

## 2. Bug Fixes Applied

- **AmbiguousForeignKeysError**: The `Requisition` model was crashing with a 500 Server Error because it had two relationships (`creator` and `qc_receiver_user`) pointing to the same `UserProfile` table. Fixed by explicitly defining `foreign_keys=[created_by]` and `foreign_keys=[qc_done_by]`.
- **Auth Page Styling**: The `signup.html` and `login.html` pages were rendering white text on a white background. Fixed by modifying `base.html` to accept a dynamic `{% block body_class %}` and injecting `bg-brand-600` specifically into the authentication pages to restore the dark blue gradient background.
- **Missing Imports (500 Errors)**: 
  - Fixed a crash on the `/receive` route by correctly importing `UserRole` in `app/requisitions/routes.py`.
  - Fixed an `ImportError` on the Dashboard caused by an incorrect import name (`VendorRequisitionLink` instead of `RequisitionVendor` in `app/main.py`), which was breaking the stat tiles (rendering them as `—`).

## 3. Known Issues & Breaking Changes (To Fix Later)

- **Legacy Data 500 Error on `/receive`**: Clicking the "Receive & QC Items" button on older mocked requisitions (created before the `RequisitionVendor` relationship logic was fully implemented) throws a 500 Server Error. The `/receive` route expects to find an accepted vendor quote, but legacy data is missing these associations.
- **Alembic Migration Limitations**: Alembic `autogenerate` struggles with the async SQLAlchemy setup. Database schema modifications (like adding the `qc_done` fields) were implemented safely via functional `ALTER TABLE` raw SQL checks directly in `database.py` (`init_db`). A proper Alembic async configuration should be established for future schema changes.
- **Apple Spinner Aggressiveness**: The Apple-style loading spinner triggers on *all* `<a>` clicks, which can be visually jarring on simple local navigation. This may need to be refined to only trigger on forms, HTMX, and heavy transitions.
