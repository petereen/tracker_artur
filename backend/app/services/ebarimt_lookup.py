"""Mongolian tax-office (e-Barimt) taxpayer lookup.

Dayansoft d026 “РД-аар татвараас (Нэр, ТТД, НӨАТ, НХАТ) татах”: a registry
number resolves to a TIN, and the TIN resolves to the official name and the
VAT / city-tax payer status. The public service is often unavailable, so
callers must treat every failure as “enter the details manually”.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import httpx

EBARIMT_INFO_BASE_URL = "https://api.ebarimt.mn/api/info/check"
LOOKUP_TIMEOUT_SECONDS = 8.0


class TaxpayerLookupError(Exception):
    """The tax office could not be reached or did not recognise the number."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TaxpayerInfo:
    registry_no: str | None
    tin: str
    name: str | None
    vat_payer: bool
    city_tax_payer: bool
    found: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _payload_data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def parse_tin_response(payload: Any) -> str | None:
    """``getTinInfo`` returns the TIN either bare or inside ``data``."""
    data = _payload_data(payload)
    if isinstance(data, dict):
        data = data.get("tin") or data.get("TIN")
    if data in (None, "", 0):
        return None
    return str(data).strip() or None


def parse_info_response(payload: Any, *, tin: str, registry_no: str | None = None) -> TaxpayerInfo:
    data = _payload_data(payload)
    if not isinstance(data, dict):
        raise TaxpayerLookupError("ebarimt_unexpected_response", "Татварын системээс ирсэн хариу танигдсангүй")
    name = data.get("name") or data.get("Name")
    return TaxpayerInfo(
        registry_no=registry_no,
        tin=tin,
        name=str(name).strip() if name else None,
        vat_payer=bool(data.get("vatPayer") or data.get("vat_payer")),
        city_tax_payer=bool(data.get("cityPayer") or data.get("city_payer") or data.get("cityTaxPayer")),
        found=bool(data.get("found", bool(name))),
    )


async def _get_json(client: httpx.AsyncClient, path: str, params: dict[str, str]) -> Any:
    try:
        response = await client.get(f"{EBARIMT_INFO_BASE_URL}/{path}", params=params)
    except httpx.HTTPError as exc:
        raise TaxpayerLookupError("ebarimt_unavailable", "Татварын систем рүү холбогдож чадсангүй. Мэдээллийг гараар оруулна уу.") from exc
    if response.status_code >= 400:
        raise TaxpayerLookupError("ebarimt_unavailable", f"Татварын систем {response.status_code} алдаа буцаалаа. Мэдээллийг гараар оруулна уу.")
    try:
        return response.json()
    except ValueError as exc:
        raise TaxpayerLookupError("ebarimt_unexpected_response", "Татварын системээс ирсэн хариу танигдсангүй") from exc


async def lookup_taxpayer(*, registry_no: str | None = None, tin: str | None = None, client: httpx.AsyncClient | None = None) -> TaxpayerInfo:
    registry_no = (registry_no or "").strip().upper() or None
    tin = (tin or "").strip() or None
    if not registry_no and not tin:
        raise TaxpayerLookupError("ebarimt_number_required", "Регистр эсвэл ТТД оруулна уу")
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=LOOKUP_TIMEOUT_SECONDS)
    try:
        if not tin:
            tin = parse_tin_response(await _get_json(client, "getTinInfo", {"regNo": registry_no or ""}))
            if not tin:
                raise TaxpayerLookupError("ebarimt_not_found", "Энэ регистрээр татвар төлөгч олдсонгүй")
        info = parse_info_response(await _get_json(client, "getInfo", {"tin": tin}), tin=tin, registry_no=registry_no)
        if not info.found:
            raise TaxpayerLookupError("ebarimt_not_found", "Татвар төлөгч олдсонгүй")
        return info
    finally:
        if owns_client:
            await client.aclose()
