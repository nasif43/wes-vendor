# Development Checkpoint

This document tracks current development status, recent changes, and open issues.
Update this after each significant development session.

## Current Branch: `vps-deployment`

## Phase Status

| Phase | Status | Commit | Notes |
|-------|--------|--------|-------|
| Phase 0: Naming cleanup | ⏳ In Progress | — | Template context keys being standardized |
| Phase 1: Schema & Models | ✅ Done | 8b8909b | New models: ShortlistedItem, ReceivedItem, WorkOrder, SupplierRating; fixed Quotation unique bug |
| Phase 2: State Machine | ✅ Done | TBD | New statuses, fixed transitions, winner selection is real |
| Phase 3: Features | 🔜 Next | — | Per-item shortlisting UI, tabular receiving, invoice PDF, supplier ratings |
| Phase 4: Email Overhaul | 🔜 Next | — | New email builders, proper PDF attachments |
| Phase 5: Modularization | ✅ Done | TBD | routes.py split into 3 focused files |
| Phase 6: Documentation | ✅ Done | TBD | ARCHITECTURE.md, DEV_SETUP.md, LIFECYCLE.md created |
| Phase 7: Tests | 🔜 Next | — | Unit + integration + E2E test suite |

## Recent Changes (Phase 1)

- **Fixed critical bug:** `Quotation.requisition_vendor_id` had `unique=True` — prevented v2 revised quotes. Now uses composite unique (requisition_vendor_id, quote_version).
- **New models:** `ShortlistedItem`, `ReceivedItem`, `WorkOrder`, `SupplierRating`
- **New statuses:** `NEGOTIATING`, `AWARDED`, `WORK_ORDER_ISSUED`, `RECEIVING`
- **New module:** `app/work_orders/` with routes, service, and placeholder templates
- **Bug fix:** `settings/routes.py` letterhead upload was missing `await db.commit()`
- **`negotiation_version`** type fixed from `String` to `Integer`

## Known Issues

- **Legacy data:** Requisitions with `status=submitted` or `status=received` will map to legacy values. The `_missing_` handler and transition table accommodate these.
- **Alembic:** Not configured for async. All migrations in `init_db()` via raw SQL.
- **Work order templates:** Placeholder HTML only — needs proper Tailwind styling to match app design.
- **Per-item shortlisting UI:** Backend supports it (ShortlistedItem model exists) but compare.html still only does per-vendor shortlisting. Phase 3 will add per-item UI.
- **Tabular receiving:** Form exists but is single-field. Phase 3 will make it per-item tabular.

## Next Steps (Phase 3)

1. Update compare.html shortlisting UI to support per-item selection
2. Update vendor quote form to filter items based on ShortlistedItem rows (v2)
3. Rebuild receive.html as tabular per-item form
4. Auto-generate invoice PDF from ReceivedItem records
5. Create supplier performance tab on vendor detail page
