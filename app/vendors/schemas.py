from pydantic import BaseModel


class VendorCreate(BaseModel):
    company_name: str
    contact_email: str
    contact_person: str = ""
    phone: str = ""
    notes: str = ""
    category_ids: list[str] = []


class VendorUpdate(BaseModel):
    company_name: str | None = None
    contact_email: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    notes: str | None = None
    is_active: bool | None = None
    category_ids: list[str] | None = None
