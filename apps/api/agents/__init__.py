"""PO reader, AI agents and outbox (owner: Ravi).

Importing the package imports every agent module so ``agents.base.REGISTRY`` is full.
A module file that does not exist yet is skipped with a warning (its agent shows as not
installed); any other import error is raised.
"""
from __future__ import annotations

import importlib
import logging

from agents.base import AGENT_NAMES

log = logging.getLogger(__name__)

MISSING: list[str] = []

for _name in AGENT_NAMES:
    _module = f"agents.{_name}"
    try:
        importlib.import_module(_module)
    except ModuleNotFoundError as _exc:
        if _exc.name != _module:  # a real import error inside an existing module
            raise
        MISSING.append(_name)
        log.warning("agent module %s is missing; agent %s is not available", _module, _name)
