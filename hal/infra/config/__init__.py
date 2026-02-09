"""Configuration module for HaL."""

from hal.infra.config.loader import load_config, get_config_path
from hal.infra.config.schema import Config

__all__ = ["Config", "load_config", "get_config_path"]
