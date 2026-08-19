from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Parameters injected by Cylinder — never represent user-defined API parameters
CYLINDER_PARAMS: frozenset[str] = frozenset({"request", "response", "logger", "abort", "e"})


@dataclass
class RouteInfo:
    path: str
    method: str  # uppercase HTTP method, e.g. "GET", or "DEFAULT" for catch-alls
    handler_file: Path
    module_name: str
    function: Optional[Callable] = None
    metadata: dict = field(default_factory=dict)
