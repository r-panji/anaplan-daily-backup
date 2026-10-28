import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

try:
    from backup import ArchiveNameError, backup_name
except ModuleNotFoundError:  # Package import used by the test suite.
    from .backup import ArchiveNameError, backup_name


class ConfigError(ValueError):
    pass


def _integer(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be an integer from {minimum} to {maximum}.")


def validate_config(cfg):
    if not isinstance(cfg, dict):
        raise ConfigError("The configuration root must be a YAML mapping.")
    timezone = cfg.get("timezone", "Asia/Jakarta")
    if not isinstance(timezone, str):
        raise ConfigError("timezone must be a string.")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        raise ConfigError(f"Unknown timezone: {timezone!r}.") from None

    schedule = cfg.get("schedule", {})
    if not isinstance(schedule, dict):
        raise ConfigError("schedule must be a YAML mapping.")
    _integer(schedule.get("hour", 1), "schedule.hour", 0, 23)
    _integer(schedule.get("minute", 0), "schedule.minute", 0, 59)

    backup = cfg.get("backup")
    if not isinstance(backup, dict):
        raise ConfigError("backup must be a YAML mapping.")
    models = backup.get("models")
    if not isinstance(models, list) or not models:
        raise ConfigError("backup.models must contain at least one model.")
    suffix = backup.get("suffix_format", "_[BACKUP]_%Y%m%d_%H%M%S")
    if not isinstance(suffix, str) or not suffix:
        raise ConfigError("backup.suffix_format must be a non-empty string.")
    try:
        backup_name("Model", suffix, datetime(2000, 1, 2, 3, 4, 5))
    except ArchiveNameError as exc:
        raise ConfigError(f"Invalid backup.suffix_format: {exc}") from None

    seen = set()
    id_pattern = re.compile(r"^[A-Fa-f0-9]{32}$")
    for index, model in enumerate(models, 1):
        prefix = f"backup.models[{index}]"
        if not isinstance(model, dict):
            raise ConfigError(f"{prefix} must be a YAML mapping.")
        workspace = model.get("workspace_name", model.get("workspace", ""))
        name = model.get("model_name", model.get("model", ""))
        if not isinstance(workspace, str) or not workspace.strip():
            raise ConfigError(f"{prefix}.workspace_name must not be empty.")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{prefix}.model_name must not be empty.")
        tags = model.get("tags", [])
        if not isinstance(tags, list):
            raise ConfigError(f"{prefix}.tags must be a YAML list of strings.")
        normalized_tags = set()
        for tag_index, tag in enumerate(tags, 1):
            if not isinstance(tag, str) or not tag.strip():
                raise ConfigError(f"{prefix}.tags[{tag_index}] must be a non-empty string.")
            normalized = tag.strip().casefold()
            if normalized in normalized_tags:
                raise ConfigError(f"{prefix}.tags contains duplicate tag {tag.strip()!r}.")
            normalized_tags.add(normalized)
        for field in ("workspace_id", "model_id"):
            value = model.get(field, "") or ""
            if not isinstance(value, str):
                raise ConfigError(f"{prefix}.{field} must be a string.")
            if value and not id_pattern.fullmatch(value):
                raise ConfigError(f"{prefix}.{field} must be a 32-character hexadecimal Anaplan ID.")
        if model.get("enabled") is True:
            key = ((model.get("workspace_id") or workspace).lower(),
                   (model.get("model_id") or name).lower())
            if key in seen:
                raise ConfigError(f"{prefix} duplicates another enabled workspace/model target.")
            seen.add(key)
    return cfg


def load_config(path: str | Path) -> dict:
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            cfg = yaml.safe_load(handle)
    except FileNotFoundError:
        raise ConfigError(f"Configuration file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from None
    return validate_config(cfg)
