from app.core.config import Settings


def test_desktop_control_canary_allowlist_defaults_empty(monkeypatch):
    monkeypatch.delenv("DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", raising=False)

    settings = Settings(_env_file=None)

    assert settings.DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST == []


def test_desktop_control_canary_allowlist_accepts_empty_string(monkeypatch):
    monkeypatch.setenv("DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", "")

    settings = Settings(_env_file=None)

    assert settings.DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST == []


def test_desktop_control_canary_allowlist_accepts_comma_separated_env(monkeypatch):
    monkeypatch.setenv(
        "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST",
        "com.example.Target, com.example.Other ,,",
    )

    settings = Settings(_env_file=None)

    assert settings.DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST == [
        "com.example.Target",
        "com.example.Other",
    ]


def test_desktop_control_canary_allowlist_accepts_json_array_env(monkeypatch):
    monkeypatch.setenv(
        "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST",
        '["com.example.Target", "com.example.Other"]',
    )

    settings = Settings(_env_file=None)

    assert settings.DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST == [
        "com.example.Target",
        "com.example.Other",
    ]
