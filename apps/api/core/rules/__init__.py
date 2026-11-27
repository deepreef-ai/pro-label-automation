"""Pure, deterministic business rules replacing the client's Excel v12 formulas.

No DB, no I/O. Every public function cites the SPEC section 2 rule it implements.
"""
from .errors import RuleError
from .settings import DEFAULTS, Defaults

__all__ = ["RuleError", "Defaults", "DEFAULTS"]
