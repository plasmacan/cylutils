from __future__ import annotations

from pathlib import Path

from .inspect import scan_app
from .models import RouteInfo


def generate_openapi(
    app_path: str | Path,
    title: str = "Cylinder App",
    version: str = "1.0.0",
    reference: dict | None = None,
) -> dict:
    """Generate an OpenAPI 3.0.3 document dict from a Cylinder app directory.

    If ``reference`` is a parsed OpenAPI spec dict, its ``info``, ``servers``,
    ``security``, and ``tags`` fields are used as the base for the output doc.
    """
    routes = scan_app(app_path)

    # Build info section, preferring reference spec metadata if provided
    ref = reference or {}
    ref_info: dict = ref.get("info") or {}
    info: dict = {
        "title": ref_info.get("title") or title,
        "version": ref_info.get("version") or version,
    }
    if ref_info.get("description"):
        info["description"] = ref_info["description"]

    doc: dict = {
        "openapi": "3.0.3",
        "info": info,
        "paths": {},
    }

    # Carry over top-level fields that cannot be inferred from code.
    for key in ("servers", "security", "tags", "externalDocs"):
        if key in ref:
            doc[key] = ref[key]

    all_schemas: dict[str, dict] = {}

    for route in routes:
        operation = _build_operation(route)
        path_entry: dict = doc["paths"].setdefault(route.path, {})

        method_key = route.method.lower()
        if method_key == "default":
            # Cylinder-specific catch-all; not a standard HTTP method
            path_entry.setdefault("x-cylinder-default", []).append(operation)
        else:
            path_entry[method_key] = operation

        all_schemas.update(route.schemas)

    if all_schemas:
        doc["components"] = {"schemas": all_schemas}

    return doc


def _build_operation(route: RouteInfo) -> dict:
    # Strip template braces so operationId is a clean identifier.
    clean_path = route.path.replace("{", "").replace("}", "")
    path_slug = clean_path.strip("/").replace("/", "_") or "root"
    method_slug = route.method.lower()
    auto_operation_id = f"{path_slug}_{method_slug}"

    op: dict = {"operationId": auto_operation_id}
    op.update(route.metadata)

    # Allow sidecar to override operationId explicitly, but not accidentally blank it
    if not op.get("operationId"):
        op["operationId"] = auto_operation_id

    if "responses" not in op:
        op["responses"] = {"200": {"description": "OK"}}

    return op
