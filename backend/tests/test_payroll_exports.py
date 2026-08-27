from zipfile import ZipFile
from io import BytesIO

from pypdf import PdfReader

from app.payroll.exports import nd7_summary, nd8_rows, render_bank_export, render_protected_payslip


def test_bank_renderer_honours_date_decimal_and_trailer_configuration():
    filename, content = render_bank_export(
        [{"execution_date": "2026-08-31", "amount": "1234.50"}],
        {"columns": [{"key": "execution_date"}, {"key": "amount"}], "date_format": "%d.%m.%Y", "decimal_separator": ",", "trailer_rows": [["END"]]},
    )
    assert filename == "payroll-payout.csv"
    assert content.decode() == "execution_date,amount\n31.08.2026,\"1234,50\"\nEND\n"


def test_xlsx_renderer_is_a_valid_zip_package_and_reports_preserve_shi_subject():
    filename, content = render_bank_export([{"amount": "10.00"}], {"columns": [{"key": "amount"}]}, "xlsx")
    assert filename.endswith(".xlsx")
    with ZipFile(BytesIO(content)) as archive:
        assert "xl/worksheets/sheet1.xml" in archive.namelist()
    rows = nd8_rows([{"employee_id": 1, "shi_subject_gross": "20", "shi_base": "10", "employee_shi": "1", "employer_shi": "2"}])
    assert rows[0]["insurable_earnings"] == "20"
    assert nd7_summary([{"shi_subject_gross": "20", "shi_base": "10", "employee_shi": "1", "employer_shi": "2"}])["insurable_earnings"] == "20.00"


def test_payslip_pdf_requires_the_employee_selected_password():
    payload = render_protected_payslip(["Payroll PR-1", "Net pay: 1000 MNT"], "strong-passphrase")
    reader = PdfReader(BytesIO(payload))
    assert reader.is_encrypted is True
    assert reader.decrypt("wrong-password") == 0
    assert reader.decrypt("strong-passphrase") != 0
