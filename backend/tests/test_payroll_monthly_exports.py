from datetime import date
from decimal import Decimal
from io import BytesIO

from openpyxl import load_workbook

from app.payroll.monthly_engine import PayrollProfile, PayrollRunType, calculate_monthly_run, default_2026_rules, overtime_day_lines
from app.payroll.monthly_exports import FINAL_COLUMNS, build_run_workbook, company_title, split_name


D = Decimal


def test_overtime_lines_reconcile_to_engine_cells_for_section18_example():
    rules = default_2026_rules()
    hours = {"weekday": D("4"), "rest_day": D("8"), "public_holiday": D("8")}
    result = calculate_monthly_run(
        PayrollRunType.FINAL, PayrollProfile(base_salary=D("1500000")), rules=rules,
        planned_days=21, planned_hours=168, worked_normal_hours=168, overtime_hours=hours,
    )
    assert result.overtime_by_bucket == {"weekday": D("53571"), "rest_day": D("107143"), "public_holiday": D("142857")}
    day_lines = [
        {"date": "2026-08-03", "day_type": "working", "overtime_hours": {"weekday": "2"}},
        {"date": "2026-08-04", "day_type": "working", "overtime_hours": {"weekday": "2"}},
        {"date": "2026-08-08", "day_type": "weekly_rest", "overtime_hours": {"rest_day": "8"}},
        {"date": "2026-08-15", "day_type": "public_holiday", "overtime_hours": {"public_holiday": "8"}},
    ]
    lines = overtime_day_lines(
        day_lines=day_lines, aggregate_hours=hours, bucket_totals=result.overtime_by_bucket,
        salary_segments=[], base_salary=D("1500000"), planned_hours=D("168"), multipliers=rules.overtime_multipliers,
    )
    assert [line["date"] for line in lines] == ["2026-08-03", "2026-08-04", "2026-08-08", "2026-08-15"]
    for bucket, total in result.overtime_by_bucket.items():
        assert sum(D(line["amount"]) for line in lines if line["bucket"] == bucket) == total
    assert sum(D(line["amount"]) for line in lines) == result.overtime_pay == D("303571")
    assert lines[0]["rate"] == "8928.57" and lines[0]["weekday"] == 0


def test_overtime_lines_fall_back_to_manual_bucket_when_hours_were_edited():
    rules = default_2026_rules()
    lines = overtime_day_lines(
        day_lines=[{"date": "2026-08-03", "day_type": "working", "overtime_hours": {"weekday": "2"}}],
        aggregate_hours={"weekday": "5"}, bucket_totals={"weekday": "66964"}, salary_segments=[],
        base_salary="1500000", planned_hours="168", multipliers=rules.overtime_multipliers,
    )
    assert len(lines) == 1 and lines[0]["source"] == "manual" and lines[0]["date"] is None
    assert lines[0]["amount"] == "66964"


def test_overtime_lines_use_the_salary_in_force_on_each_date():
    lines = overtime_day_lines(
        day_lines=[
            {"date": "2026-08-05", "day_type": "working", "overtime_hours": {"weekday": "1"}},
            {"date": "2026-08-20", "day_type": "working", "overtime_hours": {"weekday": "1"}},
        ],
        aggregate_hours={"weekday": "2"}, bucket_totals={"weekday": "22322"},
        salary_segments=[
            {"monthly_salary": "1000000", "valid_from": "2026-08-01", "valid_to": "2026-08-14"},
            {"monthly_salary": "1500000", "valid_from": "2026-08-15", "valid_to": "2026-08-31"},
        ],
        base_salary="1500000", planned_hours="168", multipliers={"weekday": "1.5"},
    )
    assert [line["rate"] for line in lines] == ["5952.38", "8928.57"]
    assert sum(D(line["amount"]) for line in lines) == D("22322")


def _final_row(name, department, gross, net, **extra):
    return {
        "identity": {"name": name, "department": department, "rd": "УБ90010101", "job_title": "Нягтлан", "pay_date": "2026-08-25"},
        "profile": {"base_salary": "1500000", "salary_type": "PRORATION"},
        "inputs": {"worked_normal_hours": "168", "leave_pay": "168000", "bonus": "0", "overtime_hours": {}, "other_deductions": [{"type": "Торгууль", "amount": "50000", "note": "хоцролт"}]},
        "result": {"planned_days": 21, "planned_hours": "168", "base_pay": "1500000", "overtime_pay": "0", "meal_commute": "120000", "gross": gross,
                   "shi_base": gross, "employee_shi": "205620", "relief": "14000", "pit": "144238", "advance": "600000", "other_deductions": "50000",
                   "total_deductions": str(D(gross) - D(net)), "net_pay": net, "employer_shi": "223500", "overtime_lines": [], **extra},
        "payout": {"bank_code": "KHAN", "account_number": "5000123456"},
    }


def test_final_workbook_follows_excel_layout_with_groups_subtotals_and_sheets():
    rows = [_final_row("Бат Оюун-Эрдэнэ", "Санхүү", "1788000", "788142"), _final_row("Дорж Сараа", "Борлуулалт", "1788000", "788142")]
    stats = {"totals": {"gross": "3576000", "company_cost": "4023000"}, "headcount": {"on_register": 2}, "accounting": {"account_a": {"total": "3576000", "lines": {}}, "account_b": {"total": "447000"}, "advance_reconciliation": {"matches": True}}, "by_department": {"Санхүү": {"headcount": 1, "gross": "1788000"}}}
    content = build_run_workbook(run_type="final", pay_date=date(2026, 8, 31), year=2026, month=8, rows=rows, company="Оюунс", rule_snapshot={"employee_rates": {"pension": "0.085"}, "employer_rates": {"pension": "0.085"}}, stats=stats)
    workbook = load_workbook(BytesIO(content))
    assert workbook.sheetnames == ["Цалингийн хүснэгт", "Дүн", "Илүү цаг", "НДШ задаргаа", "Төлбөрийн жагсаалт", "Бусад суутгал"]
    sheet = workbook["Цалингийн хүснэгт"]
    assert sheet["A1"].value == '"Оюунс" ХХК-ийн 2026 оны 08 сарын цалингийн хүснэгт'
    assert sheet.cell(3, 7).value == "Ажиллах" and sheet.cell(3, 17).value == "Суутгалууд"
    assert [sheet.cell(4, column).value for column in (7, 8, 17, 21)] == ["Өдөр", "Цаг", "НДШ", "Бусад суутгал"]
    assert [sheet.cell(3, column).value for column in (1, 2, 3, 16, 22, 23, 24)] == ["№", "Овог", "Нэр", "Олговол зохих цалин", "Суутгалын дүн", "Гарт олгох цалин", "БНДШ"]
    assert len(FINAL_COLUMNS) == 24
    values = [cell.value for row in sheet.iter_rows() for cell in row]
    assert "Борлуулалт" in values and "Санхүү — дүн" in values and "НИЙТ ДҮН" in values
    assert "БНДШ – Байгууллагын төлөх нийгмийн даатгалын шимтгэл" in values
    data_row = next(row for row in sheet.iter_rows(min_row=5) if row[2].value == "Сараа")
    assert data_row[1].value == "Дорж" and data_row[15].value == 1788000 and data_row[22].value == 788142
    assert any(isinstance(value, str) and value.startswith("=SUBTOTAL(9,") for value in values)
    assert sheet.page_setup.orientation == "landscape"
    payments = [cell.value for row in workbook["Төлбөрийн жагсаалт"].iter_rows() for cell in row]
    assert "Төлбөрийн өдөр: 2026-08-25" in payments
    deductions = [cell.value for row in workbook["Бусад суутгал"].iter_rows() for cell in row]
    assert "Торгууль" in deductions and 50000 in deductions


def test_advance_workbook_title_register_and_missing_bank_flag():
    row = {
        "identity": {"name": "Бат", "department": "Санхүү", "pay_date": "2026-08-10"},
        "profile": {"base_salary": "1500000", "salary_type": "PRORATION", "advance_basis": "PERCENT"},
        "inputs": {}, "result": {"advance": "600000", "advance_basis": "PERCENT", "advance_value": "40"}, "payout": None,
    }
    workbook = load_workbook(BytesIO(build_run_workbook(run_type="advance", pay_date=date(2026, 8, 10), year=2026, month=8, rows=[row], company="Оюунс ХХК", rule_snapshot={})))
    assert workbook.sheetnames == ["Урьдчилгаа", "Төлбөрийн жагсаалт"]
    assert workbook["Урьдчилгаа"]["A1"].value == "Оюунс ХХК-ийн 08 сарын урьдчилгаа цалин (10 өдөр)"
    register = [cell.value for row_cells in workbook["Урьдчилгаа"].iter_rows() for cell in row_cells]
    assert "40%" in register and 600000 in register
    payments = [cell.value for row_cells in workbook["Төлбөрийн жагсаалт"].iter_rows() for cell in row_cells]
    assert "Банкны мэдээлэл дутуу" in payments


def test_advance_register_shows_projected_month_breakdown_and_employer_shi():
    projection = {
        "base_pay": "3875455", "overtime_pay": "0", "meal_commute": "550000", "gross": "4425455", "employee_shi": "508927",
        "relief": "0", "pit": "391653", "advance": "2000000", "total_deductions": "3450580", "net_pay": "974875", "employer_shi": "553182",
    }
    row = {
        "identity": {"name": "Ochirbat Temuulen", "department": "Систем хөгжүүлэлт", "pay_date": "2026-09-05"},
        "profile": {"base_salary": "4000000", "salary_type": "PRORATION", "advance_basis": "FIXED"},
        "inputs": {"worked_normal_hours": "213.15", "worked_days": 22, "overtime_hours": {}, "leave_pay": "0", "bonus": "0"},
        "result": {"advance": "2000000", "advance_basis": "FIXED", "advance_value": "2000000", "planned_days": 22, "planned_hours": "220", "projection": projection},
        "payout": None,
    }
    workbook = load_workbook(BytesIO(build_run_workbook(run_type="advance", pay_date=date(2026, 9, 5), year=2026, month=9, rows=[row], company="OYUNS", rule_snapshot={})))
    sheet = workbook["Урьдчилгаа"]
    header = {sheet.cell(4, column).value or sheet.cell(3, column).value: column for column in range(1, sheet.max_column + 1)}
    assert "Таслах өдөр хүртэл цаг" not in header
    assert [sheet.cell(3, header[label]).value for label in ("Суурь", "Өдөр", "НДШ")] == ["Урьдчилгааны тооцоо", "Ажиллах", "Суутгалууд"]
    data_row = next(row_cells for row_cells in sheet.iter_rows(min_row=5) if row_cells[2].value == "Temuulen")
    cell = {label: data_row[column - 1].value for label, column in header.items()}
    assert cell["Олговол зохих цалин"] == 4425455 and cell["НДШ"] == 508927 and cell["ХХОАТ"] == 391653 and cell["Урьдчилгаа"] == 2000000
    assert cell["Суутгалын дүн"] == 3450580 and cell["Сүүл цалин (тооцоолсон)"] == 974875 and cell["БНДШ"] == 553182
    assert cell["Ажилласан цаг"] == 213.15 and cell["Хоол унаа"] == 550000 and cell["Төлбөрийн өдөр"] == "2026-09-05"
    values = [cell.value for row_cells in sheet.iter_rows() for cell in row_cells]
    assert any(isinstance(value, str) and "БНДШ – Байгууллагын" in value for value in values)


def test_name_split_and_company_title_helpers():
    assert split_name({"name": "Бат Оюун-Эрдэнэ"}) == ("Бат", "Оюун-Эрдэнэ")
    assert split_name({"name": "Сараа", "last_name": "Дорж", "first_name": "Сараа"}) == ("Дорж", "Сараа")
    assert company_title(None, "x") == '"Байгууллага" ХХК-ийн x'
