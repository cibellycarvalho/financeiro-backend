import importlib


def test_config_leitura_tem_defaults(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LEITURA_MODEL", raising=False)
    import config
    importlib.reload(config)
    assert config.ANTHROPIC_API_KEY == ""
    assert config.LEITURA_MODEL == "claude-opus-5"


def test_config_leitura_le_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-teste")
    monkeypatch.setenv("LEITURA_MODEL", "claude-sonnet-5")
    import config
    importlib.reload(config)
    assert config.ANTHROPIC_API_KEY == "sk-teste"
    assert config.LEITURA_MODEL == "claude-sonnet-5"
