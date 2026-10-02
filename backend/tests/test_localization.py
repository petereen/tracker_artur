import ast
import re
from pathlib import Path

from app.core.localization import request_language, resolve_language, translate_detail


def test_accept_language_uses_quality_and_supported_language_fallback():
    assert request_language("ru,en;q=0.9") == "ru"
    assert request_language("fr-CA,en-US;q=0.8") == "en"
    assert request_language("fr-CA") == "mn"
    assert request_language(None) == "mn"


def test_accept_language_ignores_zero_quality_and_invalid_values():
    assert request_language("en;q=0,ru;q=0.7") == "ru"
    assert request_language("en;q=invalid") == "mn"


def test_recipient_language_uses_supported_account_employee_and_platform_fallbacks():
    assert resolve_language("en-US", "ru", "mn") == "en"
    assert resolve_language(None, "ru-RU", "en") == "ru"
    assert resolve_language(None, None, "en-US") == "en"
    assert resolve_language(None, "xx") == "mn"


def test_error_localization_keeps_detail_shape_and_machine_codes():
    assert translate_detail("Invalid credentials", "en") == "The email or password is incorrect."
    value = {"code": "tenant_boundary", "message": "Хандах эрхгүй өгөгдөл.", "monthly_path": "/monthly"}
    assert translate_detail(value, "en") == {
        "code": "tenant_boundary",
        "message": "You do not have permission to access this data.",
        "monthly_path": "/monthly",
    }
    assert translate_detail("An application-specific error", "en") == "An application-specific error"
    assert translate_detail("Invalid credentials", "mn") == "Invalid credentials"


def test_dynamic_payroll_error_localizes_system_labels_and_preserves_account_data():
    source = "Цалингийн зардлын данс: 7010 · Цалин бодит данс «Зардал» ангиллынх байх ёстой."
    assert translate_detail(source, "en") == "Salary expense account: account 7010 · Цалин бодит must be classified as expenses."
    assert translate_detail(source, "ru") == "Счёт расходов на оплату труда: счёт 7010 · Цалин бодит должен относиться к категории «расходы»."


def test_dynamic_error_messages_localize_without_changing_codes_or_values():
    source = {
        "code": "outside_worktime_geofence",
        "message": "Та оффисоос 125м зайтай байна. Ажил эхлүүлэхийн тулд 100м дотор очно уу.",
        "distance_m": 125,
        "radius_m": 100,
    }
    assert translate_detail(source, "en") == {
        "code": "outside_worktime_geofence",
        "message": "You are 125 m from the office. Move within 100 m to start work.",
        "distance_m": 125,
        "radius_m": 100,
    }
    assert translate_detail({"code": "telegram_id_invalid", "message": "Telegram ID зөвхөн тооноос бүрдэнэ: abc"}, "en")["message"] == "Telegram ID must contain digits only: abc"
    assert translate_detail({"code": "erp_role_unknown_capability", "message": "Тодорхойгүй эрх: payroll.approve"}, "ru")["message"] == "Неизвестное разрешение: payroll.approve"
    assert translate_detail({"code": "seat_limit_reached", "message": "Лицензийн хэрэглэгчийн хязгаар (10) дүүрсэн байна: 10 идэвхтэй хэрэглэгч. Шинэ хэрэглэгч нэмэхийн тулд багцаа өргөтгөх эсвэл идэвхгүй хэрэглэгчийг хаана уу."}, "en")["message"].startswith("The license limit of 10 users")
    assert translate_detail({"message": "Хэлтэст 3 ажилтан бүртгэлтэй. Эхлээд ажилтнуудыг өөр хэлтэс рүү шилжүүлэх, эсвэл хэлтсийг идэвхгүй болгоно уу."}, "en")["message"].startswith("This department has 3 employees")
    assert translate_detail({"message": "Бат: Excel-ийн утга буруу байна."}, "ru")["message"] == "Бат: Недопустимое значение Excel."
    assert translate_detail({"message": "Тест: шалгах тэмдэглэгээтэй мөрийг эхлээд цэвэрлэнэ үү."}, "en")["message"] == "Тест: Clear the flagged row before importing."


def test_every_fixed_cyrillic_http_error_has_english_and_russian_copy():
    app_root = Path(__file__).parents[1] / "app"
    details = set()
    for path in app_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "HTTPException":
                continue
            for keyword in node.keywords:
                if keyword.arg == "detail" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    detail = keyword.value.value
                    if re.search(r"[А-Яа-яӨҮөү]", detail):
                        details.add(detail)
    assert details
    assert all(translate_detail(detail, "en") != detail for detail in details)
    assert all(translate_detail(detail, "ru") != detail for detail in details)


def test_every_fixed_cyrillic_http_error_message_object_has_english_and_russian_copy():
    app_root = Path(__file__).parents[1] / "app"
    messages = set()
    for path in app_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "HTTPException":
                continue
            for keyword in node.keywords:
                if keyword.arg != "detail":
                    continue
                for detail in ast.walk(keyword.value):
                    if not isinstance(detail, ast.Dict):
                        continue
                    for key, value in zip(detail.keys, detail.values):
                        if key and isinstance(key, ast.Constant) and key.value == "message" and isinstance(value, ast.Constant) and isinstance(value.value, str) and re.search(r"[А-Яа-яӨҮөү]", value.value):
                            messages.add(value.value)
    assert messages
    assert all(translate_detail(message, "en") != message for message in messages)
    assert all(translate_detail(message, "ru") != message for message in messages)


def test_auth_email_copy_is_available_in_all_supported_languages(monkeypatch, tmp_path):
    # Settings loads ``.env`` from cwd; run outside the checkout so unrelated
    # local compose/Vite variables cannot leak into this isolated service test.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
    monkeypatch.setenv("SYNC_DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    from app.services.email_service import _content

    for language, expected in (("mn", "Нууц үг"), ("ru", "парол"), ("en", "password")):
        subject, text, html = _content("password_reset", "https://example.test/reset", language)
        assert expected.casefold() in f"{subject} {text} {html}".casefold()
        assert "https://example.test/reset" in text
        assert "https://example.test/reset" in html


def test_generated_notifications_and_telegram_delivery_render_by_locale(monkeypatch):
    from app.services.notification_localization import notification_copy, render_notification_payload

    source_title, source_body = "Mongolian source", "Mongolian body"
    assert notification_copy("contract_approved", source_title, source_body, "en") == (
        "Contract approved", "The contract is approved. Print, sign, and certify the document.",
    )
    assert notification_copy("contract_approved", source_title, source_body, "ru")[0] == "Договор утверждён"
    assert notification_copy("unknown_kind", source_title, source_body, "en") == (source_title, source_body)

    payload = {
        "locale": "en",
        "template_key": "notification.contract_approved",
        "template_params": {"source_title": source_title, "source_body": source_body},
        "target_url": "/contracts/12",
    }
    english_title, english_body = render_notification_payload("contract_approved", payload, "en")
    russian_title, _ = render_notification_payload("contract_approved", payload, "ru")
    assert english_title == "Contract approved"
    assert english_body == "The contract is approved. Print, sign, and certify the document."
    assert "Mongolian source" not in english_title + english_body
    assert russian_title == "Договор утверждён"
