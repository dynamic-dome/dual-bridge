"""Generate a complete bridge config from scout and wizard results."""
from __future__ import annotations

import copy
import json

from . import bridge_common

_NODE_KEYS = ("A", "B")
_SUPPORTED_MODELS = ("claude", "codex")


def generate_config(scout_result: dict, wizard_result: dict) -> dict:
    """Return a config dict with node models and endpoint commands filled in.

    The existing ``config.json`` is treated as the template. The returned dict is
    not written to disk.
    """
    config = copy.deepcopy(bridge_common.bridge_config(use_cache=False))
    if not isinstance(config, dict):
        config = {}

    mapping = _wizard_mapping(wizard_result)
    nodes = _dict_section(config, "nodes")
    endpoints = _dict_section(config, "endpoints")

    for node in _NODE_KEYS:
        model = mapping[node]
        node_cfg = _dict_section(nodes, node)
        endpoint_cfg = _dict_section(endpoints, node)

        node_cfg["model"] = model
        endpoint_cfg["command"] = _command_for_model(scout_result, model)

    _validate_required(config)
    return config


def _wizard_mapping(wizard_result: dict) -> dict[str, str]:
    if not isinstance(wizard_result, dict):
        raise ValueError("wizard_result must be a dict")

    raw = {
        "A": wizard_result.get("node_a"),
        "B": wizard_result.get("node_b"),
    }

    nested = wizard_result.get("nodes")
    if isinstance(nested, dict):
        for node in _NODE_KEYS:
            entry = nested.get(node)
            if isinstance(entry, dict):
                raw[node] = entry.get("model", raw[node])
            elif isinstance(entry, str):
                raw[node] = entry

    mapping: dict[str, str] = {}
    for node, model in raw.items():
        if not isinstance(model, str) or not model.strip():
            raise ValueError(f"wizard_result is missing node {node} model")
        normalized = model.strip().lower()
        if normalized not in _SUPPORTED_MODELS:
            raise ValueError(f"unsupported model for node {node}: {model!r}")
        mapping[node] = normalized
    return mapping


def _command_for_model(scout_result: dict, model: str) -> str:
    if not isinstance(scout_result, dict):
        raise ValueError("scout_result must be a dict")

    command = scout_result.get(model) or model
    if not isinstance(command, str) or not command.strip():
        raise ValueError(f"missing command for model {model!r}")
    return command.strip()


def _dict_section(parent: dict, key: str) -> dict:
    value = parent.setdefault(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"config section {key!r} must be a dict")
    return value


def _validate_required(config: dict) -> None:
    missing = []
    for node in _NODE_KEYS:
        if not config.get("nodes", {}).get(node, {}).get("model"):
            missing.append(f"nodes.{node}.model")
        if not config.get("endpoints", {}).get(node, {}).get("command"):
            missing.append(f"endpoints.{node}.command")

    if missing:
        raise ValueError("missing required config fields: " + ", ".join(missing))

    try:
        json.dumps(config)
    except (TypeError, ValueError) as exc:
        raise ValueError("generated config is not JSON-serializable") from exc
