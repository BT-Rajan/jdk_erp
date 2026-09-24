from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.core.errors import NotFoundError, ValidationError
from app.models.audit_event import DOCUMENT_TEMPLATE_UPDATED, ORGANISATION_MODULE
from app.models.document_template import DOCUMENT_TYPES, DocumentTemplate
from app.models.file import FileRecord
from app.models.user import User
from app.schemas.document_template import DocumentTemplateOut, DocumentTemplateUpdateRequest
from app.schemas.file import FileOut
from app.services import audit_service, file_service

router = APIRouter(prefix="/api/document-templates", tags=["document-templates"])

_LETTERHEAD_FILE = "document_template"
_LETTERHEAD_MIME_TYPES = ("image/png", "image/jpeg")


def _check_type(document_type: str) -> None:
    if document_type not in DOCUMENT_TYPES:
        raise NotFoundError("Document template not found.")


def _out(db: Session, template: DocumentTemplate | None, document_type: str) -> DocumentTemplateOut:
    if template is None:
        return DocumentTemplateOut(
            document_type=document_type, letterhead_file_id=None, margin_top_mm=40, margin_bottom_mm=25,
            intro_text=None, terms_text=None, signature_text=None,
        )
    letterhead = None
    if template.letterhead_file_id is not None:
        letterhead = (
            db.query(FileRecord)
            .filter(FileRecord.id == template.letterhead_file_id, FileRecord.deleted_at.is_(None))
            .first()
        )
    out = DocumentTemplateOut.model_validate(template)
    out.letterhead_file = FileOut.model_validate(letterhead) if letterhead else None
    return out


def _get(db: Session, organisation_id: int, document_type: str) -> DocumentTemplate | None:
    return (
        db.query(DocumentTemplate)
        .filter(DocumentTemplate.organisation_id == organisation_id, DocumentTemplate.document_type == document_type)
        .first()
    )


@router.get("/{document_type}", response_model=DocumentTemplateOut)
def get_document_template(
    document_type: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> DocumentTemplateOut:
    """Admin Setup -> Documents (docs/modules/rfq.md #11). Defaults until
    first saved."""
    _check_type(document_type)
    return _out(db, _get(db, admin.organisation_id, document_type), document_type)


@router.put("/{document_type}", response_model=DocumentTemplateOut)
def update_document_template(
    document_type: str,
    payload: DocumentTemplateUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DocumentTemplateOut:
    """Letterhead + wording used for every document of this type generated
    from now on. Already-generated PDFs are never changed."""
    _check_type(document_type)
    template = _get(db, admin.organisation_id, document_type)
    if template is None:
        template = DocumentTemplate(organisation_id=admin.organisation_id, document_type=document_type)
        db.add(template)
        db.flush()

    if payload.letterhead_file_id is not None and payload.letterhead_file_id != template.letterhead_file_id:
        record = (
            db.query(FileRecord)
            .filter(
                FileRecord.id == payload.letterhead_file_id,
                FileRecord.organisation_id == admin.organisation_id,
                FileRecord.deleted_at.is_(None),
            )
            .first()
        )
        if record is None or record.mime_type not in _LETTERHEAD_MIME_TYPES:
            raise ValidationError(
                "The letterhead must be a PNG or JPEG image uploaded to your organisation.",
                fields={"letterhead_file_id": "Upload a PNG or JPEG image."},
            )
        file_service.attach_files(
            db,
            file_ids=[record.id],
            entity_type=_LETTERHEAD_FILE,
            entity_id=template.id,
            organisation_id=admin.organisation_id,
        )

    for field, value in payload.model_dump().items():
        setattr(template, field, value)
    db.add(template)

    audit_service.log_event(
        db,
        action=DOCUMENT_TEMPLATE_UPDATED,
        module=ORGANISATION_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="document_template",
        entity_id=template.id,
        result="success",
        details=f"document_type: {document_type}, letterhead_file_id: {template.letterhead_file_id}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(template)
    return _out(db, template, document_type)
