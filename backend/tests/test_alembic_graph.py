from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_has_one_deployable_head():
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    script = ScriptDirectory.from_config(config)

    heads = script.get_heads()
    assert len(heads) == 1
    assert heads == ["p1q2r3s4t5u6"]
    assert set(script.get_revision(heads[0]).down_revision) == {
        "b2c3d4e5f6g7",
        "m6n7o8p9q0r1",
    }
