from app.auth.models import UserProfile, UserRole
from app.categories.models import Category
from app.vendors.models import Vendor


def test_create_category(db_session):
    cat = Category(id="1", name="Laptop Vendors", description="Laptops and PCs")
    db_session.add(cat)
    db_session.commit()
    assert cat.name == "Laptop Vendors"


def test_create_vendor(db_session):
    vendor = Vendor(
        id="1",
        company_name="TechCorp",
        contact_email="sales@techcorp.com",
        contact_person="John",
    )
    db_session.add(vendor)
    db_session.commit()
    assert vendor.company_name == "TechCorp"
    assert vendor.is_active is True


def test_create_user_profile(db_session):
    user = UserProfile(
        id="1",
        email="admin@company.com",
        full_name="Admin User",
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    db_session.commit()
    assert user.email == "admin@company.com"
    assert user.role == UserRole.ADMIN


def test_vendor_category_relationship(db_session):
    cat = Category(id="1", name="Packaging")
    vendor = Vendor(id="1", company_name="PackCo", contact_email="info@packco.com")
    db_session.add_all([cat, vendor])
    db_session.flush()
    vendor.categories.append(cat)
    db_session.commit()
    assert len(vendor.categories) == 1
    assert vendor.categories[0].name == "Packaging"


def test_vendor_is_temporary_default(db_session):
    vendor = Vendor(id="temp-1", company_name="Normal Co", contact_email="normal@co.com")
    db_session.add(vendor)
    db_session.commit()
    assert vendor.is_temporary is False


def test_vendor_is_temporary_true(db_session):
    vendor = Vendor(id="temp-2", company_name="Temp Co", contact_email="temp@co.com", is_temporary=True)
    db_session.add(vendor)
    db_session.commit()
    assert vendor.is_temporary is True


def test_user_permission_properties(db_session):
    u = UserProfile(id="u1", email="proc@test.com", full_name="Procurement User", role=UserRole.PROCUREMENT)
    assert u.is_procurement is True
    assert u.can_create_requisitions is True
    assert u.can_perform_qc is False
    assert u.has_management_authority is False

    # Grant QC receiver rights to procurement user
    u.can_do_qc = True
    assert u.can_perform_qc is True

    # QC Receiver user
    qc_user = UserProfile(id="u2", email="qc@test.com", full_name="QC Receiver", role=UserRole.QC_RECEIVER)
    assert qc_user.can_perform_qc is True
    assert qc_user.can_create_requisitions is False
    assert qc_user.has_management_authority is False

    # Management user
    mgmt_user = UserProfile(id="u3", email="mgmt@test.com", full_name="Management User", role=UserRole.MANAGEMENT)
    assert mgmt_user.has_management_authority is True
    assert mgmt_user.can_create_requisitions is True
    assert mgmt_user.can_perform_qc is True
    assert mgmt_user.can_see_quotes is True

