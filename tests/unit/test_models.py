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
    u = UserProfile(id="u1", email="req@test.com", full_name="Requester User", role=UserRole.REQUESTER)
    assert u.can_see_quotes is False
    assert u.can_perform_qc is False
    assert u.has_management_authority is False

    # Grant QC and Quote visibility
    u.can_view_quotations = True
    u.can_do_qc = True
    assert u.can_see_quotes is True
    assert u.can_perform_qc is True
    assert u.has_management_authority is False
