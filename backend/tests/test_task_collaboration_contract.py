from pathlib import Path

import pytest
from pydantic import ValidationError

from app.main import app
from app.routers.enterprise import DependencyInput
from app.services.user_notifications import create_notifications


def test_task_collaboration_routes_and_relationship_types_are_public():
    paths = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    assert {
        ("/v1/tasks/{task_id}/dependencies", "GET"),
        ("/v1/tasks/{task_id}/dependencies", "POST"),
        ("/v1/tasks/{task_id}/check-items", "POST"),
        ("/v1/tasks/{task_id}/comments", "POST"),
        ("/v1/tasks/{task_id}/comments/{comment_id}", "DELETE"),
        ("/v1/tasks/{task_id}/activity", "GET"),
        ("/v1/attachments", "POST"),
    }.issubset(paths)
    assert DependencyInput(predecessor_task_id=2).dependency_type == "blocks"
    assert DependencyInput(predecessor_task_id=2, dependency_type="related").dependency_type == "related"
    with pytest.raises(ValidationError):
        DependencyInput(predecessor_task_id=2, dependency_type="unknown")


def test_collaboration_notifications_stay_web_only_and_history_is_task_scoped():
    notification_source = Path(create_notifications.__code__.co_filename).read_text()
    router_source = (Path(__file__).parents[1] / "app/routers/enterprise.py").read_text()
    assert "deliver_telegram: bool = True" in notification_source
    assert "deliver_telegram=False" in router_source
    assert 'AuditLog.after_data["task_id"].as_integer() == task_id' in router_source
    assert 'AuditLog.after_data["parent_task_id"].as_integer() == task_id' in router_source
