from __future__ import annotations

import csv
import io
import json
from zipfile import ZIP_DEFLATED, ZipFile
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter


DEFAULT_COLUMNS = [
    ("batch_reference", "Batch reference"), ("sequence", "Sequence"), ("execution_date", "Execution date"), ("debit_account", "Debit account"),
    ("employee_reference", "Employee reference"), ("recipient_name", "Recipient name"), ("bank_code", "Bank code"), ("bic", "BIC"),
    ("account_number", "Account number"), ("amount", "Amount"), ("currency", "Currency"), ("purpose", "Purpose"), ("reference", "Reference"),
]


def _xlsx_content(columns: list[Mapping[str, Any]], rows: list[Mapping[str, Any]], template: Mapping[str, Any]) -> bytes:
    values: list[list[Any]] = []
    values.extend(template.get("header_rows", []))
    if template.get("include_header", True):
        values.append([column.get("header", column["key"]) for column in columns])
    values.extend([[row[column["key"]] for column in columns] for row in rows])
    values.extend(template.get("trailer_rows", []))

    def cell(value: Any, column: int) -> str:
        ref = ""
        n = column
        while n:
            n, remainder = divmod(n - 1, 26)
            ref = chr(65 + remainder) + ref
        text = escape("" if value is None else str(value))
        return f'<c r="{ref}{row_number}" t="inlineStr"><is><t>{text}</t></is></c>'

    xml_rows = []
    for row_number, values_row in enumerate(values, start=1):
        xml_rows.append(f'<row r="{row_number}">' + "".join(cell(value, index) for index, value in enumerate(values_row, start=1)) + "</row>")
    sheet = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(xml_rows) + "</sheetData></worksheet>"
    workbook = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Payroll" sheetId="1" r:id="rId1"/></sheets></workbook>'
    content_types = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'
    relationships = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    workbook_relationships = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return output.getvalue()


def render_bank_export(rows: Iterable[Mapping[str, Any]], template: Mapping[str, Any] | None = None, format: str = "csv") -> tuple[str, bytes]:
    template = template or {}
    columns = template.get("columns") or [{"key": key, "header": header} for key, header in DEFAULT_COLUMNS]
    date_format = template.get("date_format")
    decimal_separator = template.get("decimal_separator")
    decimal_keys = set(template.get("decimal_keys") or {"amount", "value", "total"})
    decimal_places = template.get("decimal_places")

    def format_value(key: str, value: Any) -> Any:
        if value in (None, ""):
            return ""
        if date_format and (key.endswith("_date") or key in {"execution_date", "value_date"}):
            try:
                parsed = datetime.fromisoformat(str(value)).date() if "T" in str(value) else date.fromisoformat(str(value))
                return parsed.strftime(date_format)
            except ValueError:
                return value
        if decimal_separator and (key in decimal_keys or key.endswith("_amount") or key.endswith("_total")):
            formatted = str(value)
            if decimal_places is not None:
                try:
                    formatted = f"{Decimal(str(value)):.{int(decimal_places)}f}"
                except (ValueError, TypeError, ArithmeticError):
                    return value
            return formatted.replace(".", decimal_separator)
        return value

    projected = [{column["key"]: format_value(column["key"], row.get(column["key"], "")) for column in columns} for row in rows]
    if format == "json":
        return template.get("filename", "payroll-payout.json"), json.dumps(projected, ensure_ascii=False, separators=(",", ":")).encode(template.get("encoding", "utf-8"))
    if format == "xlsx":
        return template.get("filename", "payroll-payout.xlsx"), _xlsx_content(columns, projected, template)
    delimiter = template.get("delimiter", ",")
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=delimiter, lineterminator=template.get("line_ending", "\n"))
    for header_row in template.get("header_rows", []): writer.writerow(header_row)
    if template.get("include_header", True): writer.writerow([column.get("header", column["key"]) for column in columns])
    for row in projected: writer.writerow([row[column["key"]] for column in columns])
    for trailer_row in template.get("trailer_rows", []): writer.writerow(trailer_row)
    return template.get("filename", "payroll-payout.csv"), output.getvalue().encode(template.get("encoding", "utf-8"))


def render_protected_payslip(lines: Iterable[str], password: str) -> bytes:
    """Render a small text payslip PDF and encrypt it with the employee's chosen password."""
    escaped_lines = []
    for line in lines:
        safe = str(line).encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        escaped_lines.append(f"({safe}) Tj 0 -18 Td")
    stream = ("BT /F1 11 Tf 50 790 Td " + " ".join(escaped_lines) + " ET").encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    raw = io.BytesIO()
    raw.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(raw.tell())
        raw.write(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = raw.tell()
    raw.write(f"xref\n0 {len(objects) + 1}\n".encode())
    raw.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        raw.write(f"{offset:010d} 00000 n \n".encode())
    raw.write(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    reader = PdfReader(io.BytesIO(raw.getvalue()))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.encrypt(password)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def nd7_summary(payslips: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    payslips = list(payslips)
    totals = defaultdict(lambda: Decimal("0"))
    fund_totals = defaultdict(lambda: Decimal("0"))
    for slip in payslips:
        totals["employee_shi"] += Decimal(str(slip.get("employee_shi", 0)))
        totals["employer_shi"] += Decimal(str(slip.get("employer_shi", 0)))
        totals["shi_base"] += Decimal(str(slip.get("shi_base", 0)))
        totals["insurable_earnings"] += Decimal(str(slip.get("shi_subject_gross", slip.get("gross", 0))))
        for fund, amount in (slip.get("shi_by_fund") or {}).items():
            fund_totals[str(fund)] += Decimal(str(amount))
    return {key: str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) for key, value in totals.items()} | {"employee_count": len(payslips), "fund_breakdown": {key: str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) for key, value in fund_totals.items()}}


def nd8_rows(payslips: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for slip in payslips:
        rows.append({"employee_id": slip.get("employee_id"), "insured_code": slip.get("insured_code"), "payable_days": slip.get("payable_days", "0"), "insurable_earnings": str(slip.get("shi_subject_gross", slip.get("gross", 0))), "shi_base": str(slip.get("shi_base", 0)), "employee_shi": str(slip.get("employee_shi", 0)), "employer_shi": str(slip.get("employer_shi", 0)), "fund_breakdown": slip.get("shi_by_fund") or {}})
    return rows


def tt11_summary(payslips: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    totals = defaultdict(lambda: Decimal("0"))
    for slip in payslips:
        totals["employment_income"] += Decimal(str(slip.get("gross", 0)))
        totals["shi_deduction"] += Decimal(str(slip.get("employee_shi", 0)))
        totals["taxable_income"] += Decimal(str(slip.get("taxable_income", 0)))
        totals["pit_before_relief"] += Decimal(str(slip.get("pit_before_relief", 0)))
        totals["relief"] += Decimal(str(slip.get("pit_relief", 0)))
        totals["pit_withheld"] += Decimal(str(slip.get("pit", 0)))
    return {key: str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) for key, value in totals.items()}
