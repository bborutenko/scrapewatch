"""Scrapewatch settings and configuration.

Provides centralized configuration for all scrapewatch components.
Settings are immutable (frozen dataclasses) and accessed via get_settings().

Usage:
    import scrapewatch as sw

    # Configure at startup
    sw.configure(
        db_path="data/scrapewatch.db",
        rules_dir="rules/",
    )

    # Get settings anywhere
    settings = sw.get_settings()
"""

from dataclasses import dataclass

__all__ = [
    "AnalyzerSettings",
    "StorageSettings",
    "Settings",
    "get_settings",
    "configure",
    "reset_settings",  # for tests
]


@dataclass(frozen=True, slots=True)
class AnalyzerSettings:
    """Settings for AsyncAnalyzer."""
    queue_limit: int = 10_000
    shutdown_timeout: float = 10.0
    body_size_cap: int = 10 * 1024 * 1024  # 10MB


@dataclass(frozen=True, slots=True)
class StorageSettings:
    """Settings for Storage."""
    db_path: str = "scrapewatch.db"
    batch_size: int = 50
    flush_interval: float = 10.0


@dataclass(frozen=True, slots=True)
class Settings:
    """Global scrapewatch settings."""
    analyzer: AnalyzerSettings
    storage: StorageSettings
    body_sample_limit: int = 64 * 1024  # 64KB
    rules_dir: str | None = None


# Default settings (used when configure() was never called)
_DEFAULTS = Settings(
    analyzer=AnalyzerSettings(),
    storage=StorageSettings(),
)


# Global settings instance (singleton)
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get current settings.
    
    Returns configured settings if configure() was called,
    otherwise returns defaults.
    """
    global _settings
    return _settings if _settings is not None else _DEFAULTS


def configure(
    queue_limit: int | None = None,
    shutdown_timeout: float | None = None,
    body_size_cap: int | None = None,
    db_path: str | None = None,
    batch_size: int | None = None,
    flush_interval: float | None = None,
    body_sample_limit: int | None = None,
    rules_dir: str | None = None,
) -> None:
    """Configure scrapewatch settings.
    
    Call once at application startup before creating any scrapewatch clients.
    Any parameter not provided keeps its current value (or default).
    
    Args:
        queue_limit: Max events in AsyncAnalyzer queue (default: 10_000)
        shutdown_timeout: Seconds to wait for graceful shutdown (default: 10.0)
        body_size_cap: Max body size to process in bytes (default: 10MB)
        db_path: Path to SQLite database (default: "scrapewatch.db")
        batch_size: Number of events to batch before flush (default: 50)
        flush_interval: Seconds between automatic flushes (default: 10.0)
        body_sample_limit: Max body sample size to store in bytes (default: 64KB)
        rules_dir: Directory to load .yaml rule files from (default: None)
    
    Example:
        >>> import scrapewatch as sw
        >>> sw.configure(
        ...     rules_dir="rules/",
        ...     db_path="data/scrapewatch.db",
        ...     queue_limit=5_000,
        ... )
    """
    global _settings
    
    current = get_settings()
    
    _settings = Settings(
        analyzer=AnalyzerSettings(
            queue_limit=queue_limit if queue_limit is not None else current.analyzer.queue_limit,
            shutdown_timeout=shutdown_timeout if shutdown_timeout is not None else current.analyzer.shutdown_timeout,
            body_size_cap=body_size_cap if body_size_cap is not None else current.analyzer.body_size_cap,
        ),
        storage=StorageSettings(
            db_path=db_path if db_path is not None else current.storage.db_path,
            batch_size=batch_size if batch_size is not None else current.storage.batch_size,
            flush_interval=flush_interval if flush_interval is not None else current.storage.flush_interval,
        ),
        body_sample_limit=body_sample_limit if body_sample_limit is not None else current.body_sample_limit,
        rules_dir=rules_dir if rules_dir is not None else current.rules_dir,
    )


def reset_settings() -> None:
    """Reset settings to defaults.
    
    Only used in tests to ensure isolation between test cases.
    """
    global _settings
    _settings = None
