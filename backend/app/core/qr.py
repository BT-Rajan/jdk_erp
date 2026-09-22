import io
from urllib.parse import urlparse

import qrcode
from PIL import Image
from qrcode.constants import ERROR_CORRECT_H

# One fixed logo-sizing ratio for every JDK-branded QR code -- so no
# module invents its own branding treatment (docs/modules/common_validation.md
# #5). Error-correction level H (up to ~30% of modules can be obscured)
# is chosen specifically so this overlay never compromises scannability.
_LOGO_SIZE_RATIO = 0.22


def validate_qr_url(url: str, allowed_domains: list[str], *, require_https: bool = True) -> str:
    """The one check before any JDK-branded QR code is generated
    (docs/modules/common_validation.md #5) -- only an approved
    JDK/company domain (app.core.config.settings.allowed_qr_domains) may
    be presented as an official QR code, and production destinations
    must be HTTPS. Raises ValueError with a user-facing message; never
    silently accepts an arbitrary external URL."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"'{url}' is not a valid URL.")
    if require_https and parsed.scheme != "https":
        raise ValueError("QR destinations must use HTTPS.")
    if not allowed_domains:
        raise ValueError("No allowed QR domains are configured.")
    if parsed.hostname.lower() not in allowed_domains:
        raise ValueError(f"'{parsed.hostname}' is not an approved JDK/company domain.")
    return url


def generate_qr_code(
    url: str,
    allowed_domains: list[str],
    *,
    require_https: bool = True,
    logo_path: str | None = None,
) -> bytes:
    """Validates `url` (see validate_qr_url) then renders it as a PNG QR
    code, with the standard JDK/company logo centered on top when
    `logo_path` is given. The one QR generation path for the whole
    project -- individual modules pass the URL and get branded, validated
    bytes back rather than building their own QR image."""
    validate_qr_url(url, allowed_domains, require_https=require_https)

    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_H, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    if logo_path is not None:
        logo = Image.open(logo_path).convert("RGBA")
        logo_size = int(image.size[0] * _LOGO_SIZE_RATIO)
        logo = logo.resize((logo_size, logo_size))
        position = ((image.size[0] - logo_size) // 2, (image.size[1] - logo_size) // 2)
        image.paste(logo, position, logo)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
