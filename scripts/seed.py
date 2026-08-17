"""
Seed script for the WES Vendor Portal.

Drops all existing tables and re-initializes tables & seed data.

Populates: user_profiles, categories, vendors, vendor_categories,
requisitions, requisition_vendors, quotations, decisions, audit_logs.

Usage:
    python3 -m scripts.seed
"""

import asyncio
import os
import random
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.audit.models import AuditLog
from app.auth.models import UserProfile, UserRole
from app.categories.models import Category
from app.database import Base
from app.decisions.models import Decision
from app.quotations.models import Quotation
from app.requisitions.models import Requisition, RequisitionStatus, RequisitionVendor
from app.vendors.models import Vendor

random.seed(42)

# Obtain DB URL from environment or default to local SQLite
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./wes_dev.db")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)


def now_minus(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


# ── USERS ──────────────────────────────────────────────────────────────────
USERS = [
    dict(
        email="tanjila.akter@wenerbd.com",
        full_name="Tanjila Akter",
        role=UserRole.PROCUREMENT,
        can_view_quotations=False,
        can_do_qc=False,
        can_view_all_requisitions=False,
        is_management=False,
    ),
    dict(
        email="mizanur.rahman@wenerbd.com",
        full_name="Mizanur Rahman",
        role=UserRole.MANAGEMENT,
        can_view_quotations=True,
        can_do_qc=True,
        can_view_all_requisitions=True,
        is_management=True,
    ),
    dict(
        email="kamrul.hasan@wenerbd.com",
        full_name="Md. Kamrul Hasan",
        role=UserRole.QC_RECEIVER,
        can_view_quotations=False,
        can_do_qc=True,
        can_view_all_requisitions=True,
        is_management=False,
    ),
    dict(
        email="admin@wenerbd.com",
        full_name="System Admin",
        role=UserRole.ADMIN,
        can_view_quotations=True,
        can_do_qc=True,
        can_view_all_requisitions=True,
        is_management=True,
    ),
]


# ── CATEGORIES ────────────────────────────────────────────────────────────
CATEGORIES = [
    ("Raw Materials", "Copper, brass, and polycarbonate/PVC resins for switch and MCB bodies"),
    ("Electrical Components", "PCBs, relays, terminals, LED chips and drivers"),
    ("Packaging & Shipping", "Cartons, blister packs, printed labels and inserts"),
    ("Logistics & Transport", "Freight forwarding, C&F agents, and local trucking"),
    ("Testing & Certification", "BSTI compliance, tooling, and lab testing services"),
]

# ── VENDORS: (company, contact person, phone suffix, category names, city, bin, bank, rating) ──
VENDORS = [
    ("Bengal Copper & Wire Industries", "Abdul Karim", "711234501", ["Raw Materials"], "Tejgaon I/A, Dhaka-1208", "901824712001", "City Bank Ltd, Gulshan Branch, A/C 1109283741", 4.5),
    ("Anwar Metal Works Ltd", "Nasrin Jahan", "812345602", ["Raw Materials"], "Kadamtali, Dhaka-1204", "902938471002", "Dutch-Bangla Bank, Motijheel Branch, A/C 2201938475", 4.2),
    ("Padma Brass & Alloys", "Jashim Uddin", "913456703", ["Raw Materials"], "Fatullah, Narayanganj", "903019283003", "Islami Bank Bangladesh, Narayanganj Br, A/C 3301827364", 4.0),
    ("Dhaka Polymer Resins Ltd", "Shirin Sultana", "714567804", ["Raw Materials"], "Tongi, Gazipur-1710", "904192837004", "BRAC Bank, Tongi Branch, A/C 4401726395", 4.6),
    ("Green Delta Petrochemicals", "Habibur Rahman", "815678905", ["Raw Materials"], "Patenga, Chattogram-4100", "905283746005", "EBL, Agrabad Branch, Chattogram, A/C 5501928374", 3.9),
    ("Karim Non-Ferrous Metals", "Selina Begum", "916789006", ["Raw Materials"], "Kaptan Bazar, Old Dhaka", "906374859006", "Sonali Bank, Bangshal Branch, A/C 6601827465", 3.7),
    ("Apex Circuit Boards Ltd", "Rownak Hossain", "717890107", ["Electrical Components"], "Tejgaon I/A, Dhaka-1208", "907465920007", "Standard Chartered, Gulshan Branch, A/C 7701928374", 4.7),
    ("Star Electro Components", "Farhana Yasmin", "818901208", ["Electrical Components"], "Konabari, Gazipur", "908576031008", "City Bank, Gazipur Branch, A/C 8801726395", 4.1),
    ("Unity Relay & Switchgear", "Shahidul Islam", "919012309", ["Electrical Components"], "Siddhirganj, Narayanganj", "909687142009", "Prime Bank, Narayanganj Branch, A/C 9901827364", 4.3),
    ("Bijoy Electronics Trading", "Ruma Akter", "720123410", ["Electrical Components"], "Nababpur Road, Dhaka-1100", "910798253010", "Mercantile Bank, Nababpur Branch, A/C 1012938475", 4.4),
    ("Zenith LED Solutions", "Kamal Uddin Ahmed", "821234511", ["Electrical Components"], "Savar, Dhaka-1340", "911809364011", "Bank Asia, Savar Branch, A/C 1112039586", 4.5),
    ("Nabab Electric Traders", "Momtaz Begum", "922345612", ["Electrical Components", "Raw Materials"], "Nababpur Road, Dhaka-1100", "912910475012", "Pubali Bank, Nababpur Branch, A/C 1213140697", 3.8),
    ("Orbit Terminal & Connectors", "Faruk Ahmed", "723456713", ["Electrical Components"], "Tejgaon, Dhaka-1215", "913021586013", "UCB, Tejgaon Branch, A/C 1314251708", 4.2),
    ("Dhaka Corrugated Box Industries", "Nazma Khatun", "824567814", ["Packaging & Shipping"], "Dhaka EPZ, Savar", "914132697014", "AB Bank, Savar Branch, A/C 1415362819", 4.3),
    ("Mego Packaging Solutions", "Anisur Rahman", "925678915", ["Packaging & Shipping"], "Konabari, Gazipur", "915243708015", "NRB Bank, Gazipur Branch, A/C 1516473920", 4.0),
    ("Bengal Carton & Print", "Sultana Razia", "726789016", ["Packaging & Shipping"], "Fatullah, Narayanganj", "916354819016", "Jamuna Bank, Narayanganj Branch, A/C 1617584031", 3.9),
    ("Elite Blister Pack Ltd", "Iqbal Hossain", "827890117", ["Packaging & Shipping"], "Tongi, Gazipur", "917465920017", "One Bank, Tongi Branch, A/C 1718695142", 4.1),
    ("Sonar Bangla Printing Press", "Mahmuda Sultana", "928901218", ["Packaging & Shipping"], "Fakirapool, Dhaka-1000", "918576031018", "NCC Bank, Motijheel Branch, A/C 1819706253", 3.6),
    ("Trust Line Cargo & Logistics", "Tariqul Islam", "729012319", ["Logistics & Transport"], "Tejgaon, Dhaka-1215", "919687142019", "Trust Bank, Tejgaon Branch, A/C 1920817364", 4.2),
    ("Chattogram Freight Movers Ltd", "Delwar Hossain", "830123420", ["Logistics & Transport"], "Agrabad, Chattogram-4100", "920798253020", "Southeast Bank, Agrabad Branch, A/C 2021928475", 4.4),
    ("Speed Trans Bangladesh", "Nurul Amin", "931234521", ["Logistics & Transport"], "Cumilla Highway, Dhaka", "921809364021", "IFIC Bank, Cumilla Branch, A/C 2123039586", 3.8),
    ("Meghna C&F Agency", "Rezaul Karim", "732345622", ["Logistics & Transport"], "Port Connecting Road, Chattogram", "922910475022", "Uttara Bank, Chattogram Branch, A/C 2224150697", 4.0),
    ("City Express Carrying Agency", "Yasmin Akhter", "833456723", ["Logistics & Transport"], "Postogola, Dhaka-1204", "923021586023", "Midland Bank, Postogola Branch, A/C 2325261708", 3.7),
    ("BSTI Compliance Consultants Ltd", "Golam Mostafa", "934567824", ["Testing & Certification"], "Tikatuli, Dhaka-1203", "924132697024", "Al-Arafah Islami Bank, Tikatuli Br, A/C 2426372819", 4.5),
    ("Precision Mould & Die Ltd", "Hasina Parvin", "735678925", ["Testing & Certification"], "Konabari, Gazipur", "925243708025", "Shahjalal Islami Bank, Gazipur Br, A/C 2527483920", 4.3),
    ("TechCheck Testing Labs", "Amirul Islam", "836789026", ["Testing & Certification"], "Mirpur, Dhaka-1216", "926354819026", "Exim Bank, Mirpur Branch, A/C 2628594031", 4.1),
    ("Rapid Repair & Tooling Services", "Firoza Begum", "937890127", ["Testing & Certification"], "Siddhirganj, Narayanganj", "927465920027", "Social Islami Bank, Narayanganj Br, A/C 2729605142", 3.9),
    ("Skyline IT Solutions", "Sabbir Ahmed", "738901228", ["Testing & Certification"], "Banani, Dhaka-1213", "928576031028", "Eastern Bank, Banani Branch, A/C 2830716253", 4.6),
]

REQ_ITEMS = [
    ("Oxygen-Free Copper Wire Coils", "Raw Materials", "kg", 500),
    ("Polycarbonate Flame-Retardant Switch Plates", "Electrical Components", "pcs", 20000),
    ("Brass Terminal Pins", "Electrical Components", "pcs", 50000),
    ("MCB Circuit Breaker Casing (PC, black)", "Electrical Components", "pcs", 8000),
    ("Corrugated Shipping Cartons (double-wall)", "Packaging & Shipping", "pcs", 15000),
    ("LED Driver Modules 9W", "Electrical Components", "pcs", 10000),
    ("Exhaust Fan Motor Windings", "Raw Materials", "pcs", 3000),
    ("Blister Pack Sheets for Switch Retail Box", "Packaging & Shipping", "pcs", 25000),
    ("Distribution Box Hinges & Latches", "Electrical Components", "pcs", 6000),
    ("Freight: Chattogram Port to Dhaka Warehouse", "Logistics & Transport", "trip", 12),
    ("BSTI Certification Renewal - RCCB Line", "Testing & Certification", "service", 1),
    ("PVC Compound Granules (Cable Grade)", "Raw Materials", "kg", 2000),
]


def pack_vendor_notes(city, bin_no, bank, rating, payment_terms):
    return (
        f"Address: {city} | BIN: {bin_no} | Bank: {bank} | "
        f"Rating: {rating}/5.0 | Payment Terms: {payment_terms}"
    )


PAYMENT_TERMS_OPTIONS = ["Net 30", "50% Advance / 50% on Delivery", "Net 15", "Full Advance", "Net 45"]


async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)

    # Clean DB: Drop all tables and recreate clean schema
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        # Users
        user_objs = [UserProfile(**u) for u in USERS]
        session.add_all(user_objs)
        await session.flush()
        users_by_role = {u.role: u for u in user_objs}
        purchaser = users_by_role[UserRole.PROCUREMENT]
        requester = purchaser
        manager = users_by_role[UserRole.MANAGEMENT]
        qc = users_by_role[UserRole.QC_RECEIVER]
        admin = users_by_role.get(UserRole.ADMIN, manager)

        # Categories
        cat_objs = {name: Category(name=name, description=desc) for name, desc in CATEGORIES}
        session.add_all(cat_objs.values())
        await session.flush()

        # Vendors
        vendor_objs = []
        for company, contact, phone_suffix, cat_names, city, bin_no, bank, rating in VENDORS:
            v = Vendor(
                company_name=company,
                contact_person=contact,
                contact_email=f"{contact.lower().replace(' ', '.')}@{company.lower().split()[0]}.com".replace("..", "."),
                phone=f"+8801{phone_suffix}",
                notes=pack_vendor_notes(city, bin_no, bank, rating, random.choice(PAYMENT_TERMS_OPTIONS)),
                is_active=True,
                is_temporary=(random.random() < 0.1),
                created_by=purchaser.id,
                categories=[cat_objs[c] for c in cat_names],
            )
            vendor_objs.append(v)
        session.add_all(vendor_objs)
        await session.flush()

        vendors_by_category = {name: [v for v in vendor_objs if cat_objs[name] in v.categories] for name, _ in CATEGORIES}

        # Requisitions across all 6 statuses (2 each = 12, matching REQ_ITEMS)
        statuses_cycle = (
            [RequisitionStatus.DRAFT] * 2
            + [RequisitionStatus.NEW] * 2
            + [RequisitionStatus.IN_PROGRESS] * 2
            + [RequisitionStatus.SUBMITTED] * 2
            + [RequisitionStatus.RECEIVED] * 2
            + [RequisitionStatus.CLOSED] * 2
        )

        requisitions = []
        audit_logs = []

        for idx, ((item_name, cat_name, unit, qty), status) in enumerate(zip(REQ_ITEMS, statuses_cycle)):
            created_days_ago = 45 - idx * 3
            req = Requisition(
                title=f"Procurement: {item_name}",
                item_description=f"Requisition for {item_name.lower()} to support Wener production line.",
                quantity=qty,
                unit=unit,
                notes="Routine replenishment based on production forecast.",
                status=status,
                created_by=requester.id,
                created_at=now_minus(created_days_ago),
                updated_at=now_minus(max(created_days_ago - 5, 0)),
            )
            requisitions.append(req)
            session.add(req)
            await session.flush()

            audit_logs.append(AuditLog(
                actor_id=requester.id, actor_name=requester.full_name, actor_email=requester.email,
                actor_role=requester.role.value, action="requisition_created",
                entity_type="requisition", entity_id=req.id, entity_label=req.title,
                created_at=now_minus(created_days_ago),
            ))

            if status == RequisitionStatus.DRAFT:
                continue  # no vendor invitations yet

            # Invite 3 vendors from the matching category (or fewer if unavailable)
            candidates = vendors_by_category.get(cat_name, vendor_objs)[:3] or random.sample(vendor_objs, 3)
            req_vendors = []
            for v in candidates:
                rv = RequisitionVendor(
                    requisition_id=req.id,
                    vendor_id=v.id,
                    unique_link_token=secrets.token_urlsafe(24),
                    status="pending",
                    link_sent_at=now_minus(created_days_ago - 1),
                )
                req_vendors.append(rv)
            session.add_all(req_vendors)
            await session.flush()

            audit_logs.append(AuditLog(
                actor_id=purchaser.id, actor_name=purchaser.full_name, actor_email=purchaser.email,
                actor_role=purchaser.role.value, action="vendors_invited",
                entity_type="requisition", entity_id=req.id, entity_label=req.title,
                notes=f"Invited {len(req_vendors)} vendors for quotation.",
                created_at=now_minus(created_days_ago - 1),
            ))

            if status == RequisitionStatus.NEW:
                continue  # invitations sent, no quotes yet

            # in_progress and beyond: quotes submitted by all invited vendors
            base_unit_price = round(random.uniform(15, 850), 2)
            quotes = []
            rv_quote_pairs = []
            for i, rv in enumerate(req_vendors):
                rv.status = "submitted"
                unit_price = round(base_unit_price * random.uniform(0.9, 1.15), 2)
                total_price = round(unit_price * float(qty), 2)
                q = Quotation(
                    requisition_vendor_id=rv.id,
                    submission_type="form",
                    form_data={
                        "unit_price": unit_price,
                        "currency": "BDT",
                        "total_price": total_price,
                        "delivery_timeline": f"{random.choice([5, 7, 10, 14, 21])} days",
                        "warranty": random.choice(["6 months", "1 year", "2 years", "N/A"]),
                        "payment_terms": random.choice(PAYMENT_TERMS_OPTIONS),
                    },
                    submitted_at=now_minus(created_days_ago - 3 - i),
                    notes="Auto-generated demo quotation.",
                )
                quotes.append(q)
                rv_quote_pairs.append((rv, q))
            session.add_all(quotes)
            await session.flush()

            audit_logs.append(AuditLog(
                actor_id=None, actor_name="Vendor Portal", actor_email="system@wenerbd.com",
                actor_role="system", action="quotations_received",
                entity_type="requisition", entity_id=req.id, entity_label=req.title,
                notes=f"{len(quotes)} quotations received.",
                created_at=now_minus(created_days_ago - 3),
            ))

            if status == RequisitionStatus.IN_PROGRESS:
                continue  # quotes in, no decision yet

            # submitted, received, closed: a decision has been made and approved
            winning_rv, _ = min(rv_quote_pairs, key=lambda pair: pair[1].form_data["unit_price"])
            decision = Decision(
                requisition_id=req.id,
                winning_vendor_id=winning_rv.vendor_id,
                decided_by=purchaser.id,
                decided_at=now_minus(created_days_ago - 6),
                notes="Lowest priced compliant quote selected.",
                management_approved=True,
                approved_by=manager.id,
                approved_at=now_minus(created_days_ago - 7),
            )
            session.add(decision)

            audit_logs.append(AuditLog(
                actor_id=manager.id, actor_name=manager.full_name, actor_email=manager.email,
                actor_role=manager.role.value, action="decision_approved",
                entity_type="requisition", entity_id=req.id, entity_label=req.title,
                notes="Winning vendor approved by management.",
                created_at=now_minus(created_days_ago - 7),
            ))

            if status == RequisitionStatus.SUBMITTED:
                continue  # approved, awaiting delivery

            # received and closed: goods have arrived
            req.invoice_number = f"INV-{2026}{1000 + idx}"
            req.invoice_url = f"https://storage.wenerbd.com/invoices/inv-{req.id[:8]}.pdf"
            req.delivery_image_url = f"https://storage.wenerbd.com/delivery/del-{req.id[:8]}.jpg"
            req.payment_status = "paid" if status == RequisitionStatus.CLOSED else "pending"

            audit_logs.append(AuditLog(
                actor_id=qc.id, actor_name=qc.full_name, actor_email=qc.email,
                actor_role=qc.role.value, action="goods_received",
                entity_type="requisition", entity_id=req.id, entity_label=req.title,
                notes="Delivery received at warehouse with invoice and photo proof.",
                created_at=now_minus(created_days_ago - 9),
            ))

            if status == RequisitionStatus.CLOSED:
                req.qc_done = True
                req.qc_done_by = qc.id
                req.qc_done_at = now_minus(created_days_ago - 10)

                audit_logs.append(AuditLog(
                    actor_id=qc.id, actor_name=qc.full_name, actor_email=qc.email,
                    actor_role=qc.role.value, action="qc_completed",
                    entity_type="requisition", entity_id=req.id, entity_label=req.title,
                    notes=f"QC done on {req.qc_done_at.strftime('%Y-%m-%d')}.",
                    created_at=now_minus(created_days_ago - 10),
                ))

        session.add_all(audit_logs)
        await session.commit()

    await engine.dispose()
    print(f"Seed complete -> {DATABASE_URL}")
    print(f"  Users: {len(USERS)}")
    print(f"  Categories: {len(CATEGORIES)}")
    print(f"  Vendors: {len(VENDORS)}")
    print(f"  Requisitions: {len(REQ_ITEMS)} (2 per status across all 6 stages)")


if __name__ == "__main__":
    asyncio.run(main())
