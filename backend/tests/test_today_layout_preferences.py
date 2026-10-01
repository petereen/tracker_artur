import pytest

from app.main import app
from app.routers.enterprise_auth import TODAY_LAYOUT_MAX_WIDGETS, TodayLayoutPreferences, TodayWidget


def widget(**overrides):
    return {"id": "w1", "type": "world-clock", "x": 0, "y": 0, "w": 12, "h": 1, "settings": {}, **overrides}


def test_today_layout_route_is_registered():
    paths = {route.path for route in app.routes}
    assert "/v1/auth/preferences/today-layout" in paths


def test_today_layout_defaults_to_uncustomised():
    default = TodayLayoutPreferences()
    assert default.widgets is None
    assert default.updated_at is None
    assert TodayLayoutPreferences(widgets=[]).widgets == []


def test_today_layout_accepts_widgets_with_settings():
    layout = TodayLayoutPreferences.model_validate({
        "updated_at": 1_700_000_000_000,
        "widgets": [
            widget(),
            widget(id="kpi-1", type="kpi", x=7, y=1, w=5, h=6, settings={"period": "previous_week"}),
            widget(id="notes-2", type="notes", x=0, y=7, w=4, h=5, settings={"text": "Сайн уу"}),
        ],
    })
    assert [item.id for item in layout.widgets] == ["w1", "kpi-1", "notes-2"]
    assert layout.widgets[1].settings == {"period": "previous_week"}


@pytest.mark.parametrize("bad", [
    {"x": 8, "w": 5},          # overflows 12 columns
    {"x": -1},
    {"w": 0},
    {"h": 41},
    {"y": 401},
    {"type": "Bad Type"},
    {"id": "has space"},
    {"settings": {"text": "x" * 16_001}},
])
def test_today_widget_rejects_out_of_bounds_values(bad):
    with pytest.raises(ValueError):
        TodayWidget.model_validate(widget(**bad))


def test_today_layout_rejects_duplicate_ids_and_too_many_widgets():
    with pytest.raises(ValueError):
        TodayLayoutPreferences(widgets=[widget(), widget()])
    with pytest.raises(ValueError):
        TodayLayoutPreferences(widgets=[widget(id=f"w{index}") for index in range(TODAY_LAYOUT_MAX_WIDGETS + 1)])
