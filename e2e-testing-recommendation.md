# End-to-End Testing Guide: WES Vendor Portal

Because this system involves multiple distinct user roles (Internal Management, Procurement, QC) as well as unauthenticated external users (Vendors), the best way to comprehensively test the platform is to follow a full **Procurement Lifecycle Path** using multiple browser sessions.

## 🧪 Recommended Test Setup

1. **Internal Portal (Authenticated)**: Open a standard browser window (e.g., Chrome).
2. **External Vendor View (Unauthenticated)**: Open an Incognito/Private window. This simulates a vendor who does not have a user account on the portal.

## 🚀 Scenario: Full Procurement & Negotiation Lifecycle

### Step 1: Draft & Create Requisition (Internal)
* **Role**: Admin or Management
* **Action**:
  1. Log into the standard browser window using a Management or Admin demo account.
  2. Click **+ New Requisition** on the dashboard.
  3. Fill out the requisition form (Title, Description, Quantity, etc.).
  4. Notice the Requisition is created in **Draft** state. Click **Send to Vendors**.

### Step 2: Generate Links & Invite Vendors (Internal)
* **Action**:
  1. Add a few existing vendors from the database.
  2. Use the **Unlisted Vendor** form at the bottom to generate a temporary link.
  3. *Verification*: Check that the statuses for these vendors show as `Awaiting Quote`.

### Step 3: Vendor Submits Quote (External)
* **Role**: Vendor (No Account)
* **Action**:
  1. In the standard window, click **Link** next to one of the vendors to copy their unique URL.
  2. Switch to your **Incognito Window** and paste the URL.
  3. *Verification*: You should see the requested quantity and item details.
  4. Submit the quote form with a price and quantity (can be partial).
  5. Back in the standard window, refresh the page.
  6. *Verification*: The "Generate Temporary Link" button should now be visually hidden, and the vendor's status should be `Quote Received`.

### Step 4: Compare & Shortlist (Internal)
* **Role**: Management
* **Action**:
  1. Click **Compare Quotes**.
  2. You will see all submitted quotes. In the shortlisting column, select up to 3 vendors.
  3. Assign specific **Allocated Quantities** to split the total order among them.
  4. Click **Shortlist**.

### Step 5: V2 Negotiation (Internal & External)
* **Action**:
  1. Once shortlisted, click **Start Negotiation**.
  2. *Verification*: The system creates new `v2` links for the shortlisted vendors, while preserving the `v1` links.
  3. Copy the `v2` link, open it in the **Incognito Window**.
  4. *Verification*: The vendor should see their **Allocated Quantity** in the form instead of the original total amount.
  5. Submit the v2 quote with a new (presumably lower) price.
  6. Back in the internal window, refresh the Compare page.
  7. *Verification*: The **Δ Delta Table** should appear showing the price differences between v1 and v2.

### Step 6: Procurement Blind Mode Check (Internal - Role Switch)
* **Role**: Procurement Purchaser
* **Action**:
  1. Sign out of Management, and log in as Procurement (e.g., `tanjila.akter@wenerbd.com`).
  2. Open the Compare View.
  3. *Verification*: You should see a red banner at the top indicating "Procurement Blind Mode." All unit prices, subtotals, and the Delta Table should be masked with a `—`.

### Step 7: Final Decision & Invoice
* **Role**: Management / Admin
* **Action**:
  1. Log back in as Management. Select a winning quote and approve it.
  2. The Requisition moves to **Received** (or pending QC).
  3. Click **Receive Delivery** and check the **Do QC** box.
  4. *Verification*: The Requisition status transitions instantly to **Closed**.
  5. Back on the detail page, click the new **Invoice** button.
  6. *Verification*: Ensure the invoice correctly reflects the final negotiated quantities and BDT pricing.

---

### Additional Edge Cases to Test:
* **Vendor Rejection/Audit**: Reject a vendor quote or flag a vendor, then go to their Vendor Profile -> Audit Notes. Ensure the rejection is permanently logged.
* **Requisition Cancellation**: Click Cancel on an open requisition. Ensure it prompts for a reason and moves the requisition to the gray `Cancelled` column on the Kanban board.
