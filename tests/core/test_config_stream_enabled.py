from svgmaker_proxy.core.config import Settings


def test_stream_enabled_defaults_to_true() -> None:
    settings = Settings(_env_file=None)
    assert settings.stream_enabled is True


def test_stream_enabled_reads_env_value_false() -> None:
    settings = Settings(SVGM_STREAM_ENABLED=False, _env_file=None)
    assert settings.stream_enabled is False
