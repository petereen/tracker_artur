import base64

import pytest
from pydantic import ValidationError

from app.services.tenant_branding import FAVICON_MAX_BYTES, BrandingInput

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _data(content: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(content).decode()}"


def test_attached_png_is_accepted_for_logo_and_favicon():
    data = BrandingInput(logo_url=_data(PNG), favicon_url=_data(PNG))
    assert data.logo_url.startswith("data:image/png;base64,")
    assert data.favicon_url == data.logo_url


@pytest.mark.parametrize("value", [
    _data(b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
    _data(b"not a png"),
    "data:text/html;base64,PHNjcmlwdD4=",
    "data:image/png;base64,@@@",
])
def test_unsafe_attachments_are_rejected(value):
    with pytest.raises(ValidationError):
        BrandingInput(logo_url=value)


def test_favicon_size_limit_is_stricter_than_logo():
    big = PNG + b"\x00" * FAVICON_MAX_BYTES
    assert BrandingInput(logo_url=_data(big)).logo_url
    with pytest.raises(ValidationError):
        BrandingInput(favicon_url=_data(big))


def test_plain_urls_still_validated():
    assert BrandingInput(logo_url="https://x.test/l.png").logo_url == "https://x.test/l.png"
    with pytest.raises(ValidationError):
        BrandingInput(logo_url="javascript:alert(1)")
