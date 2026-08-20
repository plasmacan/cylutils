from __future__ import annotations

import importlib.util
import inspect
import re
import typing
import warnings
from pathlib import Path
from typing import Callable, Optional

from .models import CYLINDER_PARAMS, RouteInfo

_INFER_DESCRIPTION_LINE_COUNT = 2  # lines after summary to include in description
_EX_RE = re.compile(r"^(.+)\.ex\.([a-zA-Z]+)\.py$")

_JSON_TYPE_MAP: dict[type, str] = {
    int: "integer",
    float: "number",
    str: "string",
    bool: "boolean",
    list: "array",
    dict: "object",
    bytes: "string",
}


def scan_app(app_path: str | Path) -> list[RouteInfo]:
    """Scan a Cylinder app directory and return discovered executable routes.

    Includes sibling root-handler files (e.g. ``webapp1.ex.get.py`` next to
    the ``webapp1/`` directory) as well as all ``.ex.<method>.py`` files
    found recursively inside the directory.  Hooks, error handlers, and
    non-handler files are ignored.
    """
    app_path = Path(app_path).resolve()
    routes: list[RouteInfo] = []

    # Sibling root handlers: {parent}/{dirname}.ex.{method}.py → path "/"
    for sibling in sorted(app_path.parent.glob(f"{app_path.name}.ex.*.py")):
        m = _EX_RE.match(sibling.name)
        if m:
            method = m.group(2).upper()
            route = RouteInfo(
                path="/",
                method=method,
                handler_file=sibling,
                module_name=sibling.stem,
            )
            routes.append(_load_and_inspect(route))

    # All .ex.{method}.py files inside the app directory
    for file in sorted(app_path.rglob("*.py")):
        if "__pycache__" in file.parts:
            continue
        m = _EX_RE.match(file.name)
        if not m:
            continue

        segment = m.group(1)
        method = m.group(2).upper()

        rel = file.relative_to(app_path)
        dir_parts = list(rel.parts[:-1])
        path_parts = dir_parts + [segment]
        route_path = "/" + "/".join(path_parts)
        module_name = ".".join(dir_parts + [file.stem])

        route = RouteInfo(
            path=route_path,
            method=method,
            handler_file=file,
            module_name=module_name,
        )
        routes.append(_load_and_inspect(route))

    return routes


def _load_and_inspect(route: RouteInfo) -> RouteInfo:
    """Import a handler module and populate ``route.function``, ``route.schemas``, and ``route.metadata``."""
    module = _load_module(route)
    route.function = getattr(module, "main", None) if module else None
    route.schemas = _extract_dataclass_schemas(module) if module else {}

    inferred: dict = {}
    if route.function is not None:
        params = _infer_parameters(route.function)
        if params:
            inferred["parameters"] = params
        docstring = inspect.getdoc(route.function)
        if docstring:
            lines = docstring.splitlines()
            inferred["summary"] = lines[0]
            if len(lines) > _INFER_DESCRIPTION_LINE_COUNT:
                inferred["description"] = "\n".join(lines[1 : _INFER_DESCRIPTION_LINE_COUNT + 1]).strip()

    sidecar = _load_sidecar(route.handler_file)
    # sidecar keys override inferred keys
    route.metadata = {**inferred, **sidecar}
    return route


def _load_module(route: RouteInfo):
    """Import a handler file and return the module object, or ``None`` on failure."""
    spec = importlib.util.spec_from_file_location(route.module_name, route.handler_file)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        warnings.warn(f"Could not import {route.handler_file}: {exc}", stacklevel=2)
        return None
    return module


def _load_handler(route: RouteInfo) -> Optional[Callable]:
    """Import a handler file and return its ``main()`` function, or ``None`` on failure."""
    module = _load_module(route)
    return getattr(module, "main", None) if module else None


def _extract_dataclass_schemas(module) -> dict[str, dict]:
    """Return ``{ClassName: openapi_schema}`` for every dataclass defined in module."""
    import dataclasses as _dc

    schemas: dict[str, dict] = {}
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if _dc.is_dataclass(obj) and getattr(obj, "__module__", None) == module.__name__:
            schemas[name] = _dataclass_to_openapi_schema(obj)
    return schemas


def _hint_to_openapi(hint) -> dict:
    """Convert a Python type hint to an OpenAPI schema dict."""
    if hint is None:
        return {}

    origin = getattr(hint, "__origin__", None)
    args = getattr(hint, "__args__", ()) or ()

    if origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            schema = dict(_hint_to_openapi(non_none[0]))
            schema["nullable"] = True
            return schema
        return {}

    if origin is list:
        if args:
            return {"type": "array", "items": _hint_to_openapi(args[0])}
        return {"type": "array"}

    if origin is dict:
        return {"type": "object"}

    _HINT_MAP: dict = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
        list: {"type": "array"},
        dict: {"type": "object"},
        bytes: {"type": "string", "format": "binary"},
    }
    return dict(_HINT_MAP.get(hint, {}))


def _dataclass_to_openapi_schema(cls) -> dict:
    """Convert a dataclass to an OpenAPI 3.0 object schema."""
    import dataclasses as _dc

    try:
        hints = typing.get_type_hints(cls)
    except Exception:
        hints = {}

    properties: dict = {}
    required: list[str] = []

    for f in _dc.fields(cls):
        properties[f.name] = _hint_to_openapi(hints.get(f.name))
        if f.default is _dc.MISSING and f.default_factory is _dc.MISSING:
            required.append(f.name)

    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _infer_parameters(fn: Callable) -> list[dict]:
    """Infer OpenAPI parameter objects from a handler's type-annotated signature.

    Cylinder built-in parameters are excluded; everything else becomes a
    candidate API parameter.
    """
    try:
        sig = inspect.signature(fn)
        hints = typing.get_type_hints(fn)
    except Exception:
        return []

    params: list[dict] = []
    for name, param in sig.parameters.items():
        if name in CYLINDER_PARAMS:
            continue

        schema: dict = {}
        hint = hints.get(name)
        if hint is not None:
            json_type = _JSON_TYPE_MAP.get(hint)
            if json_type:
                schema["type"] = json_type

        if param.default is not inspect.Parameter.empty:
            schema["default"] = param.default

        entry: dict = {"name": name}
        if schema:
            entry["schema"] = schema
        params.append(entry)

    return params


def _load_sidecar(handler_file: Path) -> dict:
    """Load an optional ``<handler>.openapi.yaml`` sidecar file."""
    sidecar_path = handler_file.with_name(handler_file.stem + ".openapi.yaml")
    if not sidecar_path.exists():
        return {}
    try:
        import yaml  # pyyaml; imported lazily to avoid hard dep at module level

        return yaml.safe_load(sidecar_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        warnings.warn(f"Could not parse sidecar {sidecar_path}: {exc}", stacklevel=2)
        return {}
