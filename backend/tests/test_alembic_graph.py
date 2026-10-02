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
    assert heads == ["6c8a2e4f0d37"]
    assert script.get_revision("6c8a2e4f0d37").down_revision == "5b7f1d3e9c26"
    assert script.get_revision("5b7f1d3e9c26").down_revision == "4a6e0c2d8b15"
    assert script.get_revision("4a6e0c2d8b15").down_revision == "a9b8c7d6e5f4"
    assert script.get_revision("a9b8c7d6e5f4").down_revision == "e1f2a3b4c5d6"
    assert script.get_revision("e1f2a3b4c5d6").down_revision == "d4e8f1a2b3c9"
    assert script.get_revision("d4e8f1a2b3c9").down_revision == "b3c4d5e6f7a8"
    assert script.get_revision("e5f6a7b8c9d0").down_revision == "d1e2f3a4b5c6"
    # The allowance-payout migration alters monthly_payroll_profiles, so it must
    # descend from the merge that includes the monthly payroll foundation.
    assert script.get_revision("a7b8c9d0e1f3").down_revision == "p1q2r3s4t5u6"
    assert set(script.get_revision("p1q2r3s4t5u6").down_revision) == {
        "b2c3d4e5f6g7",
        "m6n7o8p9q0r1",
    }
