from backend import settings_manager


def test_avatar_visibility_defaults_to_true():
    settings = settings_manager.load_settings()
    assert settings["show_avatar"] is True


def test_avatar_visibility_can_be_disabled():
    saved = settings_manager.save_settings({"show_avatar": False})
    assert saved["show_avatar"] is False

    reloaded = settings_manager.load_settings()
    assert reloaded["show_avatar"] is False

    # Restore the default so later tests remain stable.
    settings_manager.save_settings({"show_avatar": True})
