from pathlib import Path


README = Path("README.md").read_text()


def test_readme_documents_replacement_workflows_with_uv() -> None:
    assert "uv run network-scripts serial watch" in README
    assert "uv run network-scripts cisco dump" in README
    assert "uv run network-scripts cisco dump --no-enable" in README
    assert "uv run network-scripts cisco explain INPUT" in README


def test_readme_documents_diagnostic_dump_and_feature_parity_gate() -> None:
    assert "Diagnostic Dump" in README
    assert "show running-config" in README
    assert "Feature parity gate" in README
    assert "scripts/" in README


def test_legacy_scripts_directory_has_been_removed_after_feature_parity() -> None:
    assert not Path("scripts").exists()
    assert "The legacy `scripts/` directory has been removed" in README
    assert "stays until" not in README
