"""Tests for app.core.qr (docs/modules/common_validation.md #5) -- no
HTTP endpoint caller yet (no invoice/payment module exists), so verified
standalone here, same as tests/test_common_validation.py."""
import io

import pytest
from PIL import Image

from app.core.qr import generate_qr_code, validate_qr_url

ALLOWED = ["pay.jdk.com", "jdk.com"]


class TestValidateQrUrl:
    def test_accepts_an_approved_https_domain(self):
        assert validate_qr_url("https://pay.jdk.com/i/123", ALLOWED) == "https://pay.jdk.com/i/123"

    def test_rejects_a_domain_not_on_the_allow_list(self):
        with pytest.raises(ValueError, match="not an approved"):
            validate_qr_url("https://evil.com/i/123", ALLOWED)

    def test_rejects_http_when_https_is_required(self):
        with pytest.raises(ValueError, match="HTTPS"):
            validate_qr_url("http://pay.jdk.com/i/123", ALLOWED)

    def test_allows_http_when_https_is_not_required(self):
        assert validate_qr_url("http://pay.jdk.com/i/123", ALLOWED, require_https=False)

    def test_rejects_a_malformed_url(self):
        with pytest.raises(ValueError, match="not a valid URL"):
            validate_qr_url("not-a-url", ALLOWED)

    def test_rejects_when_no_domains_are_configured(self):
        with pytest.raises(ValueError, match="No allowed QR domains"):
            validate_qr_url("https://pay.jdk.com/i/123", [])

    def test_is_case_insensitive_on_the_domain(self):
        assert validate_qr_url("https://PAY.JDK.COM/i/123", ALLOWED)


class TestGenerateQrCode:
    def test_rejects_an_unapproved_domain_before_generating(self):
        with pytest.raises(ValueError, match="not an approved"):
            generate_qr_code("https://evil.com/i/123", ALLOWED)

    def test_generates_a_scannable_png_for_an_approved_url(self):
        png_bytes = generate_qr_code("https://pay.jdk.com/i/123", ALLOWED)
        image = Image.open(io.BytesIO(png_bytes))
        assert image.format == "PNG"
        assert image.size[0] > 0 and image.size[1] > 0
