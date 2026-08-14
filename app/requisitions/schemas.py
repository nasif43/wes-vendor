from pydantic import BaseModel


class RequisitionCreate(BaseModel):
    title: str
    item_description: str
    quantity: float
    unit: str = ""
    notes: str = ""
