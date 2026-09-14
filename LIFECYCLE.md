# Procurement Lifecycle Reference

Complete description of the procurement workflow with role responsibilities, 
DB changes, and emails at each step.

## Full Flow Diagram

```
Procurement          Supplier            Management          QC Receiver
────────────         ────────            ──────────          ───────────
Create Requisition
  │
  ├─ Invite Suppliers (v1 links)
  │         │
  │    Submit Quotes ────────────► Review & Compare Quotes
  │                                 │
  │                          Shortlist Suppliers
  │                          (per supplier, per item)
  │                                 │
  │                          Start Negotiation
  │         │                       │
  │    Rejected suppliers ◄──────────
  │    get rejection email
  │         │
  │    Shortlisted suppliers get v2 links
  │         │
  │    Submit Revised Quotes ───────► Review v2 Quotes
  │                                 │
  │                          Select Winner(s)
  │                                 │
Issue Work Order ◄─────────────────
  │
  ├─ Work Order PDF emailed to supplier + management CC
  │
  │                   Supplier delivers goods
  │                                            │
  │                                    Receive Items (tabular)
  │                                    Log per-item quantities
  │                                    Mark accepted/rejected
  │                                            │
  │                                    Invoice auto-generated
  │                                    Supplier rating saved
  │                                    Delivery timer stopped
  │                                    Status → CLOSED
```

## Step-by-Step Detail

### Step 1: Create Requisition (Procurement)
- **Who:** Procurement
- **What:** Fill title, add line items (name, description, qty each)
- **DB:** `Requisition` row created with `status=DRAFT`
- **Email:** None

### Step 2: Invite Suppliers (Procurement)
- **Who:** Procurement
- **What:** Select suppliers from the supplier list, click Send
- **DB:** `RequisitionVendor` rows created (one per supplier), `status=NEW`
- **Email:** Each supplier gets invitation email with unique quote link

### Step 3: Supplier Submits Quote
- **Who:** Supplier (external, no login)
- **What:** Open unique link, fill per-item prices OR upload image
- **DB:** `Quotation` row created (`quote_version=1`), `status=IN_PROGRESS`
- **Email:** Procurement/creator notified with PDF attachment; Supplier gets confirmation

### Step 4: Management Reviews Quotes
- **Who:** Management
- **Where:** Quotations → Compare (`/quotations/compare/{req_id}`)
- **What:** View per-item prices from all suppliers, compare v1 quotes
- **DB:** No changes yet

### Step 5: Shortlist Suppliers (Management)
- **Who:** Management
- **What:** Select which suppliers are shortlisted (and optionally per item)
- **DB:** `RequisitionVendor.is_shortlisted=True`, `ShortlistedItem` rows created
- **Email:** None yet

### Step 6: Start Negotiation (Management)
- **Who:** Management  
- **What:** Click "Start Negotiation" — sends v2 links
- **DB:** New `RequisitionVendor` rows created (`negotiation_version=2`), `status=NEGOTIATING`
- **Email:** 
  - Non-shortlisted suppliers → rejection notification
  - Shortlisted suppliers → v2 quote request (showing only their shortlisted items)

### Step 7: Supplier Submits Revised Quote
- **Who:** Shortlisted supplier (external)
- **What:** Open v2 link, see only their shortlisted items, submit revised prices
- **DB:** `Quotation` row created (`quote_version=2`)
- **Email:** Management/creator notified; Supplier gets confirmation

### Step 8: Select Winner (Management)
- **Who:** Management
- **What:** Click "Select as Winner" on compare page
- **DB:** `Decision` record created, `status=AWARDED`
- **Email:** All suppliers notified (winner: congratulations; others: not selected)
- **UI:** Compare view locks — winner badge shown, all controls disabled

### Step 9: Issue Work Order (Procurement)
- **Who:** Procurement
- **What:** Click "Issue Work Order" on requisition detail page
- **DB:** `WorkOrder` row created, `delivery_started_at=now()`, `status=WORK_ORDER_ISSUED`
- **PDF:** Work order generated with active letterhead
- **Email:** Work order PDF emailed to winning supplier + management CC

### Step 10: Receive Items (QC Receiver)
- **Who:** QC Receiver or Management
- **Where:** Requisition → Receive Items
- **What:** Tabular form — per item: enter received qty, auto-calculates rejected qty, optional rejection reason
- **DB:** `ReceivedItem` rows created, `WorkOrder.delivery_completed_at=now()`
- **Invoice:** Auto-generated PDF: `accepted_qty × unit_price` per item
- **Rating:** `SupplierRating` row created with delivery days + defect rate
- **Email:** Invoice PDF emailed to management CC
- **Status:** → `CLOSED`

## Email Reference

| Trigger | Recipient | Has PDF? |
|---------|-----------|----------|
| Supplier invited | Supplier | No |
| Quote submitted | Procurement/Creator | Yes (quotation PDF) |
| Quote submitted | Supplier | No (confirmation only) |
| Negotiation started | Non-shortlisted suppliers | No (rejection) |
| Negotiation started | Shortlisted suppliers | No (v2 invitation) |
| Winner selected | All suppliers | No |
| Work order issued | Winning supplier | Yes (work order PDF) |
| Work order issued | Management CC | Yes (work order PDF) |
| Invoice generated | Management CC | Yes (invoice PDF) |
