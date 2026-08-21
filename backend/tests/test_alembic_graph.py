from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_has_one_deployable_head():
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["r7s8t9u0v1w2"]
