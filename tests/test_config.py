from config import Settings


def test_from_env_falls_back_to_project_env_when_launched_elsewhere(
    tmp_path,
    monkeypatch,
) -> None:
    project_env = tmp_path / ".env"
    project_env.write_text("OPENSEARCH_OUTPUT_DIR=mac-output\n", encoding="utf-8")

    fake_config = tmp_path / "src" / "config.py"
    fake_config.parent.mkdir()
    monkeypatch.setattr("config.__file__", str(fake_config))
    monkeypatch.chdir(tmp_path / "src")

    settings = Settings.from_env(tmp_path / "missing.env")

    assert settings.output_dir.name == "mac-output"
