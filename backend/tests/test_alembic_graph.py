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
    assert heads == ["w2x3y4z5a6b7"]
    assert script.get_revision(heads[0]).down_revision == "u2v3w4x5y6z7"
    assert script.get_revision("u2v3w4x5y6z7").down_revision == "s0t1u2v3w4x5"
