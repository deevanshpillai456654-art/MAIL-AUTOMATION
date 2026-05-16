"""
Config Manager - Dynamic Configuration
=================================

Dynamic configuration management:
- Environment-based config
- Hot reload
- Validation
- Secrets management
- Config versioning
"""

import os
import json
import time
import threading
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger("config.manager")


class ConfigSource(Enum):
    ENV = "env"
    FILE = "file"
    DEFAULT = "default"
    SECRET = "secret"


@dataclass
class ConfigEntry:
    """Configuration entry"""
    key: str
    value: Any
    source: ConfigSource
    updated_at: float = field(default_factory=time.time)
    version: int = 1


class ConfigManager:
    """
    Dynamic configuration manager.
    """
    
    def __init__(self, config_dir: str = None):
        self.config_dir = config_dir or os.path.join(os.getcwd(), "configs")
        self._config: Dict[str, ConfigEntry] = {}
        self._lock = threading.RLock()
        
        # Callbacks
        self._change_callbacks: Dict[str, list] = {}
        
        # Load defaults
        self._load_defaults()
        
        logger.info("ConfigManager initialized")
    
    def _load_defaults(self):
        """Load default configurations"""
        defaults = {
            "api.host": ("127.0.0.1", ConfigSource.DEFAULT),
            "api.port": (4597, ConfigSource.DEFAULT),
            "api.cors.enabled": (True, ConfigSource.DEFAULT),
            "cache.enabled": (True, ConfigSource.DEFAULT),
            "cache.ttl": (3600, ConfigSource.DEFAULT),
            "session.ttl": (86400, ConfigSource.DEFAULT),
            "rate.limit.enabled": (True, ConfigSource.DEFAULT),
            "rate.limit.requests": (60, ConfigSource.DEFAULT),
        }
        
        for key, (value, source) in defaults.items():
            self._config[key] = ConfigEntry(
                key=key,
                value=value,
                source=source
            )
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        with self._lock:
            entry = self._config.get(key)
            return entry.value if entry else default
    
    def set(self, key: str, value: Any, source: ConfigSource = ConfigSource.DEFAULT):
        """Set configuration value"""
        with self._lock:
            old_entry = self._config.get(key)
            old_value = old_entry.value if old_entry else None
            
            self._config[key] = ConfigEntry(
                key=key,
                value=value,
                source=source
            )
            
            # Trigger callbacks
            if old_value != value and key in self._change_callbacks:
                for callback in self._change_callbacks[key]:
                    try:
                        callback(key, old_value, value)
                    except Exception as e:
                        logger.error(f"Config change callback error: {e}")
    
    def on_change(self, key: str, callback):
        """Register change callback"""
        if key not in self._change_callbacks:
            self._change_callbacks[key] = []
        self._change_callbacks[key].append(callback)
    
    def get_all(self, prefix: str = None) -> Dict[str, Any]:
        """Get all configurations"""
        with self._lock:
            if prefix:
                return {
                    k: v.value for k, v in self._config.items()
                    if k.startswith(prefix)
                }
            return {k: v.value for k, v in self._config.items()}
    
    def reload(self):
        """Reload configuration from environment"""
        with self._lock:
            # Load from environment
            for key, value in os.environ.items():
                if key.startswith("API_"):
                    config_key = key.lower().replace("_", ".")
                    self.set(config_key, value, ConfigSource.ENV)
            
            logger.info("Configuration reloaded")
    
    def validate(self) -> Dict[str, List[str]]:
        """Validate configuration"""
        issues = {}
        
        # Required keys
        required = ["api.host", "api.port"]
        for key in required:
            if key not in self._config:
                issues.setdefault("missing", []).append(key)
        
        # Type validation
        port = self.get("api.port")
        if port and not isinstance(port, int):
            issues.setdefault("type", []).append("api.port must be integer")
        
        return issues


# Global config manager
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Get global config manager"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


__all__ = ["ConfigManager", "ConfigEntry", "ConfigSource", "get_config_manager"]