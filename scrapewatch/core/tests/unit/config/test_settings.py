"""Settings module tests: defaults, configure, get_settings."""

import pytest

from scrapewatch.config import configure, get_settings, reset_settings


@pytest.fixture(autouse=True)
def clean_settings():
    """Reset settings before and after each test."""
    reset_settings()
    yield
    reset_settings()


class TestDefaults:
    """Default values when configure() was never called."""

    def test_get_settings_returns_defaults(self):
        """get_settings() returns defaults without configure()."""
        settings = get_settings()

        assert settings.analyzer.queue_limit == 10_000
        assert settings.analyzer.shutdown_timeout == 10.0
        assert settings.analyzer.body_size_cap == 10 * 1024 * 1024
        assert settings.storage.db_path == "scrapewatch.db"
        assert settings.storage.batch_size == 50
        assert settings.storage.flush_interval == 10.0
        assert settings.body_sample_limit == 64 * 1024
        assert settings.rules_dir is None

    def test_defaults_are_immutable(self):
        """Settings objects are frozen."""
        settings = get_settings()

        with pytest.raises(Exception):  # FrozenInstanceError
            settings.storage.db_path = "other.db"


class TestConfigure:
    """configure() sets settings."""

    def test_configure_sets_single_value(self):
        """configure() can set a single value."""
        configure(db_path="custom.db")

        settings = get_settings()
        assert settings.storage.db_path == "custom.db"
        # Others remain defaults
        assert settings.storage.batch_size == 50

    def test_configure_sets_multiple_values(self):
        """configure() can set multiple values."""
        configure(
            db_path="data/watch.db",
            rules_dir="rules/",
            queue_limit=5_000,
            batch_size=100,
        )

        settings = get_settings()
        assert settings.storage.db_path == "data/watch.db"
        assert settings.rules_dir == "rules/"
        assert settings.analyzer.queue_limit == 5_000
        assert settings.storage.batch_size == 100

    def test_configure_preserves_previous_values(self):
        """Second configure() preserves values not specified."""
        configure(db_path="first.db", queue_limit=1_000)
        configure(rules_dir="rules/")  # Only set rules_dir

        settings = get_settings()
        assert settings.storage.db_path == "first.db"  # Preserved
        assert settings.analyzer.queue_limit == 1_000  # Preserved
        assert settings.rules_dir == "rules/"  # New value

    def test_configure_can_override_values(self):
        """configure() can override previous values."""
        configure(db_path="first.db")
        configure(db_path="second.db")

        settings = get_settings()
        assert settings.storage.db_path == "second.db"


class TestResetSettings:
    """reset_settings() restores defaults."""

    def test_reset_restores_defaults(self):
        """reset_settings() restores all defaults."""
        configure(db_path="custom.db", queue_limit=999)
        reset_settings()

        settings = get_settings()
        assert settings.storage.db_path == "scrapewatch.db"
        assert settings.analyzer.queue_limit == 10_000

    def test_reset_allows_reconfigure(self):
        """Can configure again after reset."""
        configure(db_path="first.db")
        reset_settings()
        configure(db_path="second.db")

        settings = get_settings()
        assert settings.storage.db_path == "second.db"


class TestSettingsImmutable:
    """Settings objects are immutable."""

    def test_analyzer_settings_immutable(self):
        """AnalyzerSettings is frozen."""
        settings = get_settings()

        with pytest.raises(Exception):
            settings.analyzer.queue_limit = 999  # type: ignore

    def test_storage_settings_immutable(self):
        """StorageSettings is frozen."""
        settings = get_settings()

        with pytest.raises(Exception):
            settings.storage.db_path = "other.db"  # type: ignore

    def test_settings_immutable(self):
        """Settings is frozen."""
        settings = get_settings()

        with pytest.raises(Exception):
            settings.rules_dir = "rules/"  # type: ignore
