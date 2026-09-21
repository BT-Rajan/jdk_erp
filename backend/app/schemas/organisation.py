from pydantic import BaseModel, ConfigDict


class OrganisationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    contact_email: str | None
    contact_phone: str | None
    address: str | None
    currency: str
    timezone: str
    is_active: bool
