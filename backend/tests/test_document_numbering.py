"""Sales S3: the shared YY?NNNN numbering helper
(app/services/document_numbering.py) future Sales documents reuse.

Sales type digits are not decided, so these tests run against a
test-only table and the test-only digit "8" -- neither is a production
document type."""

from datetime import date

import pytest
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, SessionLocal
from app.services import document_numbering

TEST_ONLY_DIGIT = "8"


class _NumberedProbe(Base):
    __tablename__ = "test_only_numbered_probes"
    __table_args__ = (UniqueConstraint("organisation_id", "number", name="uq_test_only_numbered_probes_org_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id"), nullable=False)
    number: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")


def _next(db, organisation_id, today):
    return document_numbering.next_yearly_number(
        db,
        number_column=_NumberedProbe.number,
        organisation_column=_NumberedProbe.organisation_id,
        organisation_id=organisation_id,
        type_digit=TEST_ONLY_DIGIT,
        today=today,
    )


def _insert(db, organisation_id, today):
    row = document_numbering.insert_with_yearly_number(
        db,
        build=lambda number: _NumberedProbe(organisation_id=organisation_id, number=number),
        number_column=_NumberedProbe.number,
        organisation_column=_NumberedProbe.organisation_id,
        organisation_id=organisation_id,
        type_digit=TEST_ONLY_DIGIT,
        today=today,
        label="probe",
    )
    db.commit()
    return row


def test_format_sequence_organisation_and_year_isolation(db_session, organisation, other_organisation):
    assert TEST_ONLY_DIGIT not in document_numbering.ESTABLISHED_TYPE_DIGITS

    assert _insert(db_session, organisation.id, date(2026, 5, 1)).number == "2680001"
    assert _insert(db_session, organisation.id, date(2026, 5, 2)).number == "2680002"
    # Another organisation has its own sequence.
    assert _insert(db_session, other_organisation.id, date(2026, 5, 2)).number == "2680001"
    # A new year starts again at 0001; the old year is unaffected.
    assert _insert(db_session, organisation.id, date(2027, 1, 1)).number == "2780001"
    assert _next(db_session, organisation.id, date(2026, 12, 31)) == "2680003"

    with pytest.raises(ValueError):
        document_numbering.yearly_prefix("12", date(2026, 1, 1))


def test_concurrent_claim_of_the_same_number_is_retried_never_duplicated(db_session, organisation):
    today = date(2026, 5, 1)
    competing = SessionLocal()
    try:
        attempts = []

        def build(number):
            # Another request commits the same number after ours was counted.
            if not attempts:
                competing.add(_NumberedProbe(organisation_id=organisation.id, number=number))
                competing.commit()
            attempts.append(number)
            return _NumberedProbe(organisation_id=organisation.id, number=number)

        row = document_numbering.insert_with_yearly_number(
            db_session,
            build=build,
            number_column=_NumberedProbe.number,
            organisation_column=_NumberedProbe.organisation_id,
            organisation_id=organisation.id,
            type_digit=TEST_ONLY_DIGIT,
            today=today,
        )
        db_session.commit()
    finally:
        competing.close()

    assert attempts == ["2680001", "2680002"]
    assert row.number == "2680002"

    # The DB constraint itself refuses a duplicate, whatever the caller does.
    db_session.add(_NumberedProbe(organisation_id=organisation.id, number="2680002"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_preview_reserves_nothing_and_issued_numbers_are_never_reused(db_session, organisation):
    today = date(2026, 5, 1)
    # Previewing (e.g. opening a form) allocates nothing.
    assert _next(db_session, organisation.id, today) == "2680001"
    assert _next(db_session, organisation.id, today) == "2680001"

    first = _insert(db_session, organisation.id, today)
    # Cancelling or editing a document never changes or frees its number.
    first.status = "cancelled"
    db_session.commit()
    db_session.refresh(first)
    assert first.number == "2680001"
    assert _insert(db_session, organisation.id, today).number == "2680002"
