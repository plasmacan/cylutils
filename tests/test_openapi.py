"""Tests for cylutils.openapi — models, inspect, export, scaffold, and CLI."""
from __future__ import annotations

import pathlib
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
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

    def test_creates_sidecar_file(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: Test, version: "1.0"}
            paths:
              /items:
                post:
                  summary: Create item
                  responses:
                    "201": {description: Created}
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        assert (out / "items.ex.post.openapi.yaml").exists()

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

    def test_sidecar_excludes_operation_id(self, tmp_path):
        spec = self._spec(
            tmp_path,
            """\
            openapi: "3.0.3"
            info: {title: T, version: "1.0"}
            paths:
              /items:
                get:
                  operationId: items_get
                  summary: List items
                  responses:
                    "200": {description: OK}
            """,
        )
        out = tmp_path / "out"
        scaffold_from_openapi(spec, out)
        sidecar = yaml.safe_load((out / "items.ex.get.openapi.yaml").read_text(encoding="utf-8"))
        assert "operationId" not in sidecar
        assert sidecar.get("summary") == "List items"

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
        # 2 routes × (handler + sidecar) = 4 files
        assert len(created) == 4


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

    def test_no_summary_no_description_uses_no_doc_template(self, tmp_path):
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
        # No docstring in the no-doc template
        assert '"""' not in content

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
