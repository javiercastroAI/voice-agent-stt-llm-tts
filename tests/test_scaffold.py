from pathlib import Path


def test_level_five_scaffold_exists() -> None:
    root = Path(__file__).resolve().parent.parent
    assert (root / "agentic-repo.toml").exists()
    assert (root / "specs" / "governance" / "controls.json").exists()
    assert (root / "shared" / "generated" / "interface_contract.py").exists()
