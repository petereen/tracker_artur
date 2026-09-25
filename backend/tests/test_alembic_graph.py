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
    assert heads == ["b9c0d1e2f3a4"]
    # The allowance-payout migration alters monthly_payroll_profiles, so it must
    # descend from the merge that includes the monthly payroll foundation.
    assert script.get_revision("a7b8c9d0e1f3").down_revision == "p1q2r3s4t5u6"
    assert set(script.get_revision("p1q2r3s4t5u6").down_revision) == {
        "b2c3d4e5f6g7",
        "m6n7o8p9q0r1",
    }
