"""Validate generated dual-bridge configuration dictionaries."""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_NODE_KEYS = ("A", "B")
_ROOT_REQUIRED = (
    "round_timeout",
    "codex_timeout",
    "max_rounds",
    "poll_interval",
    "poller_interval",
    "nodes",
    "endpoints",
)

CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": list(_ROOT_REQUIRED),
    "properties": {
        "nodes": {
            "type": "object",
            "required": list(_NODE_KEYS),
            "properties": {
                node: {
                    "type": "object",
                    "required": ["model"],
                    "properties": {"model": {"type": "string"}},
                }
                for node in _NODE_KEYS
            },
        },
        "endpoints": {
            "type": "object",
            "required": list(_NODE_KEYS),
            "properties": {
                node: {
                    "type": "object",
                    "required": ["command"],
                    "properties": {"command": {"type": "string"}},
                }
                for node in _NODE_KEYS
            },
        },
    },
}


def validate_config(config_dict: dict) -> bool:
    """Validate required config shape, CLI availability, and optional dry-run."""
    if not isinstance(config_dict, dict):
        raise ValueError("config must be a dict")

    _validate_schema(config_dict, CONFIG_SCHEMA)
    resolved_commands = _validate_cli_commands(config_dict)

    if config_dict.get("dry_run"):
        _run_cli_dry_runs(resolved_commands)

    return True


def _validate_schema(value: Any, schema: dict[str, Any], path: str = "config") -> None:
    expected_type = schema.get("type")
    if expected_type == "object" and not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    if expected_type == "string":
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{path} must be a non-empty string")
        return

    if not isinstance(value, dict):
        return

    for key in schema.get("required", []):
        if key not in value:
            raise ValueError(f"missing required config field: {_join_path(path, key)}")

    properties = schema.get("properties", {})
    for key, child_schema in properties.items():
        if key in value:
            _validate_schema(value[key], child_schema, _join_path(path, key))


def _validate_cli_commands(config: dict) -> dict[str, str]:
    resolved: dict[str, str] = {}
    endpoints = config["endpoints"]
    for node in _NODE_KEYS:
        path = f"endpoints.{node}.command"
        command = endpoints[node]["command"].strip()
        resolved_command = _resolve_command(command)
        if not resolved_command:
            raise ValueError(f"{path} not found: {command!r}")
        resolved[path] = resolved_command
    return resolved


def _resolve_command(command: str) -> str | None:
    if os.path.exists(command):
        return command
    return shutil.which(command)


def _run_cli_dry_runs(commands: dict[str, str]) -> None:
    for field, command in commands.items():
        try:
            result = subprocess.run(
                [command, "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                creationflags=_NO_WINDOW,
            )
        except OSError as exc:
            raise ValueError(f"dry-run failed for {field}: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"dry-run failed for {field}: timed out") from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            suffix = f": {detail}" if detail else ""
            raise ValueError(
                f"dry-run failed for {field}: exit {result.returncode}{suffix}"
            )


def _join_path(parent: str, child: str) -> str:
    return child if parent == "config" else f"{parent}.{child}"
