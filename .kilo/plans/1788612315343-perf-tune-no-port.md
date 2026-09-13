# Plan: Performance-tune wes-vendor (no Go port)

## Goal

Make the dashboard (`GET /`) and quotations inbox/detail feel fast on the current FastAPI/SQLAlchemy/Supabase stack. Defer the Go port decision until after the cheap wins are measured.

## Why this plan, not a port

- Slowness is concentrated on two routes, not the whole app.
- A full Go port of ~6,800 LOC (3,200 Python + 3,680 templates) plus a Jinja2→Templ rewrite is a multi-week effort for a marginal perceived gain once the slow routes are fixed.
- A targeted SQL + N+1 + cache pass is the highest-leverage move and is reversible.

## Bottleneck analysis (from code)

### `GET /` dashboard — `app/main.py:137`
- 6 sequential `await db.execute(...)` calls (open, delivered, pending pay, vendors, pending decisions, confirmed, plus recent reqs + audit).
- The 3 requisition KPIs are already collapsed into one `SELECT SUM(CASE WHEN ...)` (`app/main.py:152`) — good.
- The other 4 are independent. They run serially against Supabase over a 150–300 ms RTT. **4× RTT is the floor cost today.**
- Final `qc_completion_rate` and `avg_lead_time_days` are computed in Python (`app/main.py:236`) over a JOIN result, not in SQL.

### `GET /quotations/inbox` — `app/quotations/routes_internal.py:14`
- Single query (`select(Requisition).where(status == IN_PROGRESS)`).
- But `requisitions/inbox.html` and `requisitions/detail.html` almost certainly walk `link.vendor` and `link.requisition` — typical SQLAlchemy `selectinload` lazy-load N+1. **Verify in the template; if present, this is the cost.**

### `GET /quotations/detail/{id}` — `app/quotations/routes_internal.py:37`
- Single fetch of `RequisitionVendor` by id. Likely fine on its own; slow because the template iterates vendor + requisition + audit.

### `GET /requisitions` list — `app/requisitions/routes.py:21`
- Already uses a `WHERE IN` to batch-fetch `Decision`s in one query — good.
- The Kanban stage classification is done in Python over `req.vendor_links` (`app/requisitions/routes.py:84`) — this triggers a `selectinload` per requisition. N+1 risk.

## Plan

### Phase 0 — Measure first (mandatory, ~1h)
1. Add a one-line `time.perf_counter()` timing log around each route handler in `app/main.py` and `app/quotations/routes_internal.py` and `app/requisitions/routes.py`. Log with `logger.info("route %s took %.0fms db_count=%d", path, ms, db_count)`. Use a middleware that counts `await db.execute` calls per request (wrap `AsyncSession.execute` with a counter on `request.state`).
2. In the Supabase dashboard → SQL editor, run `EXPLAIN ANALYZE` on each of the 6 dashboard queries against the production-sized dataset. Capture the plans.
3. Note the per-request baseline: total ms, DB ms, query count.

This step is the basis for every later decision. Skip it and you are guessing.

### Phase 1 — Collapse the dashboard queries (highest impact, ~2–4h)
1. **Combine the 4 independent aggregates into one round trip** using `asyncio.gather` (`app/main.py:182-227`):
   - `total_vendors`, `pending_decisions`, `confirmed_orders`, and the lead-time average.
2. **Move `avg_lead_time_days` into SQL.** Replace the Python loop (`app/main.py:230-236`) with:
   ```sql
   SELECT AVG(EXTRACT(EPOCH FROM (r.qc_done_at - d.approved_at)) / 86400.0)
   FROM requisitions r
   JOIN decisions d ON d.requisition_id = r.id
   WHERE r.qc_done = TRUE AND r.qc_done_at IS NOT NULL AND d.approved_at IS NOT NULL
     AND r.qc_done_at >= d.approved_at;
   ```
3. **Move `qc_completion_rate` into SQL** with a single `CASE` aggregate.
4. After this, `GET /` should make **2 DB round trips** instead of 6+. Expected speedup: 3–6× on the dashboard's DB-bound cost.

### Phase 2 — Kill N+1 in inbox + detail + list (~2–3h)
1. Read `app/templates/quotations/inbox.html`, `detail.html`, `compare.html`, and `app/templates/requisitions/list.html`. Identify every place that accesses a relationship attribute (`link.vendor`, `link.requisition`, `req.vendor_links`, `req.decisions`).
2. Replace any lazy-loaded `selectinload` style access with explicit eager loading. For the inbox, change the query to:
   ```python
   stmt = (
       select(Requisition)
       .where(Requisition.status == RequisitionStatus.IN_PROGRESS)
       .options(selectinload(Requisition.vendor_links).selectinload(RequisitionVendor.vendor))
       .order_by(Requisition.created_at.desc())
   )
   ```
   Same pattern for detail and list.
3. Re-run the Phase 0 timing. Query count per page should drop sharply.

### Phase 3 — Add the right indexes (low risk, ~1h)
1. From the `EXPLAIN ANALYZE` output in Phase 0, identify any `Seq Scan` on large tables.
2. Add indexes only where the planner picks a seq scan. Likely candidates based on the query shapes:
   - `requisitions(status, created_at DESC)` for the list/inbox.
   - `decisions(requisition_id, approved_at)` for lead-time.
   - `requisition_vendors(requisition_id)` (likely already indexed via FK).
3. Apply via a single new Alembic/SQL migration; do **not** keep expanding `init_db()`.

### Phase 4 — Cache the dashboard for 30s (~1h)
1. Add a `cachetools` TTLCache (or a small in-process dict) keyed by `(user_id, role, can_see_all)`.
2. Cache the `stats` dict for 30s. Do **not** cache `recent_requisitions` / `recent_audits` — those need to feel live.
3. Invalidate on any write to `requisitions` or `decisions` (a hook in the audit log service is fine).
4. Expected effect: under concurrent browsing, the dashboard becomes a single ~5ms in-process call.

### Phase 5 — HTTP caching + ETag (~30 min)
1. Set `Cache-Control: private, max-age=15` on `GET /` and `GET /quotations/inbox`.
2. Add an ETag derived from `max(requisitions.updated_at)` for the inbox so back-button navigation is a 304.
3. Cheap win; matters on Vercel because it reduces function invocations.

### Phase 6 — Vercel-side tuning (optional, ~1h)
1. Move from serverless functions to a Vercel "fluid compute" instance if available, or a Railway/Fly container. Serverless cold starts + asyncpg plan cache invalidations have bitten you already (see `prepared_statement_cache_size=0` in `app/database.py:25`).
2. If staying on Vercel: raise `max-age` on the function, set a single instance for the dashboard route via route config.

## Expected speedup (rough, with current Supabase RTT ~150–250ms)

| Route | Before | After (target) | Notes |
|---|---|---|---|
| `GET /` dashboard | ~800–1400 ms (6 round trips + Python work) | ~150–300 ms | 4× RTT reduction + SQL aggregates + 30s cache |
| `GET /quotations/inbox` | ~300–700 ms (1 query + N+1) | ~80–200 ms | Eager loading + index |
| `GET /quotations/detail/{id}` | ~250–500 ms (1 query + template lazy loads) | ~80–150 ms | Eager loading |
| `GET /requisitions` (list/kanban) | ~400–900 ms (1 query + decision batch + N vendor_link loads) | ~150–300 ms | Eager loading of vendor_links.vendor |

These are estimates based on the code shape and typical Supabase asyncpg latency. Phase 0 produces real numbers that override the table above.

## When to actually port to Go

Re-evaluate the port only if, after all 6 phases, either:
- Dashboard still measures >500 ms, or
- Concurrent users exceed ~50 and Vercel cost grows faster than feature work.

If neither, stay on Python. The Go port still has a place later (cost + concurrency ceiling), but it should be a deliberate decision backed by numbers, not a default response to "feels slow."

## Files to touch

- `app/main.py` — Phase 1 (aggregate collapse), Phase 0 timing.
- `app/quotations/routes_internal.py` — Phase 2 eager loading.
- `app/requisitions/routes.py` — Phase 2 eager loading.
- `app/audit/service.py` — Phase 4 cache invalidation hook.
- `app/database.py` — Phase 3 index migration runner (replace incremental `init_db` `ALTER TABLE`s with a proper migration; in scope only the new indexes).
- New `migrations/versions/0006_perf_indexes.sql` — Phase 3.
- `requirements.txt` — add `cachetools` (Phase 4).
- `app/templates/quotations/inbox.html`, `detail.html`, `app/templates/requisitions/list.html` — read-only audit for N+1 identification.

## Risks

- **Phase 0 not done → guessing.** Without timings you cannot prove the speedup or pick the right fix. Treat Phase 0 as non-optional.
- **`selectinload` chained** on `vendor_links.vendor` can still produce large result sets if a requisition has many vendors. Keep an eye on the result row count; add pagination if it grows.
- **Cache staleness** in Phase 4: 30s is fine for KPIs, never cache recent activity. If procurement complains about stale counts, drop to 10s or remove the cache.
- **`init_db()` is already 166 lines of unguarded DDL** (per `GOLANG_MIGRATION.md`). Do not pile more on it; if you add a new column for indexing, go through the migration. Otherwise the technical debt compounds.

## Out of scope

- The full Go port (your `GOLANG_MIGRATION.md` is preserved untouched for when/if it is needed).
- Refactoring auth (session-only, no passwords) — not a perf issue.
- Tailwind/HTMX frontend changes.
- Vercel plan change (defer until Phase 6 numbers are in hand).

## Validation checklist

After all phases, verify:
1. `GET /` returns in <300 ms from cold on a Supabase connection.
2. `GET /` issues ≤2 SQL statements (use the Phase 0 counter).
3. `GET /quotations/inbox` issues 1 SQL statement for the page render.
4. `EXPLAIN ANALYZE` on the dashboard query shows index scans, not seq scans, on `requisitions` and `decisions`.
5. Dashboard cache invalidates after a write to `requisitions` or `decisions`.
6. No regression on quotation submission, vendor invite, decision approval, receive/QC flows.
7. `make test` and `make typecheck` pass.
