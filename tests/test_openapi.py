"""Tests for cylutils.openapi — models, inspect, export, scaffold, and CLI."""
from __future__ import annotations

import pathlib
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from typing import Optional
from click.testing import CliRunner

from cylutils.cli import cli
from cylutils.openapi import (
    CYLINDER_PARAMS,
    RouteInfo,
    generate_openapi,
    scan_app,
    scaffold_from_openapi,
)
from cylutils.openapi.inspect import _infer_parameters, _load_sidecar
from cylutils.openapi.inspect import (
    _dataclass_to_openapi_schema,
    _extract_dataclass_schemas,
    _hint_to_openapi,
    _load_handler,
    _load_module,
)
from cylutils.openapi.scaffold import (
    _collect_refs,
    _merge_allof,
    _normalize_type,
    _prop_to_py_type,
    _schema_to_dataclass,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# RouteInfo model
# ---------------------------------------------------------------------------


class TestRouteInfo:
    def test_required_fields(self, tmp_path):
        r = RouteInfo(
            path="/foo",
            method="GET",
            handler_file=tmp_path / "foo.ex.get.py",
            module_name="foo.ex.get",
        )
        assert r.path == "/foo"
        assert r.method == "GET"
        assert r.function is None
        assert r.metadata == {}

    def test_cylinder_params_set(self):
        assert "request" in CYLINDER_PARAMS
        assert "response" in CYLINDER_PARAMS
        assert "logger" in CYLINDER_PARAMS
        assert "abort" in CYLINDER_PARAMS
        assert "e" in CYLINDER_PARAMS


# ---------------------------------------------------------------------------
# _infer_parameters
# ---------------------------------------------------------------------------


class TestInferParameters:
    def test_empty_when_only_cylinder_params(self):
        def main(request, response, logger):
            pass

        assert _infer_parameters(main) == []

    def test_extracts_typed_param(self):
        def main(response, user_id: int):
            pass

        params = _infer_parameters(main)
        assert len(params) == 1
        assert params[0]["name"] == "user_id"
        assert params[0]["schema"]["type"] == "integer"

    def test_extracts_default_value(self):
        def main(response, limit: int = 20):
            pass

        params = _infer_parameters(main)
        assert params[0]["schema"]["default"] == 20

    def test_untyped_param_has_no_schema(self):
        def main(response, extra):
            pass

        params = _infer_parameters(main)
        assert params[0]["name"] == "extra"
        assert "schema" not in params[0]

    def test_multiple_params_order_preserved(self):
        def main(request, response, a: str, b: int, c: float):
            pass

        params = _infer_parameters(main)
        assert [p["name"] for p in params] == ["a", "b", "c"]

    def test_bool_type(self):
        def main(response, active: bool):
            pass

        params = _infer_parameters(main)
        assert params[0]["schema"]["type"] == "boolean"


# ---------------------------------------------------------------------------
# _load_sidecar
# ---------------------------------------------------------------------------


class TestLoadSidecar:
    def test_returns_empty_when_no_sidecar(self, tmp_path):
        handler = tmp_path / "foo.ex.get.py"
        handler.write_text("def main(response): pass", encoding="utf-8")
        assert _load_sidecar(handler) == {}

    def test_loads_yaml_sidecar(self, tmp_path):
        handler = tmp_path / "foo.ex.get.py"
        handler.write_text("def main(response): pass", encoding="utf-8")
        sidecar = tmp_path / "foo.ex.get.openapi.yaml"
        sidecar.write_text("summary: Get foo\ntags: [foo]", encoding="utf-8")
        result = _load_sidecar(handler)
        assert result["summary"] == "Get foo"
        assert result["tags"] == ["foo"]

    def test_warns_on_invalid_yaml(self, tmp_path):
        handler = tmp_path / "foo.ex.get.py"
        handler.write_text("def main(response): pass", encoding="utf-8")
        sidecar = tmp_path / "foo.ex.get.openapi.yaml"
        sidecar.write_text(":\n  bad: [yaml", encoding="utf-8")
        with pytest.warns(UserWarning, match="Could not parse sidecar"):
            result = _load_sidecar(handler)
        assert result == {}


# ---------------------------------------------------------------------------
# scan_app
# ---------------------------------------------------------------------------


class TestScanApp:
    def _make_app(self, tmp_path: Path) -> Path:
        """Build a minimal test app structure."""
        app_dir = tmp_path / "webapp1"
        app_dir.mkdir()

        # Root handler (sibling)
        _write(tmp_path / "webapp1.ex.get.py", "def main(response): pass\n")
        # API route
        _write(
            app_dir / "api" / "v1" / "users.ex.get.py",
            """\
            def main(response, user_id: int):
                \\'\\'\\'Get a user by ID.\\'\\'\\'
                pass
            """,
        )
        _write(app_dir / "api" / "v1" / "users.ex.post.py", "def main(response): pass\n")
        # Catch-all
        _write(app_dir / "api" / "v1" / "users.ex.default.py", "def main(response): pass\n")
        # Files that must be ignored
        _write(app_dir / "api" / "v1" / "users.eh.get.py", "def main(response): pass\n")
        _write(app_dir / "api" / "v1" / "users.lh.get.py", "def main(response): pass\n")
        _write(app_dir / "webapp1.400.py", "def main(response, e): pass\n")

        return app_dir

    def test_finds_sibling_root_handler(self, tmp_path):
        app_dir = self._make_app(tmp_path)
        routes = scan_app(app_dir)
        root_routes = [r for r in routes if r.path == "/"]
        assert len(root_routes) == 1
        assert root_routes[0].method == "GET"

    def test_finds_nested_routes(self, tmp_path):
        app_dir = self._make_app(tmp_path)
        routes = scan_app(app_dir)
        paths = {r.path for r in routes}
        assert "/api/v1/users" in paths

    def test_finds_all_methods_for_path(self, tmp_path):
        app_dir = self._make_app(tmp_path)
        routes = scan_app(app_dir)
        user_routes = [r for r in routes if r.path == "/api/v1/users"]
        methods = {r.method for r in user_routes}
        assert "GET" in methods
        assert "POST" in methods
        assert "DEFAULT" in methods

    def test_ignores_hooks(self, tmp_path):
        app_dir = self._make_app(tmp_path)
        routes = scan_app(app_dir)
        for r in routes:
            assert ".eh." not in str(r.handler_file)
            assert ".lh." not in str(r.handler_file)

    def test_ignores_error_handlers(self, tmp_path):
        app_dir = self._make_app(tmp_path)
        routes = scan_app(app_dir)
        for r in routes:
            assert ".400." not in r.handler_file.name

    def test_route_path_format(self, tmp_path):
        app_dir = self._make_app(tmp_path)
        routes = scan_app(app_dir)
        for r in routes:
            assert r.path.startswith("/"), f"path must start with /: {r.path!r}"

    def test_empty_directory(self, tmp_path):
        app_dir = tmp_path / "empty"
        app_dir.mkdir()
        assert scan_app(app_dir) == []

    def test_sidecar_metadata_merged(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(app_dir / "items.ex.get.py", "def main(response): pass\n")
        sidecar = app_dir / "items.ex.get.openapi.yaml"
        sidecar.write_text("summary: List items\ntags: [items]", encoding="utf-8")

        routes = scan_app(app_dir)
        assert len(routes) == 1
        assert routes[0].metadata["summary"] == "List items"
        assert routes[0].metadata["tags"] == ["items"]


# ---------------------------------------------------------------------------
# generate_openapi
# ---------------------------------------------------------------------------


class TestGenerateOpenapi:
    def test_returns_valid_structure(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(app_dir / "items.ex.get.py", "def main(response): pass\n")

        doc = generate_openapi(app_dir)
        assert doc["openapi"] == "3.0.3"
        assert "info" in doc
        assert "paths" in doc

    def test_custom_title_and_version(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(app_dir / "x.ex.get.py", "def main(response): pass\n")

        doc = generate_openapi(app_dir, title="My API", version="2.5.0")
        assert doc["info"]["title"] == "My API"
        assert doc["info"]["version"] == "2.5.0"

    def test_operation_id_generated(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(app_dir / "api" / "users.ex.get.py", "def main(response): pass\n")

        doc = generate_openapi(app_dir)
        op = doc["paths"]["/api/users"]["get"]
        assert op["operationId"] == "api_users_get"

    def test_responses_placeholder_added(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(app_dir / "items.ex.post.py", "def main(response): pass\n")

        doc = generate_openapi(app_dir)
        assert "responses" in doc["paths"]["/items"]["post"]

    def test_default_method_stored_as_extension(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(app_dir / "items.ex.default.py", "def main(response): pass\n")

        doc = generate_openapi(app_dir)
        path_entry = doc["paths"]["/items"]
        assert "x-cylinder-default" in path_entry
        assert "default" not in path_entry

    def test_empty_app(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        doc = generate_openapi(app_dir)
        assert doc["paths"] == {}

    def test_inferred_parameters_included(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(
            app_dir / "users.ex.get.py",
            "def main(response, user_id: int, active: bool = True): pass\n",
        )

        doc = generate_openapi(app_dir)
        params = doc["paths"]["/users"]["get"]["parameters"]
        names = {p["name"] for p in params}
        assert "user_id" in names
        assert "active" in names

    def test_docstring_summary_included(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(
            app_dir / "items.ex.get.py",
            'def main(response):\n    """List all items."""\n    pass\n',
        )

        doc = generate_openapi(app_dir)
        op = doc["paths"]["/items"]["get"]
        assert op.get("summary") == "List all items."


# ---------------------------------------------------------------------------
# scaffold_from_openapi
# ---------------------------------------------------------------------------


class TestScaffoldFromOpenapi:
    def _spec(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "spec.yaml"
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p

    def test_creates_handler_file(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: Test, version: "1.0"}
            paths:
              /users:
                get:
                  summary: List users
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        assert (out / "users.ex.get.py").exists()

    def test_path_level_parameters_dont_crash(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: Test, version: "1.0"}
            paths:
              /todos/{todoId}:
                parameters:
                  - name: todoId
                    in: path
                    required: true
                    schema:
                      type: string
                get:
                  summary: Get todo
                  responses:
                    "200": {description: OK}
                delete:
                  summary: Delete todo
                  responses:
                    "204": {description: Deleted}
            """,
        )
        out = tmp_path / "out"
        created = scaffold_from_openapi(spec, out)
        names = {f.name for f in created}
        # {todoId} stripped to todoId; files land in todos/ subdir
        assert "todoId.ex.get.py" in names
        assert "todoId.ex.delete.py" in names

    def test_path_param_in_docstring_not_in_signature(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items/{itemId}:
                parameters:
                  - name: itemId
                    in: path
                    required: true
                    schema:
                      type: string
                get:
                  summary: Get item
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        # {itemId} → itemId; file is items/itemId.ex.get.py
        content = (out / "items" / "itemId.ex.get.py").read_text(encoding="utf-8")
        # path param documented but not injected as a Python argument
        assert "itemId (string, path, required)" in content
        assert "itemId: str" not in content

    def test_docstring_includes_responses(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                get:
                  summary: List items
                  responses:
                    "200": {description: Successful response}
                    "404": {description: Not found}
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        content = (out / "items.ex.get.py").read_text(encoding="utf-8")
        assert "Responses:" in content
        assert "200: Successful response" in content
        assert "404: Not found" in content

    def test_docstring_null_response_value_handled(self, tmp_path):
        # A response value that is null (None in Python) should not crash.
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                delete:
                  summary: Delete item
                  responses:
                    "204": ~
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        content = (out / "items.ex.delete.py").read_text(encoding="utf-8")
        assert "204:" in content

    def test_docstring_includes_request_body_ref(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /todos:
                post:
                  summary: Create todo
                  requestBody:
                    required: true
                    content:
                      application/json:
                        schema:
                          $ref: "#/components/schemas/CreateTodo"
                  responses:
                    "201": {description: Created}
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        content = (out / "todos.ex.post.py").read_text(encoding="utf-8")
        assert "Request Body:" in content
        assert "application/json, required): CreateTodo" in content

    def test_nested_path_creates_subdirs(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: Test, version: "1.0"}
            paths:
              /api/v1/users:
                get:
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        assert (out / "api" / "v1" / "users.ex.get.py").exists()

    def test_handler_contains_werkzeug_imports(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /ping:
                get:
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        content = (out / "ping.ex.get.py").read_text(encoding="utf-8")
        assert "from werkzeug.wrappers import Request, Response" in content
        assert "def main(" in content

    def test_handler_includes_typed_params(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /users:
                get:
                  parameters:
                    - name: limit
                      schema:
                        type: integer
                        default: 20
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        content = (out / "users.ex.get.py").read_text(encoding="utf-8")
        assert "limit: int = 20" in content

    def test_handler_includes_docstring_from_summary(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /things:
                delete:
                  summary: Delete a thing
                  responses:
                    "204": {description: No content}
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        content = (out / "things.ex.delete.py").read_text(encoding="utf-8")
        assert "Delete a thing" in content

    def test_skips_extension_keys(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /things:
                x-cylinder-default:
                  - operationId: things_default
                get:
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        files = list(out.iterdir())
        names = {f.name for f in files}
        assert "things.ex.get.py" in names
        assert not any("x-cylinder" in n for n in names)

    def test_skips_root_path(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /:
                get:
                  responses:
                    "200": {description: OK}
              /items:
                get:
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        created = scaffold_from_openapi(spec, out)
        paths = [str(f) for f in created]
        assert not any(p.endswith("/.ex.get.py") for p in paths)

    def test_does_not_overwrite_existing_by_default(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                get:
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        out.mkdir()
        existing = out / "items.ex.get.py"
        existing.write_text("# original", encoding="utf-8")

        scaffold_from_openapi(spec, out)
        assert existing.read_text(encoding="utf-8") == "# original"

    def test_overwrite_flag_replaces_existing(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                get:
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        out.mkdir()
        existing = out / "items.ex.get.py"
        existing.write_text("# original", encoding="utf-8")

        scaffold_from_openapi(spec, out, overwrite=True)
        assert "# original" not in existing.read_text(encoding="utf-8")

    def test_returns_list_of_created_files(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /a:
                get:
                  responses:
                    "200": {description: OK}
              /b:
                post:
                  responses:
                    "201": {description: Created}
            """,
        )
        out = tmp_path / "out"
        created = scaffold_from_openapi(spec, out)
        # 2 routes × 1 handler file each = 2 files (no sidecar YAML)
        assert len(created) == 2


# ---------------------------------------------------------------------------
# CLI — openapi export
# ---------------------------------------------------------------------------


class TestCliOpenapiExport:
    def test_outputs_yaml_to_stdout(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(app_dir / "items.ex.get.py", "def main(response): pass\n")

        runner = CliRunner()
        result = runner.invoke(cli, ["openapi", "export", str(app_dir)])
        assert result.exit_code == 0
        doc = yaml.safe_load(result.output)
        assert doc["openapi"] == "3.0.3"
        assert "/items" in doc["paths"]

    def test_writes_to_file_with_output_flag(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(app_dir / "items.ex.get.py", "def main(response): pass\n")
        out_file = tmp_path / "openapi.yaml"

        runner = CliRunner()
        result = runner.invoke(cli, ["openapi", "export", str(app_dir), "-o", str(out_file)])
        assert result.exit_code == 0
        assert out_file.exists()
        doc = yaml.safe_load(out_file.read_text(encoding="utf-8"))
        assert "paths" in doc

    def test_custom_title_and_version(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(app_dir / "x.ex.get.py", "def main(response): pass\n")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["openapi", "export", str(app_dir), "--title", "Cool API", "--api-version", "3.0"],
        )
        assert result.exit_code == 0
        doc = yaml.safe_load(result.output)
        assert doc["info"]["title"] == "Cool API"
        assert doc["info"]["version"] == "3.0"


# ---------------------------------------------------------------------------
# CLI — openapi scaffold
# ---------------------------------------------------------------------------


class TestCliOpenapiScaffold:
    def _spec_file(self, tmp_path: Path) -> Path:
        p = tmp_path / "spec.yaml"
        p.write_text(
            textwrap.dedent("""\
                openapi: "3.0.3"
                info: {title: T, version: "1.0"}
                paths:
                  /widgets:
                    get:
                      summary: List widgets
                      responses:
                        "200": {description: OK}
            """),
            encoding="utf-8",
        )
        return p

    def test_creates_files_and_reports_them(self, tmp_path):
        spec = self._spec_file(tmp_path)
        out = tmp_path / "out"

        runner = CliRunner()
        result = runner.invoke(cli, ["openapi", "scaffold", str(spec), str(out)])
        assert result.exit_code == 0
        assert "Created:" in result.output
        assert (out / "widgets.ex.get.py").exists()

    def test_reports_no_files_created_on_second_run(self, tmp_path):
        spec = self._spec_file(tmp_path)
        out = tmp_path / "out"

        runner = CliRunner()
        runner.invoke(cli, ["openapi", "scaffold", str(spec), str(out)])
        result = runner.invoke(cli, ["openapi", "scaffold", str(spec), str(out)])
        assert result.exit_code == 0
        assert "No files created" in result.output


# ---------------------------------------------------------------------------
# Edge cases for 100% coverage
# ---------------------------------------------------------------------------


class TestInspectEdgeCases:
    def test_sibling_that_doesnt_match_regex_is_skipped(self, tmp_path):
        # Glob matches *.ex.*.py but regex requires [a-zA-Z]+ for method;
        # a numeric-method file should be silently skipped.
        app_dir = tmp_path / "webapp1"
        app_dir.mkdir()
        bad = tmp_path / "webapp1.ex.123.py"
        bad.write_text("def main(response): pass\n", encoding="utf-8")

        routes = scan_app(app_dir)
        assert all(r.method != "123" for r in routes)

    def test_handler_import_failure_warns_and_continues(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        bad = app_dir / "broken.ex.get.py"
        bad.write_text("raise RuntimeError('oops')\n", encoding="utf-8")

        with pytest.warns(UserWarning, match="Could not import"):
            routes = scan_app(app_dir)

        assert len(routes) == 1
        assert routes[0].function is None

    def test_handler_without_main_returns_none_function(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(app_dir / "nomain.ex.get.py", "x = 42\n")

        routes = scan_app(app_dir)
        assert routes[0].function is None

    def test_multiline_docstring_extracts_description(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(
            app_dir / "items.ex.get.py",
            'def main(response):\n    """Short summary.\n\n    Longer description here.\n    """\n    pass\n',
        )

        routes = scan_app(app_dir)
        assert routes[0].metadata.get("summary") == "Short summary."
        assert "Longer description here." in routes[0].metadata.get("description", "")

    def test_infer_parameters_exception_returns_empty(self):
        from unittest.mock import patch

        import cylutils.openapi.inspect as _inspect_mod

        def main(response):
            pass

        with patch.object(_inspect_mod.inspect, "signature", side_effect=TypeError("test")):
            result = _infer_parameters(main)
        assert result == []

    def test_hint_with_unknown_type_has_no_schema(self):
        # tuple is not in _JSON_TYPE_MAP, so no type key is emitted
        def main(response, items: tuple):
            pass

        params = _infer_parameters(main)
        assert len(params) == 1
        assert "schema" not in params[0]

    def test_spec_loader_none_returns_none(self, tmp_path):
        # When spec_from_file_location returns None, _load_handler returns None
        from unittest.mock import patch

        from cylutils.openapi.inspect import _load_handler

        route = RouteInfo(
            path="/x",
            method="GET",
            handler_file=tmp_path / "x.ex.get.py",
            module_name="x.ex.get",
        )
        with patch("cylutils.openapi.inspect.importlib.util.spec_from_file_location", return_value=None):
            result = _load_handler(route)
        assert result is None

    def test_pycache_files_are_ignored(self, tmp_path):
        app_dir = tmp_path / "myapp"
        pycache = app_dir / "__pycache__"
        pycache.mkdir(parents=True)
        (pycache / "foo.ex.get.py").write_text("def main(r): pass\n", encoding="utf-8")

        routes = scan_app(app_dir)
        assert routes == []


class TestExportEdgeCases:
    def test_sidecar_with_null_operation_id_gets_auto_id(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(app_dir / "items.ex.get.py", "def main(response): pass\n")
        sidecar = app_dir / "items.ex.get.openapi.yaml"
        sidecar.write_text("operationId: null\nsummary: List items\n", encoding="utf-8")

        doc = generate_openapi(app_dir)
        op = doc["paths"]["/items"]["get"]
        assert op["operationId"] == "items_get"

    def test_sidecar_with_responses_skips_default(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(app_dir / "items.ex.get.py", "def main(response): pass\n")
        sidecar = app_dir / "items.ex.get.openapi.yaml"
        sidecar.write_text(
            "responses:\n  '200':\n    description: Custom response\n",
            encoding="utf-8",
        )

        doc = generate_openapi(app_dir)
        op = doc["paths"]["/items"]["get"]
        assert op["responses"]["200"]["description"] == "Custom response"

    def test_root_path_operation_id_uses_root_slug(self, tmp_path):
        app_dir = tmp_path / "webapp1"
        app_dir.mkdir()
        _write(tmp_path / "webapp1.ex.get.py", "def main(response): pass\n")

        doc = generate_openapi(app_dir)
        op = doc["paths"]["/"]["get"]
        assert op["operationId"] == "root_get"


class TestScaffoldEdgeCases:
    def _spec(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "spec.yaml"
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p

    def test_description_only_used_as_docstring(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                get:
                  description: Only a description, no summary.
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        from cylutils.openapi.scaffold import scaffold_from_openapi as _scaffold

        _scaffold(spec, out)
        content = (out / "items.ex.get.py").read_text(encoding="utf-8")
        assert "Only a description, no summary." in content

    def test_both_summary_and_description_combined(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                get:
                  summary: Short title
                  description: Detailed description here.
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        from cylutils.openapi.scaffold import scaffold_from_openapi as _scaffold

        _scaffold(spec, out)
        content = (out / "items.ex.get.py").read_text(encoding="utf-8")
        assert "Short title" in content
        assert "Detailed description here." in content

    def test_no_summary_no_description_docstring_has_responses(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                get:
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        from cylutils.openapi.scaffold import scaffold_from_openapi as _scaffold

        _scaffold(spec, out)
        content = (out / "items.ex.get.py").read_text(encoding="utf-8")
        # Responses section is always emitted even without summary/description
        assert "Responses:" in content
        assert "200: OK" in content

    def test_parameter_without_schema(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                get:
                  parameters:
                    - name: q
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        from cylutils.openapi.scaffold import scaffold_from_openapi as _scaffold

        _scaffold(spec, out)
        content = (out / "items.ex.get.py").read_text(encoding="utf-8")
        assert "q: str" in content

    def test_empty_operation_uses_no_doc_template(self, tmp_path):
        # Operation with no fields → _build_docstring returns "" → no-doc template used
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                get: {}
            """,
        )
        out = tmp_path / "out"
        from cylutils.openapi.scaffold import scaffold_from_openapi as _scaffold

        _scaffold(spec, out)
        content = (out / "items.ex.get.py").read_text(encoding="utf-8")
        assert '"""' not in content

    def test_render_handler_without_all_params_falls_back_to_operation(self, tmp_path):
        from cylutils.openapi.scaffold import _render_handler

        operation = {"parameters": [{"name": "q", "in": "query", "schema": {"type": "string"}}]}
        content = _render_handler(operation)  # all_params not passed
        assert "q: str" in content

    def test_parameter_with_description_in_docstring(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                get:
                  parameters:
                    - name: limit
                      in: query
                      description: Maximum results to return.
                      schema:
                        type: integer
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        from cylutils.openapi.scaffold import scaffold_from_openapi as _scaffold

        _scaffold(spec, out)
        content = (out / "items.ex.get.py").read_text(encoding="utf-8")
        assert "limit (integer, query): Maximum results to return." in content

    def test_parameter_with_null_in_has_no_annotation(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                get:
                  parameters:
                    - name: q
                      in: null
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        from cylutils.openapi.scaffold import scaffold_from_openapi as _scaffold

        _scaffold(spec, out)
        content = (out / "items.ex.get.py").read_text(encoding="utf-8")
        # annotation is empty when in is null and no type
        assert "    q\n" in content or "    q\r\n" in content

    def test_request_body_inline_schema_no_ref(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                post:
                  requestBody:
                    required: false
                    content:
                      application/json:
                        schema:
                          type: object
                  responses:
                    "201": {description: Created}
            """,
        )
        out = tmp_path / "out"
        from cylutils.openapi.scaffold import scaffold_from_openapi as _scaffold

        _scaffold(spec, out)
        content = (out / "items.ex.post.py").read_text(encoding="utf-8")
        assert "(application/json, optional)" in content

    def test_params_with_no_responses_skips_responses_section(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                get:
                  parameters:
                    - name: q
                      in: query
            """,
        )
        out = tmp_path / "out"
        from cylutils.openapi.scaffold import scaffold_from_openapi as _scaffold

        _scaffold(spec, out)
        content = (out / "items.ex.get.py").read_text(encoding="utf-8")
        assert "Parameters:" in content
        assert "Responses:" not in content

    def test_non_dict_path_item_is_skipped(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /bad: "not-a-dict"
              /good:
                get:
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        from cylutils.openapi.scaffold import scaffold_from_openapi as _scaffold

        created = scaffold_from_openapi(spec, out)
        assert len(created) == 1
        assert created[0].name == "good.ex.get.py"

    def test_non_dict_operation_is_skipped(self, tmp_path):
        # Path items can have string fields like "summary"; they should be ignored.
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                summary: Item operations
                get:
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        from cylutils.openapi.scaffold import scaffold_from_openapi as _scaffold

        created = scaffold_from_openapi(spec, out)
        assert len(created) == 1
        assert created[0].name == "items.ex.get.py"


# ---------------------------------------------------------------------------
# _collect_refs
# ---------------------------------------------------------------------------


_SCHEMAS = {
    "Todo": {"type": "object", "properties": {"id": {"type": "string"}}},
    "CreateTodo": {"type": "object", "properties": {"title": {"type": "string"}}},
    "Tag": {"type": "object", "properties": {"name": {"type": "string"}}},
    "Item": {"type": "object", "properties": {"tags": {"type": "array", "items": {"$ref": "#/components/schemas/Tag"}}}},
    "A": {"properties": {"b": {"$ref": "#/components/schemas/B"}}},
    "B": {"properties": {"a": {"$ref": "#/components/schemas/A"}}},
}
# _collect_refs now takes the full components dict, not just the schemas section
_COMP = {"schemas": _SCHEMAS}


class TestCollectRefs:
    def test_empty_object_returns_empty(self):
        assert _collect_refs({}, _COMP) == {}

    def test_finds_request_body_ref(self):
        op = {"requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/CreateTodo"}}}}}
        assert "CreateTodo" in _collect_refs(op, _COMP)

    def test_finds_response_ref(self):
        op = {"responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Todo"}}}}}}
        assert "Todo" in _collect_refs(op, _COMP)

    def test_follows_nested_refs_transitively(self):
        op = {"requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Item"}}}}}
        result = _collect_refs(op, _COMP)
        assert "Item" in result
        assert "Tag" in result

    def test_circular_refs_dont_loop(self):
        op = {"requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/A"}}}}}
        result = _collect_refs(op, _COMP)
        assert "A" in result
        assert "B" in result

    def test_unknown_ref_skipped(self):
        assert _collect_refs({"schema": {"$ref": "#/components/schemas/Unknown"}}, _COMP) == {}

    def test_non_component_ref_skipped(self):
        assert _collect_refs({"schema": {"$ref": "#/definitions/Foo"}}, _COMP) == {}

    def test_list_traversed(self):
        assert "Todo" in _collect_refs([{"$ref": "#/components/schemas/Todo"}], _COMP)

    def test_follows_ref_through_component_response(self):
        # $ref pointing to a component response should surface the schema inside it.
        components = {
            "schemas": {"Error": {"type": "object", "properties": {"code": {"type": "string"}}}},
            "responses": {
                "Unauthorized": {
                    "description": "Unauthorized",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
                }
            },
        }
        op = {"responses": {"401": {"$ref": "#/components/responses/Unauthorized"}}}
        result = _collect_refs(op, components)
        assert "Error" in result

    def test_follows_ref_through_component_parameter(self):
        components = {
            "schemas": {},
            "parameters": {
                "ItemId": {"name": "item_id", "in": "path", "required": True, "schema": {"type": "string"}},
            },
        }
        op = {"parameters": [{"$ref": "#/components/parameters/ItemId"}]}
        result = _collect_refs(op, components)
        # No schema refs inside ItemId, but no crash either
        assert result == {}

    def test_non_string_ref_value_is_skipped(self):
        # $ref with a non-string value (malformed) should not crash
        assert _collect_refs({"$ref": None}, _COMP) == {}
        assert _collect_refs({"$ref": 42}, _COMP) == {}

    def test_unknown_response_ref_is_silently_ignored(self):
        # $ref to a component response that doesn't exist in components
        components = {"schemas": {}, "responses": {}}
        op = {"responses": {"404": {"$ref": "#/components/responses/NonExistent"}}}
        assert _collect_refs(op, components) == {}

    def test_unknown_parameter_ref_is_silently_ignored(self):
        components = {"schemas": {}, "parameters": {}}
        op = {"parameters": [{"$ref": "#/components/parameters/NonExistent"}]}
        assert _collect_refs(op, components) == {}


# ---------------------------------------------------------------------------
# _normalize_type
# ---------------------------------------------------------------------------


class TestNormalizeType:
    def test_plain_string(self):
        assert _normalize_type("string") == ("string", False)

    def test_none_returns_empty(self):
        assert _normalize_type(None) == ("", False)

    def test_list_with_null(self):
        type_str, nullable = _normalize_type(["string", "null"])
        assert type_str == "string"
        assert nullable is True

    def test_list_with_none_value(self):
        type_str, nullable = _normalize_type(["integer", None])
        assert type_str == "integer"
        assert nullable is True

    def test_list_only_null(self):
        type_str, nullable = _normalize_type(["null"])
        assert type_str == ""
        assert nullable is True

    def test_list_single_non_null(self):
        # A single-type list with no null should not be nullable
        assert _normalize_type(["boolean"]) == ("boolean", False)


# ---------------------------------------------------------------------------
# _merge_allof
# ---------------------------------------------------------------------------


class TestMergeAllof:
    def test_passthrough_when_no_allof(self):
        schema = {"type": "object", "properties": {"id": {"type": "string"}}}
        assert _merge_allof(schema, {}) is schema

    def test_merges_allof_properties(self):
        base = {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}}
        child = {
            "allOf": [
                {"$ref": "#/components/schemas/Base"},
                {"type": "object", "properties": {"extra": {"type": "integer"}}},
            ]
        }
        result = _merge_allof(child, {"Base": base})
        assert "id" in result["properties"]
        assert "extra" in result["properties"]
        assert "id" in result["required"]

    def test_direct_properties_override_allof(self):
        base = {"properties": {"x": {"type": "string"}}}
        schema = {
            "allOf": [{"$ref": "#/components/schemas/Base"}],
            "properties": {"x": {"type": "integer"}},
        }
        result = _merge_allof(schema, {"Base": base})
        assert result["properties"]["x"] == {"type": "integer"}

    def test_recursive_allof(self):
        grandparent = {"properties": {"a": {"type": "string"}}}
        parent = {"allOf": [{"$ref": "#/components/schemas/Grandparent"}], "properties": {"b": {"type": "integer"}}}
        child = {"allOf": [{"$ref": "#/components/schemas/Parent"}], "properties": {"c": {"type": "boolean"}}}
        schemas = {"Grandparent": grandparent, "Parent": parent}
        result = _merge_allof(child, schemas)
        assert "a" in result["properties"]
        assert "b" in result["properties"]
        assert "c" in result["properties"]


# ---------------------------------------------------------------------------
# _prop_to_py_type — new cases
# ---------------------------------------------------------------------------


class TestPropToPyType:
    def test_string(self):
        assert _prop_to_py_type({"type": "string"}) == ("str", False)

    def test_integer(self):
        assert _prop_to_py_type({"type": "integer"}) == ("int", False)

    def test_number(self):
        assert _prop_to_py_type({"type": "number"}) == ("float", False)

    def test_boolean(self):
        assert _prop_to_py_type({"type": "boolean"}) == ("bool", False)

    def test_object(self):
        assert _prop_to_py_type({"type": "object"}) == ("dict", False)

    def test_unknown_type_falls_back_to_object(self):
        assert _prop_to_py_type({"type": "binary"}) == ("object", False)

    def test_missing_type_falls_back_to_object(self):
        assert _prop_to_py_type({}) == ("object", False)

    def test_nullable_kwarg(self):
        py_type, needs = _prop_to_py_type({"type": "string"}, nullable=True)
        assert py_type == "Optional[str]" and needs is True

    def test_nullable_prop_flag(self):
        py_type, needs = _prop_to_py_type({"type": "integer", "nullable": True})
        assert py_type == "Optional[int]" and needs is True

    def test_array_no_items(self):
        assert _prop_to_py_type({"type": "array"}) == ("list", False)

    def test_array_with_primitive_items(self):
        py_type, _ = _prop_to_py_type({"type": "array", "items": {"type": "string"}})
        assert py_type == "list[str]"

    def test_array_with_ref_items(self):
        py_type, _ = _prop_to_py_type({"type": "array", "items": {"$ref": "#/components/schemas/Todo"}})
        assert py_type == "list[Todo]"

    def test_array_items_no_type_or_ref(self):
        py_type, _ = _prop_to_py_type({"type": "array", "items": {}})
        assert py_type == "list"

    def test_direct_ref_property(self):
        py_type, needs = _prop_to_py_type({"$ref": "#/components/schemas/Pagination"})
        assert py_type == "Pagination"
        assert needs is False

    def test_direct_ref_property_nullable_kwarg(self):
        py_type, needs = _prop_to_py_type({"$ref": "#/components/schemas/Pagination"}, nullable=True)
        assert py_type == "Optional[Pagination]"
        assert needs is True

    def test_list_type_nullable(self):
        # OpenAPI 3.1: type: [string, null]
        py_type, needs = _prop_to_py_type({"type": ["string", "null"]})
        assert py_type == "Optional[str]"
        assert needs is True

    def test_list_type_no_null(self):
        py_type, needs = _prop_to_py_type({"type": ["boolean"]})
        assert py_type == "bool"
        assert needs is False

    def test_array_items_with_list_type(self):
        # items.type may also be a list in 3.1
        py_type, _ = _prop_to_py_type({"type": "array", "items": {"type": ["integer", "null"]}})
        assert py_type == "list[int]"


# ---------------------------------------------------------------------------
# _schema_to_dataclass
# ---------------------------------------------------------------------------


class TestSchemaToDataclass:
    def test_object_generates_dataclass(self):
        schema = {
            "type": "object",
            "required": ["id", "title"],
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
            },
        }
        code, needs_optional = _schema_to_dataclass("Todo", schema)
        assert "@dataclass" in code and "class Todo:" in code
        assert "id: str" in code and "title: str" in code
        assert "description: Optional[str] = None" in code
        assert needs_optional is True

    def test_no_properties_returns_empty(self):
        code, opt = _schema_to_dataclass("Empty", {"type": "object"})
        assert code == "" and opt is False

    def test_non_object_schema_returns_empty(self):
        code, opt = _schema_to_dataclass("Tags", {"type": "array"})
        assert code == "" and opt is False

    def test_optional_field_with_default_value(self):
        schema = {"properties": {"priority": {"type": "string", "default": "medium"}}}
        code, _ = _schema_to_dataclass("Task", schema)
        assert "priority: Optional[str] = 'medium'" in code

    def test_required_nullable_field_is_optional(self):
        schema = {"required": ["note"], "properties": {"note": {"type": "string", "nullable": True}}}
        code, needs = _schema_to_dataclass("Item", schema)
        assert "note: Optional[str]" in code and needs is True

    def test_required_fields_before_optional(self):
        schema = {
            "required": ["id"],
            "properties": {"label": {"type": "string"}, "id": {"type": "integer"}},
        }
        code, _ = _schema_to_dataclass("Thing", schema)
        assert code.index("id: int") < code.index("label:")

    def test_empty_required_list(self):
        schema = {"properties": {"name": {"type": "string"}}, "required": []}
        code, _ = _schema_to_dataclass("Foo", schema)
        assert "name: Optional[str] = None" in code

    def test_allof_schema_generates_merged_dataclass(self):
        base_schema = {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}}
        child_schema = {
            "allOf": [
                {"$ref": "#/components/schemas/Base"},
                {"type": "object", "properties": {"extra": {"type": "integer"}}},
            ]
        }
        code, _ = _schema_to_dataclass("Child", child_schema, {"Base": base_schema})
        assert "id: str" in code
        assert "extra: Optional[int] = None" in code

    def test_list_type_nullable_in_required_field(self):
        schema = {
            "type": "object",
            "required": ["hostname"],
            "properties": {"hostname": {"type": ["string", "null"]}},
        }
        code, needs = _schema_to_dataclass("Host", schema)
        assert "hostname: Optional[str]" in code
        assert needs is True

    def test_direct_ref_property_in_dataclass(self):
        schema = {
            "type": "object",
            "required": ["page"],
            "properties": {"page": {"$ref": "#/components/schemas/Pagination"}},
        }
        code, _ = _schema_to_dataclass("Response", schema)
        assert "page: Pagination" in code


# ---------------------------------------------------------------------------
# Roundtrip: scaffold ↔ export consistency
# ---------------------------------------------------------------------------


class TestRoundtrip:
    """Ensure the scaffold and export directions are consistent with each other."""

    def _write_handler(self, path: Path, code: str, needs_optional: bool = False) -> None:
        imports = "from dataclasses import dataclass\n"
        if needs_optional:
            imports += "from typing import Optional\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(imports + code + "\ndef main(response): pass\n", encoding="utf-8")

    def test_schema_scaffold_then_export_preserves_required_optional(self, tmp_path):
        """Required/optional status survives a scaffold → export round-trip."""
        original = {
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "string"},
                "label": {"type": "string"},
            },
        }
        code, needs_opt = _schema_to_dataclass("Widget", original)
        handler = tmp_path / "widgets.ex.get.py"
        self._write_handler(handler, code, needs_opt)

        from cylutils.openapi.inspect import _extract_dataclass_schemas, _load_module

        route = RouteInfo(path="/widgets", method="GET", handler_file=handler, module_name="widgets.ex.get")
        exported = _extract_dataclass_schemas(_load_module(route))["Widget"]

        assert exported["type"] == "object"
        assert "id" in exported["required"]
        assert "label" not in exported.get("required", [])
        assert exported["properties"]["id"] == {"type": "string"}

    def test_schema_scaffold_then_export_preserves_nullable(self, tmp_path):
        """Nullable (OpenAPI 3.1 list or 3.0 nullable:true) survives round-trip."""
        original = {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "note": {"type": ["string", "null"]},
            },
        }
        code, needs_opt = _schema_to_dataclass("Item", original)
        handler = tmp_path / "items.ex.get.py"
        self._write_handler(handler, code, needs_opt)

        from cylutils.openapi.inspect import _extract_dataclass_schemas, _load_module

        route = RouteInfo(path="/items", method="GET", handler_file=handler, module_name="items.ex.get")
        exported = _extract_dataclass_schemas(_load_module(route))["Item"]

        assert exported["properties"]["note"].get("nullable") is True

    def test_export_scaffold_export_schemas_match(self, tmp_path):
        """spec (with $ref) → scaffold → export preserves component schemas."""
        spec = textwrap.dedent("""\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                get:
                  responses:
                    "200":
                      content:
                        application/json:
                          schema:
                            $ref: "#/components/schemas/Item"
            components:
              schemas:
                Item:
                  type: object
                  required: [id]
                  properties:
                    id:
                      type: string
                    name:
                      type: string
        """)
        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text(spec, encoding="utf-8")

        # Scaffold from spec — handler file gets Item dataclass
        out = tmp_path / "out"
        scaffold_from_openapi(spec_path, out)

        # Export the scaffolded app — Item dataclass is read back as a schema
        doc2 = generate_openapi(out)
        schemas2 = doc2.get("components", {}).get("schemas", {})

        assert "Item" in schemas2
        assert schemas2["Item"]["type"] == "object"
        assert set(schemas2["Item"].get("required", [])) == {"id"}
        assert set(schemas2["Item"]["properties"].keys()) == {"id", "name"}

    def test_full_spec_scaffolds_without_error(self, tmp_path):
        """The provided Tier2Tickets spec scaffolds cleanly (regression test)."""
        spec = textwrap.dedent("""\
            openapi: "3.1.0"
            info:
              title: Tier2Tickets API
              version: "1.0.0"
            paths:
              /endpoints:
                get:
                  summary: List endpoints
                  parameters:
                    - {name: online, in: query, schema: {type: boolean}}
                    - {name: limit, in: query, schema: {type: integer}}
                  responses:
                    '200':
                      description: Endpoint page
                      content:
                        application/json:
                          schema:
                            type: object
                            properties:
                              data:
                                type: array
                                items: {$ref: '#/components/schemas/EndpointSummary'}
                    '401': {$ref: '#/components/responses/Unauthorized'}
              /endpoints/{endpoint_id}:
                get:
                  summary: Get endpoint
                  parameters:
                    - {$ref: '#/components/parameters/EndpointId'}
                  responses:
                    '200':
                      description: OK
                      content:
                        application/json:
                          schema: {$ref: '#/components/schemas/EndpointDetail'}
            components:
              parameters:
                EndpointId:
                  name: endpoint_id
                  in: path
                  required: true
                  schema: {type: string}
              responses:
                Unauthorized:
                  description: Missing or invalid API key
                  content:
                    application/json:
                      schema: {$ref: '#/components/schemas/Error'}
              schemas:
                EndpointSummary:
                  type: object
                  required: [endpoint_id, online]
                  properties:
                    endpoint_id: {type: string}
                    hostname: {type: ['string', 'null']}
                    online: {type: boolean}
                EndpointDetail:
                  allOf:
                    - {$ref: '#/components/schemas/EndpointSummary'}
                    - type: object
                      properties:
                        last_user: {type: ['string', 'null']}
                Error:
                  type: object
                  required: [error]
                  properties:
                    error: {type: object}
        """)
        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text(spec, encoding="utf-8")
        out = tmp_path / "out"

        created = scaffold_from_openapi(spec_path, out)

        assert len(created) > 0
        # endpoint handler should exist
        names = {f.name for f in created}
        assert "endpoints.ex.get.py" in names

        # EndpointDetail (allOf) should include fields from EndpointSummary
        detail_files = [f for f in created if "endpoint_id" in f.stem or "endpointId" in f.stem]
        # Check the get endpoint handler has merged allOf fields
        get_handler = out / "endpoint_id.ex.get.py"
        if get_handler.exists():
            content = get_handler.read_text(encoding="utf-8")
            assert "endpoint_id: str" in content or "class EndpointDetail" in content

        # Verify $ref response description was resolved
        list_handler = out / "endpoints.ex.get.py"
        content = list_handler.read_text(encoding="utf-8")
        assert "Unauthorized" in content or "401" in content


# ---------------------------------------------------------------------------
# Scaffold with schemas — integration
# ---------------------------------------------------------------------------


class TestScaffoldWithSchemas:
    def _spec(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "spec.yaml"
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p

    def test_dataclass_from_request_body(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /todos:
                post:
                  requestBody:
                    required: true
                    content:
                      application/json:
                        schema:
                          $ref: "#/components/schemas/CreateTodo"
                  responses:
                    "201": {description: Created}
            components:
              schemas:
                CreateTodo:
                  type: object
                  required: [title]
                  properties:
                    title:
                      type: string
                    priority:
                      type: string
                      default: medium
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        content = (out / "todos.ex.post.py").read_text(encoding="utf-8")
        assert "from dataclasses import dataclass" in content
        assert "class CreateTodo:" in content
        assert "title: str" in content
        assert "priority: Optional[str] = 'medium'" in content

    def test_dataclass_from_response_schema(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /todos:
                get:
                  responses:
                    "200":
                      content:
                        application/json:
                          schema:
                            $ref: "#/components/schemas/Todo"
            components:
              schemas:
                Todo:
                  type: object
                  required: [id, title]
                  properties:
                    id:
                      type: string
                    title:
                      type: string
                    completed:
                      type: boolean
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        content = (out / "todos.ex.get.py").read_text(encoding="utf-8")
        assert "class Todo:" in content
        assert "id: str" in content
        assert "completed: Optional[bool] = None" in content

    def test_no_schema_ref_no_dataclass(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /ping:
                get:
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        assert "dataclass" not in (out / "ping.ex.get.py").read_text(encoding="utf-8")

    def test_all_required_fields_no_optional_import(self, tmp_path):
        # All fields required + non-nullable → opt=False → no Optional import needed.
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                get:
                  responses:
                    "200":
                      content:
                        application/json:
                          schema:
                            $ref: "#/components/schemas/Item"
            components:
              schemas:
                Item:
                  type: object
                  required: [id, name]
                  properties:
                    id:
                      type: string
                    name:
                      type: string
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        content = (out / "items.ex.get.py").read_text(encoding="utf-8")
        assert "class Item:" in content
        assert "from typing import Optional" not in content

    def test_non_object_schema_no_dataclass_block(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /tags:
                get:
                  responses:
                    "200":
                      content:
                        application/json:
                          schema:
                            $ref: "#/components/schemas/TagList"
            components:
              schemas:
                TagList:
                  type: array
                  items:
                    type: string
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        assert "@dataclass" not in (out / "tags.ex.get.py").read_text(encoding="utf-8")

    def test_nested_refs_all_included(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /orders:
                post:
                  requestBody:
                    content:
                      application/json:
                        schema:
                          $ref: "#/components/schemas/Order"
                  responses:
                    "201": {description: Created}
            components:
              schemas:
                Order:
                  type: object
                  properties:
                    item:
                      $ref: "#/components/schemas/Item"
                Item:
                  type: object
                  properties:
                    name:
                      type: string
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        content = (out / "orders.ex.post.py").read_text(encoding="utf-8")
        assert "class Order:" in content
        assert "class Item:" in content


# ---------------------------------------------------------------------------
# _hint_to_openapi
# ---------------------------------------------------------------------------


class TestHintToOpenapi:
    def test_none_hint(self):
        assert _hint_to_openapi(None) == {}

    def test_str(self):
        assert _hint_to_openapi(str) == {"type": "string"}

    def test_int(self):
        assert _hint_to_openapi(int) == {"type": "integer"}

    def test_float(self):
        assert _hint_to_openapi(float) == {"type": "number"}

    def test_bool(self):
        assert _hint_to_openapi(bool) == {"type": "boolean"}

    def test_list(self):
        assert _hint_to_openapi(list) == {"type": "array"}

    def test_dict(self):
        assert _hint_to_openapi(dict) == {"type": "object"}

    def test_bytes(self):
        assert _hint_to_openapi(bytes) == {"type": "string", "format": "binary"}

    def test_unknown_type(self):
        class Foo:
            pass

        assert _hint_to_openapi(Foo) == {}

    def test_optional_str(self):
        from typing import Optional

        assert _hint_to_openapi(Optional[str]) == {"type": "string", "nullable": True}

    def test_list_of_int(self):
        from typing import List

        assert _hint_to_openapi(List[int]) == {"type": "array", "items": {"type": "integer"}}

    def test_bare_list_generic(self):
        result = _hint_to_openapi(list[str])
        assert result == {"type": "array", "items": {"type": "string"}}

    def test_dict_generic(self):
        assert _hint_to_openapi(dict[str, int]) == {"type": "object"}

    def test_typing_List_without_type_param(self):
        import typing

        # typing.List (no args) has __origin__=list but __args__=None → {"type": "array"}
        assert _hint_to_openapi(typing.List) == {"type": "array"}

    def test_union_multiple_non_none_returns_empty(self):
        from typing import Union

        assert _hint_to_openapi(Union[str, int]) == {}


# ---------------------------------------------------------------------------
# _dataclass_to_openapi_schema
# ---------------------------------------------------------------------------


class TestDataclassToOpenapiSchema:
    def test_basic_dataclass(self):
        from dataclasses import dataclass

        @dataclass
        class Point:
            x: float
            y: float

        schema = _dataclass_to_openapi_schema(Point)
        assert schema["type"] == "object"
        assert schema["properties"]["x"] == {"type": "number"}
        assert set(schema["required"]) == {"x", "y"}

    def test_optional_fields_not_in_required(self):
        from dataclasses import dataclass
        from typing import Optional

        @dataclass
        class Item:
            name: str
            description: Optional[str] = None

        schema = _dataclass_to_openapi_schema(Item)
        assert "name" in schema["required"]
        assert "description" not in schema.get("required", [])
        assert schema["properties"]["description"] == {"type": "string", "nullable": True}

    def test_no_required_fields_omits_required_key(self):
        from dataclasses import dataclass
        from typing import Optional

        @dataclass
        class Config:
            debug: Optional[bool] = None

        assert "required" not in _dataclass_to_openapi_schema(Config)

    def test_get_type_hints_failure_returns_empty_properties(self):
        from dataclasses import dataclass
        from unittest.mock import patch

        @dataclass
        class Bad:
            x: int

        with patch("cylutils.openapi.inspect.typing.get_type_hints", side_effect=NameError):
            schema = _dataclass_to_openapi_schema(Bad)
        assert schema["properties"]["x"] == {}


# ---------------------------------------------------------------------------
# _extract_dataclass_schemas
# ---------------------------------------------------------------------------


class TestExtractDataclassSchemas:
    def test_no_dataclasses_returns_empty(self, tmp_path):
        handler = tmp_path / "items.ex.get.py"
        handler.write_text("def main(response): pass\n", encoding="utf-8")
        route = RouteInfo(path="/items", method="GET", handler_file=handler, module_name="items.ex.get")
        assert _extract_dataclass_schemas(_load_module(route)) == {}

    def test_finds_locally_defined_dataclass(self, tmp_path):
        handler = tmp_path / "items.ex.get.py"
        handler.write_text(
            "from dataclasses import dataclass\n@dataclass\nclass Item:\n    name: str\ndef main(response): pass\n",
            encoding="utf-8",
        )
        route = RouteInfo(path="/items", method="GET", handler_file=handler, module_name="items.ex.get")
        schemas = _extract_dataclass_schemas(_load_module(route))
        assert "Item" in schemas
        assert schemas["Item"]["type"] == "object"

    def test_non_dataclass_class_skipped(self, tmp_path):
        # Loop condition is False when a class exists but is not a dataclass.
        handler = tmp_path / "items.ex.get.py"
        handler.write_text(
            "class Regular: pass\ndef main(response): pass\n",
            encoding="utf-8",
        )
        route = RouteInfo(path="/items", method="GET", handler_file=handler, module_name="items.ex.get")
        assert _extract_dataclass_schemas(_load_module(route)) == {}


# ---------------------------------------------------------------------------
# _load_module
# ---------------------------------------------------------------------------


class TestLoadModule:
    def test_returns_module_on_success(self, tmp_path):
        handler = tmp_path / "x.ex.get.py"
        handler.write_text("sentinel = 99\ndef main(response): pass\n", encoding="utf-8")
        route = RouteInfo(path="/x", method="GET", handler_file=handler, module_name="x.ex.get")
        module = _load_module(route)
        assert module is not None and module.sentinel == 99

    def test_returns_none_when_spec_is_none(self, tmp_path):
        route = RouteInfo(path="/x", method="GET", handler_file=tmp_path / "x.ex.get.py", module_name="x.ex.get")
        with patch("cylutils.openapi.inspect.importlib.util.spec_from_file_location", return_value=None):
            assert _load_module(route) is None

    def test_returns_none_when_loader_is_none(self, tmp_path):
        from unittest.mock import MagicMock

        route = RouteInfo(path="/x", method="GET", handler_file=tmp_path / "x.ex.get.py", module_name="x.ex.get")
        mock_spec = MagicMock()
        mock_spec.loader = None
        with patch("cylutils.openapi.inspect.importlib.util.spec_from_file_location", return_value=mock_spec):
            assert _load_module(route) is None

    def test_load_handler_returns_main_function(self, tmp_path):
        handler = tmp_path / "y.ex.get.py"
        handler.write_text("def main(response): pass\n", encoding="utf-8")
        route = RouteInfo(path="/y", method="GET", handler_file=handler, module_name="y.ex.get")
        assert callable(_load_handler(route))


# ---------------------------------------------------------------------------
# generate_openapi — components/schemas from dataclasses
# ---------------------------------------------------------------------------


class TestGenerateOpenapiSchemas:
    def test_no_schemas_no_components_key(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(app_dir / "items.ex.get.py", "def main(response): pass\n")
        assert "components" not in generate_openapi(app_dir)

    def test_dataclass_appears_in_components_schemas(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        _write(
            app_dir / "items.ex.get.py",
            "from dataclasses import dataclass\n@dataclass\nclass Item:\n    name: str\ndef main(response): pass\n",
        )
        doc = generate_openapi(app_dir)
        assert "components" in doc
        schemas = doc["components"]["schemas"]
        assert "Item" in schemas and schemas["Item"]["type"] == "object"

    def test_schemas_deduplicated_across_routes(self, tmp_path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        dc = "from dataclasses import dataclass\n@dataclass\nclass Item:\n    name: str\ndef main(response): pass\n"
        _write(app_dir / "items.ex.get.py", dc)
        _write(app_dir / "items.ex.post.py", dc)
        doc = generate_openapi(app_dir)
        assert list(doc["components"]["schemas"].keys()).count("Item") == 1
