from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.file import FileOut


class DocumentTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_type: str
    letterhead_file_id: int | None
    letterhead_file: FileOut | None = None
    margin_top_mm: int
    margin_bottom_mm: int
    intro_text: str | None
    terms_text: str | None
    signature_text: str | None


class DocumentTemplateUpdateRequest(BaseModel):
    """`letterhead_file_id`: a PNG/JPEG already uploaded via POST
    /api/files, or null to print the plain organisation-name header."""

    letterhead_file_id: int | None = None
    margin_top_mm: int = Field(default=40, ge=5, le=120)
    margin_bottom_mm: int = Field(default=25, ge=5, le=120)
    intro_text: str | None = Field(default=None, max_length=4000)
    terms_text: str | None = Field(default=None, max_length=8000)
    signature_text: str | None = Field(default=None, max_length=1000)

    @field_validator("intro_text", "terms_text", "signature_text")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None
