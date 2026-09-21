from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: dict[str, str] | None = None


class ErrorResponse(BaseModel):
    """The one error shape every endpoint returns
    (docs/modules/api_error_handling.md #13). Success responses stay the
    plain FastAPI/Pydantic resource shape already used throughout this
    project -- see docs/audit/API_ERROR_HANDLING_AUDIT.md's
    implementation-approach section for why the envelope is applied to
    errors only, not wrapped around every success payload too."""

    success: bool = False
    error: ErrorDetail
    request_id: str
