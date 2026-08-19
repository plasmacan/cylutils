from __future__ import annotations

from pathlib import Path

_HANDLER_TEMPLATE = """\
from werkzeug.wrappers import Request, Response


def main(
    request: Request,
    response: Response,{extra_params}
) -> Response:
    \"\"\"{docstring}\"\"\"

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
    """Generate Cylinder handler and sidecar files from an OpenAPI 3.0 spec.

    Returns the list of files created.  Existing files are skipped unless
    ``overwrite=True``.
    """
    import yaml

    spec_path = Path(spec_path)
    output_dir = Path(output_dir)
    spec: dict = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    paths: dict = spec.get("paths", {})

    created: list[Path] = []

    for route_path, methods in paths.items():
        for method, operation in methods.items():
            if method.startswith("x-"):
                continue  # skip Cylinder extensions like x-cylinder-default

            segments = [s for s in route_path.strip("/").split("/") if s]
            if not segments:
                # Root handler needs the app-name context; skip for now
                continue

            dir_parts = segments[:-1]
            segment = segments[-1]
            dir_path = output_dir.joinpath(*dir_parts) if dir_parts else output_dir
            dir_path.mkdir(parents=True, exist_ok=True)

            handler_path = dir_path / f"{segment}.ex.{method}.py"
            sidecar_path = dir_path / f"{segment}.ex.{method}.openapi.yaml"

            if overwrite or not handler_path.exists():
                handler_path.write_text(_render_handler(operation), encoding="utf-8")
                created.append(handler_path)

            if overwrite or not sidecar_path.exists():
                sidecar = {k: v for k, v in operation.items() if k != "operationId"}
                sidecar_path.write_text(
                    yaml.dump(sidecar, sort_keys=False, allow_unicode=True),
                    encoding="utf-8",
                )
                created.append(sidecar_path)

    return created


def _render_handler(operation: dict) -> str:
    parameters = operation.get("parameters", [])

    extra_lines: list[str] = []
    for p in parameters:
        name = p.get("name", "param")
        schema = p.get("schema", {})
        py_type = _JSON_TO_PY.get(schema.get("type", ""), "str")
        if "default" in schema:
            extra_lines.append(f"    {name}: {py_type} = {schema['default']!r},")
        else:
            extra_lines.append(f"    {name}: {py_type},")

    extra_params = ("\n" + "\n".join(extra_lines)) if extra_lines else ""

    summary = operation.get("summary", "")
    description = operation.get("description", "")
    if description and summary:
        docstring = f"{summary}\n\n{description}"
    elif description:
        docstring = description
    else:
        docstring = summary

    if docstring:
        return _HANDLER_TEMPLATE.format(extra_params=extra_params, docstring=docstring)
    return _HANDLER_TEMPLATE_NO_DOC.format(extra_params=extra_params)
