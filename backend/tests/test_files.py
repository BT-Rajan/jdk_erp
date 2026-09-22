"""Tests for docs/modules/file_storage.md."""
import io

import pytest

from app.core import entity_access
from app.core.entity_access import register_entity_access_check
from app.core.errors import ValidationError
from app.core.storage import LocalStorageBackend, StorageKeyError, default_storage
from app.models.file import FileRecord
from app.services import file_service

PDF_BYTES = b"%PDF-1.4 fake pdf content"


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _pdf_file(name="invoice.pdf"):
    return {"upload": (name, io.BytesIO(PDF_BYTES), "application/pdf")}


class TestSecureFilenames:
    def test_storage_key_never_reuses_the_original_filename(self):
        key = file_service.generate_storage_key("pdf")
        assert "invoice" not in key
        assert key.endswith(".pdf")
        assert key.startswith("f_")

    def test_storage_key_is_unique_per_call(self):
        assert file_service.generate_storage_key("pdf") != file_service.generate_storage_key("pdf")

    def test_sanitize_display_filename_strips_path_components(self):
        assert file_service.sanitize_display_filename("../../etc/passwd.pdf") == "passwd.pdf"
        assert file_service.sanitize_display_filename("C:\\evil\\invoice.pdf") == "invoice.pdf"

    def test_sanitize_display_filename_strips_control_and_special_characters(self):
        result = file_service.sanitize_display_filename("inv\x00oice\".pdf")
        assert "\x00" not in result
        assert '"' not in result

    def test_local_backend_rejects_a_key_that_would_escape_its_root(self, tmp_path):
        backend = LocalStorageBackend(root=str(tmp_path))
        with pytest.raises(StorageKeyError):
            backend.exists("../outside.pdf")


class TestUploadValidation:
    def test_uploading_a_disallowed_extension_is_rejected(self, db_session, organisation):
        with pytest.raises(ValidationError, match="not allowed"):
            file_service.upload_file(
                db_session,
                organisation_id=organisation.id,
                uploaded_by_user_id=1,
                filename="script.exe",
                stream=io.BytesIO(b"MZ"),
            )

    def test_a_missing_extension_is_rejected(self, db_session, organisation):
        with pytest.raises(ValidationError):
            file_service.upload_file(
                db_session, organisation_id=organisation.id, uploaded_by_user_id=1, filename="noextension", stream=io.BytesIO(b"x")
            )

    def test_content_not_matching_the_claimed_extension_is_rejected(self, db_session, organisation):
        # An .exe renamed to .pdf -- the client-supplied extension lies,
        # but the actual bytes don't start with %PDF.
        with pytest.raises(ValidationError, match="does not match"):
            file_service.upload_file(
                db_session,
                organisation_id=organisation.id,
                uploaded_by_user_id=1,
                filename="evil.pdf",
                stream=io.BytesIO(b"MZ this is an executable"),
            )

    def test_oversized_upload_is_rejected_and_leaves_no_partial_file(self, db_session, organisation, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0)  # 0MB -- anything is "too big"
        stream = io.BytesIO(PDF_BYTES)
        with pytest.raises(ValidationError, match="exceeds"):
            file_service.upload_file(
                db_session, organisation_id=organisation.id, uploaded_by_user_id=1, filename="invoice.pdf", stream=stream
            )
        assert db_session.query(FileRecord).count() == 0

    def test_a_valid_upload_records_the_server_derived_mime_type_not_the_clients(self, db_session, organisation, active_user):
        record = file_service.upload_file(
            db_session,
            organisation_id=organisation.id,
            uploaded_by_user_id=active_user.id,
            filename="invoice.PDF",
            stream=io.BytesIO(PDF_BYTES),
        )
        assert record.mime_type == "application/pdf"
        assert default_storage.exists(record.storage_key)


class TestAccessControl:
    def test_a_file_from_another_organisation_is_not_found(self, db_session, organisation, other_organisation, active_user):
        record = file_service.upload_file(
            db_session, organisation_id=organisation.id, uploaded_by_user_id=active_user.id, filename="invoice.pdf", stream=io.BytesIO(PDF_BYTES)
        )
        with pytest.raises(Exception):  # NotFoundError
            file_service.get_file_or_404(db_session, record.id, other_organisation.id)

    def test_a_soft_deleted_file_is_not_found(self, db_session, organisation, active_user):
        record = file_service.upload_file(
            db_session, organisation_id=organisation.id, uploaded_by_user_id=active_user.id, filename="invoice.pdf", stream=io.BytesIO(PDF_BYTES)
        )
        file_service.soft_delete_file(db_session, record)
        with pytest.raises(Exception):
            file_service.get_file_or_404(db_session, record.id, organisation.id)
        # Soft delete only -- the physical file is untouched.
        assert default_storage.exists(record.storage_key)

    def test_entity_access_check_can_deny_even_within_the_same_organisation(self, db_session, organisation, active_user):
        register_entity_access_check("widget", lambda db, user, entity_id: False)
        try:
            record = file_service.upload_file(
                db_session,
                organisation_id=organisation.id,
                uploaded_by_user_id=active_user.id,
                filename="invoice.pdf",
                stream=io.BytesIO(PDF_BYTES),
                entity_type="widget",
                entity_id=42,
            )
            from app.core.errors import AccessDeniedError

            with pytest.raises(AccessDeniedError):
                file_service.authorize_file_access(db_session, active_user, record)
        finally:
            entity_access._registry.pop("widget", None)

    def test_no_registered_check_means_organisation_scope_alone_decides(self, db_session, organisation, active_user):
        record = file_service.upload_file(
            db_session,
            organisation_id=organisation.id,
            uploaded_by_user_id=active_user.id,
            filename="invoice.pdf",
            stream=io.BytesIO(PDF_BYTES),
            entity_type="unregistered_entity",
            entity_id=1,
        )
        file_service.authorize_file_access(db_session, active_user, record)  # does not raise


class TestFilesEndpoint:
    def test_upload_requires_authentication(self, client):
        response = client.post("/api/files", files=_pdf_file())
        assert response.status_code == 401

    def test_upload_download_round_trip(self, client, active_user):
        headers = _login_headers(client)
        upload = client.post("/api/files", headers=headers, files=_pdf_file())
        assert upload.status_code == 201
        body = upload.json()
        assert body["original_filename"] == "invoice.pdf"
        assert body["mime_type"] == "application/pdf"
        assert "storage_key" not in body  # never expose the physical location

        download = client.get(f"/api/files/{body['id']}", headers=headers)
        assert download.status_code == 200
        assert download.content == PDF_BYTES
        assert download.headers["content-type"] == "application/pdf"
        assert 'filename="invoice.pdf"' in download.headers["content-disposition"]

    def test_download_from_another_organisation_is_404_not_403(self, client, active_user, other_org_user):
        headers = _login_headers(client, "ada")
        other_headers = _login_headers(client, "grace")
        upload = client.post("/api/files", headers=headers, files=_pdf_file())
        file_id = upload.json()["id"]

        response = client.get(f"/api/files/{file_id}", headers=other_headers)
        assert response.status_code == 404

    def test_delete_is_soft_and_makes_the_file_inaccessible(self, client, active_user):
        headers = _login_headers(client)
        upload = client.post("/api/files", headers=headers, files=_pdf_file())
        file_id = upload.json()["id"]

        delete = client.delete(f"/api/files/{file_id}", headers=headers)
        assert delete.status_code == 204

        response = client.get(f"/api/files/{file_id}", headers=headers)
        assert response.status_code == 404

    def test_malicious_content_disguised_as_pdf_is_rejected(self, client, active_user):
        headers = _login_headers(client)
        response = client.post(
            "/api/files", headers=headers, files={"upload": ("evil.pdf", io.BytesIO(b"MZ not a pdf"), "application/pdf")}
        )
        assert response.status_code == 422

    def test_disallowed_extension_is_rejected(self, client, active_user):
        headers = _login_headers(client)
        response = client.post(
            "/api/files", headers=headers, files={"upload": ("script.exe", io.BytesIO(b"MZ"), "application/octet-stream")}
        )
        assert response.status_code == 422
