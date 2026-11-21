"""Scrapewatch settings and configuration.

Provides centralized configuration for all scrapewatch components.
Settings are immutable (frozen dataclasses) and accessed via get_settings().

Configuration sources (in order of priority):
1. scrapewatch.configure() calls in code
2. Environment variables (SCRPAPEWATCH_*)
3. scrapewatch.toml config file
"""

from dataclasses import dataclass
from pathlib import Path
import os

__all__ = [
    "AnalyzerSettings",
    "StorageSettings",
    "Settings",
    "get_settings",
    "configure",
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


# Global settings instance (singleton)
_default_settings: Settings | None = None


def _load_toml_config() -> dict:
    """Load scrapewatch.toml if it exists in current directory or parents."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    
    cwd = Path.cwd()
    for path in [cwd, *cwd.parents]:
        config_file = path / "scrapewatch.toml"
        if config_file.is_file():
            try:
                with open(config_file, "rb") as f:
                    data = tomllib.load(f)
                    return data.get("scrapewatch", {})
            except Exception:
                pass
    
    return {}


def _load_env_config() -> dict:
    """Load configuration from environment variables."""
    config = {}
    
    env_mappings = {
        "SCRPAPEWATCH_RULES_DIR": "rules_dir",
        "SCRPAPEWATCH_DB_PATH": "db_path",
        "SCRPAPEWATCH_QUEUE_LIMIT": "queue_limit",
        "SCRPAPEWATCH_SHUTDOWN_TIMEOUT": "shutdown_timeout",
        "SCRPAPEWATCH_BODY_SIZE_CAP": "body_size_cap",
        "SCRPAPEWATCH_BATCH_SIZE": "batch_size",
        "SCRPAPEWATCH_FLUSH_INTERVAL": "flush_interval",
        "SCRPAPEWATCH_BODY_SAMPLE_LIMIT": "body_sample_limit",
    }
    
    for env_key, config_key in env_mappings.items():
        value = os.environ.get(env_key)
        if value is not None:
            if config_key in ("queue_limit", "body_size_cap", "batch_size", "body_sample_limit"):
                value = int(value)
            elif config_key in ("shutdown_timeout", "flush_interval"):
                value = float(value)
            config[config_key] = value
    
    return config


def get_settings() -> Settings:
    """Get or create global settings.
    
    Settings are loaded from (lowest to highest priority):
    1. Default values
    2. scrapewatch.toml config file
    3. Environment variables
    4. configure() calls
    """
    global _default_settings
    if _default_settings is None:
        # Load from toml and env
        toml_config = _load_toml_config()
        env_config = _load_env_config()
        
        # Merge: env > toml
        merged = {**toml_config, **env_config}
        
        _default_settings = Settings(
            analyzer=AnalyzerSettings(
                queue_limit=merged.get("queue_limit", 10_000),
                shutdown_timeout=merged.get("shutdown_timeout", 10.0),
                body_size_cap=merged.get("body_size_cap", 10 * 1024 * 1024),
            ),
            storage=StorageSettings(
                db_path=merged.get("db_path", "scrapewatch.db"),
                batch_size=merged.get("batch_size", 50),
                flush_interval=merged.get("flush_interval", 10.0),
            ),
            body_sample_limit=merged.get("body_sample_limit", 64 * 1024),
            rules_dir=merged.get("rules_dir"),
        )
    return _default_settings


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
    """Configure scrapewatch settings globally.
    
    Args:
        queue_limit: Max events in AsyncAnalyzer queue (default: 10_000)
        shutdown_timeout: Seconds to wait for graceful shutdown (default: 10.0)
        body_size_cap: Max body size to process in bytes (default: 10MB)
        db_path: Path to SQLite database (default: "scrapewatch.db")
        batch_size: Number of events to batch before flush (default: 50)
        flush_interval: Seconds between automatic flushes (default: 10.0)
        body_sample_limit: Max body sample size to store in bytes (default: 64KB)
        rules_dir: Default directory to load .yaml rule files from (default: None)
    
    Example:
        >>> import scrapewatch as sw
        >>> sw.configure(rules_dir="rules/", queue_limit=5_000)
    """
    global _default_settings
    
    current = get_settings()
    
    analyzer = AnalyzerSettings(
        queue_limit=queue_limit if queue_limit is not None else current.analyzer.queue_limit,
        shutdown_timeout=shutdown_timeout if shutdown_timeout is not None else current.analyzer.shutdown_timeout,
        body_size_cap=body_size_cap if body_size_cap is not None else current.analyzer.body_size_cap,
    )
    
    storage = StorageSettings(
        db_path=db_path if db_path is not None else current.storage.db_path,
        batch_size=batch_size if batch_size is not None else current.storage.batch_size,
        flush_interval=flush_interval if flush_interval is not None else current.storage.flush_interval,
    )
    
    _default_settings = Settings(
        analyzer=analyzer,
        storage=storage,
        body_sample_limit=body_sample_limit if body_sample_limit is not None else current.body_sample_limit,
        rules_dir=rules_dir if rules_dir is not None else current.rules_dir,
    )
