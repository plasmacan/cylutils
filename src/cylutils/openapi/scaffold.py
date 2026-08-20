from __future__ import annotations

from pathlib import Path

# Closing """ always on its own line so multi-line and single-line render consistently.
_HANDLER_TEMPLATE = """\
from werkzeug.wrappers import Request, Response


def main(
    request: Request,
    response: Response,{extra_params}
) -> Response:
    \"\"\"{docstring}
    \"\"\"

    response.status_code = 501
    response.data = "Not implemented"

    return response
"""

_HANDLER_TEMPLATE_NO_DOC = """\
from werkzeug.wrappers import Request, Response


def main(
    request: Request,
    response: Response,{extra_params}
) -> Response:
    response.status_code = 501
    response.data = "Not implemented"

    return response
"""

_JSON_TO_PY: dict[str, str] = {
    "integer": "int",
    "number": "float",
    "string": "str",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}


def scaffold_from_openapi(
    spec_path: str | Path,
    output_dir: str | Path,
    overwrite: bool = False,
) -> list[Path]:
    """Generate Cylinder handler files from an OpenAPI 3.0/3.1 spec.

    Returns the list of files created.  Existing files are skipped unless
    ``overwrite=True``.
    """
    import yaml

    spec_path = Path(spec_path)
    output_dir = Path(output_dir)
    spec: dict = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    paths: dict = spec.get("paths", {})
    components: dict = spec.get("components") or {}
    components_params: dict = components.get("parameters") or {}

    created: list[Path] = []

    for route_path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue

        # Parameters defined at the path level are shared by all methods.
        # Resolve any $ref parameters before using them.
        path_level_params: list[dict] = [
            _resolve_param_ref(p, components_params) for p in path_item.get("parameters", [])
        ]

        for method, operation in path_item.items():
            if method.startswith("x-") or method == "parameters":
                continue
            if not isinstance(operation, dict):
                continue

            segments = [s for s in route_path.strip("/").split("/") if s]
            if not segments:
                # Root handler needs the app-name context; skip for now
                continue

            # Strip OpenAPI path template braces: {todoId} → todoId
            segments = [s[1:-1] if s.startswith("{") and s.endswith("}") else s for s in segments]

            dir_parts = segments[:-1]
            segment = segments[-1]
            dir_path = output_dir.joinpath(*dir_parts) if dir_parts else output_dir
            dir_path.mkdir(parents=True, exist_ok=True)

            handler_path = dir_path / f"{segment}.ex.{method}.py"

            # Operation params override path-level params with the same name.
            op_params: list[dict] = [
                _resolve_param_ref(p, components_params) for p in operation.get("parameters", [])
            ]
            op_param_names = {p.get("name") for p in op_params}
            all_params = op_params + [p for p in path_level_params if p.get("name") not in op_param_names]

            # Collect component schemas referenced by this operation (follows $ref
            # transitively through schemas, responses, and parameters).
            schemas = _collect_refs(operation, components)

            if overwrite or not handler_path.exists():
                handler_path.write_text(
                    _render_handler(operation, all_params, schemas, components),
                    encoding="utf-8",
                )
                created.append(handler_path)

    return created


def _resolve_param_ref(param: dict, components_params: dict) -> dict:
    """Return the resolved parameter object, following a $ref if present."""
    if "$ref" in param:
        ref_name = param["$ref"].split("/")[-1]
        return components_params.get(ref_name, param)
    return param


def _render_handler(
    operation: dict,
    all_params: list[dict] | None = None,
    schemas: dict | None = None,
    components: dict | None = None,
) -> str:
    if all_params is None:
        all_params = operation.get("parameters", [])

    components_schemas: dict = (components or {}).get("schemas") or {}

    # Only query parameters become Python function arguments; path/header/cookie
    # params are accessed via request.path / request.headers / request.cookies.
    sig_params = [p for p in all_params if p.get("in", "query") == "query"]

    extra_lines: list[str] = []
    for p in sig_params:
        name = p.get("name", "param")
        schema = p.get("schema") or {}
        type_str, _ = _normalize_type(schema.get("type"))
        py_type = _JSON_TO_PY.get(type_str, "str")
        if "default" in schema:
            extra_lines.append(f"    {name}: {py_type} = {schema['default']!r},")
        else:
            extra_lines.append(f"    {name}: {py_type},")

    extra_params = ("\n" + "\n".join(extra_lines)) if extra_lines else ""
    docstring = _build_docstring(operation, all_params, components)

    if docstring:
        # Escape braces so .format() doesn't mis-interpret docstring content.
        safe_doc = docstring.replace("{", "{{").replace("}", "}}")
        content = _HANDLER_TEMPLATE.format(extra_params=extra_params, docstring=safe_doc)
    else:
        content = _HANDLER_TEMPLATE_NO_DOC.format(extra_params=extra_params)

    if not schemas:
        return content

    # Generate @dataclass code for each referenced component schema.
    dataclass_blocks: list[str] = []
    needs_optional = False
    for schema_name, schema in schemas.items():
        code, opt = _schema_to_dataclass(schema_name, schema, components_schemas)
        if code:
            if opt:
                needs_optional = True
            dataclass_blocks.append(code)

    if not dataclass_blocks:
        return content

    import_lines = ["from dataclasses import dataclass"]
    if needs_optional:
        import_lines.append("from typing import Optional")
    inject = "\n".join(import_lines) + "\n"
    content = content.replace(
        "from werkzeug.wrappers import Request, Response",
        inject + "from werkzeug.wrappers import Request, Response",
    )
    return content + "\n\n" + "\n\n".join(dataclass_blocks) + "\n"


def _collect_refs(obj: object, components: dict, _visited: set | None = None) -> dict[str, dict]:
    """Recursively find all component schema objects reachable via $ref from obj.

    Follows $ref into schemas, responses, and parameters components so that
    schemas nested inside component responses are discovered.
    """
    if _visited is None:
        _visited = set()
    schemas = components.get("schemas") or {}
    responses = components.get("responses") or {}
    parameters = components.get("parameters") or {}
    found: dict[str, dict] = {}
    if isinstance(obj, dict):
        if "$ref" in obj:
            ref = obj["$ref"]
            if isinstance(ref, str):
                if ref.startswith("#/components/schemas/"):
                    name = ref.split("/")[-1]
                    if name not in _visited and name in schemas:
                        _visited.add(name)
                        found[name] = schemas[name]
                        found.update(_collect_refs(schemas[name], components, _visited))
                elif ref.startswith("#/components/responses/"):
                    resp_name = ref.split("/")[-1]
                    if resp_name in responses:
                        found.update(_collect_refs(responses[resp_name], components, _visited))
                elif ref.startswith("#/components/parameters/"):
                    param_name = ref.split("/")[-1]
                    if param_name in parameters:
                        found.update(_collect_refs(parameters[param_name], components, _visited))
        else:
            for v in obj.values():
                found.update(_collect_refs(v, components, _visited))
    elif isinstance(obj, list):
        for item in obj:
            found.update(_collect_refs(item, components, _visited))
    return found


def _normalize_type(raw_type) -> tuple[str, bool]:
    """Return (type_str, nullable_from_list) from an OpenAPI type value.

    OpenAPI 3.1 allows ``type`` to be a list such as ``[string, null]``.
    Only lists that include the string ``"null"`` (or Python ``None``) are
    treated as nullable.
    """
    if isinstance(raw_type, list):
        non_null = [t for t in raw_type if t not in ("null", None)]
        has_null = any(t in ("null", None) for t in raw_type)
        return ((non_null[0] or "").lower() if non_null else ""), has_null
    return (raw_type or "").lower(), False


def _prop_to_py_type(prop: dict, nullable: bool = False) -> tuple[str, bool]:
    """Return (python_type_str, needs_Optional).

    nullable=True, prop["nullable"]=true, or an OpenAPI 3.1 null-union type
    all wrap the result in Optional[...].
    """
    # Handle $ref as a direct property value.
    if "$ref" in prop:
        ref_name = prop["$ref"].split("/")[-1]
        is_nullable = nullable or bool(prop.get("nullable"))
        if is_nullable:
            return f"Optional[{ref_name}]", True
        return ref_name, False

    type_str, list_nullable = _normalize_type(prop.get("type"))
    is_nullable = nullable or bool(prop.get("nullable")) or list_nullable

    if type_str == "array":
        items = prop.get("items") or {}
        if "$ref" in items:
            item_type = items["$ref"].split("/")[-1]
            base = f"list[{item_type}]"
        elif items.get("type"):
            item_type_str, _ = _normalize_type(items["type"])
            item_type = _JSON_TO_PY.get(item_type_str, "object")
            base = f"list[{item_type}]"
        else:
            base = "list"
    else:
        base = _JSON_TO_PY.get(type_str, "object")

    if is_nullable:
        return f"Optional[{base}]", True
    return base, False


def _merge_allof(schema: dict, components_schemas: dict) -> dict:
    """Flatten allOf into a single properties/required dict.

    Non-allOf schemas are returned unchanged.
    """
    if "allOf" not in schema:
        return schema

    merged_props: dict = {}
    merged_required: list = []

    for sub in schema["allOf"]:
        if "$ref" in sub:
            ref_name = sub["$ref"].split("/")[-1]
            sub = components_schemas.get(ref_name, {})
            # Recursively flatten if the referenced schema also uses allOf.
            sub = _merge_allof(sub, components_schemas)
        merged_props.update(sub.get("properties") or {})
        merged_required.extend(sub.get("required") or [])

    # Direct properties on the allOf object itself override sub-schema properties.
    merged_props.update(schema.get("properties") or {})
    merged_required.extend(schema.get("required") or [])

    return {
        "type": "object",
        "properties": merged_props,
        "required": list(dict.fromkeys(merged_required)),
    }


def _schema_to_dataclass(
    name: str, schema: dict, components_schemas: dict | None = None
) -> tuple[str, bool]:
    """Return (dataclass_code, needs_Optional) for an OpenAPI object schema.

    Non-object schemas or schemas without properties return ("", False).
    allOf schemas are flattened before processing.
    """
    schema = _merge_allof(schema, components_schemas or {})
    properties: dict = schema.get("properties") or {}
    if not properties:
        return "", False

    required_set: set = set(schema.get("required") or [])
    needs_optional = False
    req_lines: list[str] = []
    opt_lines: list[str] = []

    for field_name, prop in properties.items():
        if field_name in required_set:
            py_type, opt = _prop_to_py_type(prop, nullable=bool(prop.get("nullable")))
            if opt:
                needs_optional = True
            req_lines.append(f"    {field_name}: {py_type}")
        else:
            py_type, _ = _prop_to_py_type(prop, nullable=True)
            needs_optional = True
            default = prop.get("default")
            if default is not None:
                opt_lines.append(f"    {field_name}: {py_type} = {default!r}")
            else:
                opt_lines.append(f"    {field_name}: {py_type} = None")

    body = "\n".join(req_lines + opt_lines) or "    pass"
    return f"@dataclass\nclass {name}:\n{body}", needs_optional


def _build_docstring(operation: dict, all_params: list[dict], components: dict | None = None) -> str:  # noqa: PLR0912
    """Build a structured docstring from OpenAPI operation metadata."""
    components_responses: dict = (components or {}).get("responses") or {}
    lines: list[str] = []

    summary = (operation.get("summary") or "").strip()
    description = (operation.get("description") or "").strip()

    if summary:
        lines.append(summary)
    if description and description != summary:
        lines.append("")
        lines.extend(description.splitlines())

    if all_params:
        lines.append("")
        lines.append("Parameters:")
        for p in all_params:
            name = p.get("name", "")
            in_ = p.get("in", "query")
            required = p.get("required", False)
            desc = (p.get("description") or "").strip()
            schema = p.get("schema") or {}
            type_str, _ = _normalize_type(schema.get("type"))

            meta = [x for x in [type_str, in_, "required" if required else ""] if x]
            annotation = f"({', '.join(meta)})" if meta else ""

            line = f"    {name}"
            if annotation:
                line += f" {annotation}"
            if desc:
                line += f": {desc}"
            lines.append(line)

    request_body = operation.get("requestBody") or {}
    if request_body:
        lines.append("")
        lines.append("Request Body:")
        required = request_body.get("required", False)
        req_label = "required" if required else "optional"
        for media_type, media_obj in (request_body.get("content") or {}).items():
            schema = (media_obj or {}).get("schema") or {}
            if "$ref" in schema:
                schema_name = schema["$ref"].split("/")[-1]
                lines.append(f"    ({media_type}, {req_label}): {schema_name}")
            else:
                lines.append(f"    ({media_type}, {req_label})")

    responses = operation.get("responses") or {}
    if responses:
        lines.append("")
        lines.append("Responses:")
        for code, resp in responses.items():
            if isinstance(resp, dict):
                if "$ref" in resp:
                    # Resolve component response for its description.
                    resp_name = resp["$ref"].split("/")[-1]
                    resp = components_responses.get(resp_name) or {}
                resp_desc = resp.get("description") or ""
            else:
                resp_desc = ""
            lines.append(f"    {code}: {resp_desc}")

    if not lines:
        return ""

    # Indent all lines after the first to sit inside the function body.
    raw_lines = "\n".join(lines).split("\n")
    return raw_lines[0] + "\n" + "\n".join(("    " + line) if line else "" for line in raw_lines[1:])
