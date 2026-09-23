"""Tests for docs/modules/common_validation.md -- these utilities have
no HTTP endpoint caller yet (see docs/audit/COMMON_VALIDATION_AUDIT.md's
"deliberately not built now" section), so they're verified standalone
here rather than through a request/response test."""
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.core.currency import DEFAULT_CURRENCY, decimal_places, round_currency
from app.core.id_formats import ORDER_ID, PRODUCT_CODE, QUOTATION_ID, RAW_MATERIAL_CODE, USER_ID
from app.core.timezone import JDK_TIMEZONE, now_jdk, to_jdk_time
from app.core.validation import (
    normalize_email,
    validate_company_email_domain,
    validate_date_range,
    validate_email_format,
)


class TestEmailValidation:
    def test_normalize_email_lowercases_and_trims(self):
        assert normalize_email("  Ada@Example.COM  ") == "ada@example.com"

    def test_validate_email_format_accepts_a_valid_address(self):
        assert validate_email_format("Ada@Example.com") == "ada@example.com"

    def test_validate_email_format_rejects_an_invalid_address(self):
        with pytest.raises(ValueError, match="not a valid email address"):
            validate_email_format("not-an-email")

    def test_validate_company_email_domain_accepts_a_matching_domain(self):
        assert validate_company_email_domain("ada@jdk.com", "jdk.com") == "ada@jdk.com"

    def test_validate_company_email_domain_is_case_insensitive(self):
        assert validate_company_email_domain("ada@JDK.COM", "jdk.com") == "ada@jdk.com"

    def test_validate_company_email_domain_rejects_a_different_domain(self):
        with pytest.raises(ValueError, match="jdk.com"):
            validate_company_email_domain("ada@gmail.com", "jdk.com")

    def test_validate_company_email_domain_allows_anything_when_not_configured(self):
        assert validate_company_email_domain("ada@anywhere.com", None) == "ada@anywhere.com"


class TestDateRangeValidation:
    def test_accepts_start_before_end(self):
        validate_date_range(date(2026, 9, 22), date(2026, 9, 23))

    def test_accepts_same_day_as_valid(self):
        # From: 22/09/2026, Valid Till: 22/09/2026 -- valid, per the spec's own example.
        validate_date_range(date(2026, 9, 22), date(2026, 9, 22))

    def test_rejects_start_after_end(self):
        # From: 23/09/2026, Valid Till: 22/09/2026 -- invalid, per the spec's own example.
        with pytest.raises(ValueError, match="must not be after"):
            validate_date_range(date(2026, 9, 23), date(2026, 9, 22))

    def test_uses_the_given_field_labels_in_the_message(self):
        with pytest.raises(ValueError, match="Valid From must not be after Valid Till"):
            validate_date_range(
                date(2026, 9, 23), date(2026, 9, 22), start_label="Valid From", end_label="Valid Till"
            )

    def test_works_with_datetimes_too(self):
        validate_date_range(datetime(2026, 9, 22, 9, 0), datetime(2026, 9, 22, 17, 0))
        with pytest.raises(ValueError):
            validate_date_range(datetime(2026, 9, 22, 17, 0), datetime(2026, 9, 22, 9, 0))


class TestIdFormats:
    @pytest.mark.parametrize(
        "id_format,valid,invalid",
        [
            (QUOTATION_ID, "Q000001", "QQ00001"),
            (ORDER_ID, "O000042", "O42"),
            (USER_ID, "00001", "1"),
            (PRODUCT_CODE, "200001", "20001"),
            (RAW_MATERIAL_CODE, "100001", "10001"),
        ],
    )
    def test_validate_accepts_the_right_shape_and_rejects_others(self, id_format, valid, invalid):
        assert id_format.validate(valid) == valid
        with pytest.raises(ValueError):
            id_format.validate(invalid)

    def test_format_generates_the_expected_string(self):
        assert QUOTATION_ID.format(1) == "Q000001"
        assert ORDER_ID.format(42) == "O000042"
        assert USER_ID.format(1) == "00001"
        assert PRODUCT_CODE.format(1) == "200001"
        assert RAW_MATERIAL_CODE.format(1) == "100001"

    def test_format_rejects_a_sequence_that_does_not_fit(self):
        with pytest.raises(ValueError, match="between 1"):
            PRODUCT_CODE.format(0)
        with pytest.raises(ValueError, match="between 1"):
            PRODUCT_CODE.format(100000)

    def test_generated_ids_round_trip_through_validate(self):
        assert QUOTATION_ID.validate(QUOTATION_ID.format(123)) == "Q000123"


class TestCurrency:
    def test_default_currency_is_kwd(self):
        assert DEFAULT_CURRENCY == "KWD"

    def test_kwd_has_three_decimal_places(self):
        assert decimal_places("KWD") == 3

    def test_usd_has_two_decimal_places(self):
        assert decimal_places("USD") == 2

    def test_unknown_currency_defaults_to_two_decimal_places(self):
        assert decimal_places("XYZ") == 2

    def test_round_currency_rounds_kwd_to_three_places(self):
        assert round_currency("125.5", "KWD") == Decimal("125.500")
        assert round_currency("125.5005", "KWD") == Decimal("125.501")

    def test_round_currency_rounds_usd_to_two_places(self):
        assert round_currency("125.505", "USD") == Decimal("125.51")

    def test_round_currency_uses_decimal_not_float(self):
        # A classic float pitfall: 0.1 + 0.2 != 0.3 in binary floating
        # point. round_currency must not inherit that from its input.
        result = round_currency(Decimal("0.1") + Decimal("0.2"), "USD")
        assert result == Decimal("0.30")


class TestTimezone:
    def test_jdk_timezone_is_kuwait(self):
        assert str(JDK_TIMEZONE) == "Asia/Kuwait"

    def test_now_jdk_is_timezone_aware_in_kuwait(self):
        value = now_jdk()
        assert value.tzinfo is not None
        assert value.utcoffset().total_seconds() == 3 * 3600

    def test_to_jdk_time_converts_a_naive_utc_datetime(self):
        naive_utc = datetime(2026, 9, 22, 9, 0)
        converted = to_jdk_time(naive_utc)
        assert converted.hour == 12  # UTC+3
        assert converted.tzinfo is not None

    def test_to_jdk_time_converts_an_aware_datetime_from_another_zone(self):
        from zoneinfo import ZoneInfo

        aware = datetime(2026, 9, 22, 5, 0, tzinfo=ZoneInfo("UTC"))
        converted = to_jdk_time(aware)
        assert converted.hour == 8
