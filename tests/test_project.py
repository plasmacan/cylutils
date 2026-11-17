import importlib.util
import itertools
import pathlib
import subprocess
import sys

import pytest

from cylutils.feature import Feature
from cylutils.features import ADD_G, ADD_HTTP, ADDONS, JINJA2, SESSIONS, SIMPLE_STORE
from cylutils.project import _fill_placeholders, _join_blocks, _unique_ordered, scaffold
from cylutils.tidy import tidy_python

ALL_FEATURES = {
    "store": SIMPLE_STORE,
    "jinja2": JINJA2,
    "g": ADD_G,
    "sessions": SESSIONS,
    "http": ADD_HTTP,
}
FEATURE_COMBOS = [
    combo
    for n in range(len(ALL_FEATURES) + 1)
    for combo in itertools.combinations(ALL_FEATURES, n)
]


# ---------------------------------------------------------------------------
# _unique_ordered
# ---------------------------------------------------------------------------


class TestUniqueOrdered:
    def test_empty_list(self):
        assert _unique_ordered([]) == []

    def test_no_duplicates(self):
        assert _unique_ordered(["a", "b", "c"]) == ["a", "b", "c"]

    def test_removes_duplicates_preserving_order(self):
        assert _unique_ordered(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]

    def test_single_item(self):
        assert _unique_ordered(["x"]) == ["x"]


# ---------------------------------------------------------------------------
# _join_blocks / _fill_placeholders
# ---------------------------------------------------------------------------


class TestJoinBlocks:
    def test_dedents_and_separates_blocks(self):
        blocks = ["\n    a = 1\n    b = 2\n", "c = 3", "\n\n        d = 4"]
        assert _join_blocks(blocks) == "a = 1\nb = 2\n\nc = 3\n\nd = 4"

    def test_empty(self):
        assert _join_blocks([]) == ""


class TestFillPlaceholders:
    def test_whole_line_placeholder_takes_line_indentation(self):
        text = "def f():\n    # BODY #\n    return x\n"
        result = _fill_placeholders(text, {"# BODY #": "x = 1\n\ny = 2"})
        assert result == "def f():\n    x = 1\n\n    y = 2\n    return x\n"

    def test_empty_whole_line_placeholder_removes_line(self):
        text = "a\n    # BODY #\nb\n"
        assert _fill_placeholders(text, {"# BODY #": ""}) == "a\nb\n"

    def test_inline_placeholder_replaced_in_place(self):
        text = 'return "apps", "# NAME #", params\n'
        assert _fill_placeholders(text, {"# NAME #": "myapp"}) == 'return "apps", "myapp", params\n'

    def test_placeholders_inside_inserted_values_are_replaced(self):
        text = "    # BODY #\n"
        replacements = {"# BODY #": 'f("# NAME #")', "# NAME #": "myapp"}
        assert _fill_placeholders(text, replacements) == '    f("myapp")\n'


# ---------------------------------------------------------------------------
# scaffold
# ---------------------------------------------------------------------------


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """Change CWD to tmp_path so scaffold creates the project there."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


class TestScaffoldNoFeatures:
    def test_creates_project_directory(self, project_dir):
        scaffold("proj", "myapp", [])
        assert (project_dir / "proj").is_dir()

    def test_server_py_exists(self, project_dir):
        scaffold("proj", "myapp", [])
        assert (project_dir / "proj" / "server.py").is_file()

    def test_appname_placeholder_replaced_in_server(self, project_dir):
        scaffold("proj", "myapp", [])
        content = _read(project_dir / "proj" / "server.py")
        assert "# APPNAME #" not in content
        assert "myapp" in content

    def test_import_placeholder_replaced(self, project_dir):
        scaffold("proj", "myapp", [])
        content = _read(project_dir / "proj" / "server.py")
        assert "# IMPORTDEF #" not in content

    def test_params_is_empty_dict(self, project_dir):
        scaffold("proj", "myapp", [])
        content = _read(project_dir / "proj" / "server.py")
        assert "params = {}" in content

    def test_appname_files_renamed(self, project_dir):
        scaffold("proj", "myapp", [])
        apps = project_dir / "proj" / "apps"
        assert (apps / "myapp.500.py").is_file()
        assert (apps / "myapp.ex.get.py").is_file()
        assert (apps / "myapp.eh.get.py").is_file()
        assert (apps / "myapp.lh.get.py").is_file()

    def test_appname_directory_renamed(self, project_dir):
        scaffold("proj", "myapp", [])
        assert (project_dir / "proj" / "apps" / "myapp").is_dir()

    def test_nested_app_files_exist(self, project_dir):
        scaffold("proj", "myapp", [])
        api = project_dir / "proj" / "apps" / "myapp" / "api" / "v1"
        assert (api / "foo.ex.get.py").is_file()
        assert (api / "foo.ex.post.py").is_file()

    def test_no_storeexample_without_simple_store(self, project_dir):
        scaffold("proj", "myapp", [])
        storeexample = project_dir / "proj" / "apps" / "myapp" / "storeexample.ex.get.py"
        assert not storeexample.exists()


class TestScaffoldSimpleStore:
    def test_storeexample_copied(self, project_dir):
        scaffold("proj", "myapp", [SIMPLE_STORE])
        assert (project_dir / "proj" / "apps" / "myapp" / "storeexample.ex.get.py").is_file()

    def test_server_contains_store_import(self, project_dir):
        scaffold("proj", "myapp", [SIMPLE_STORE])
        content = _read(project_dir / "proj" / "server.py")
        assert "from cylutils import simple_store" in content

    def test_server_contains_store_init(self, project_dir):
        scaffold("proj", "myapp", [SIMPLE_STORE])
        content = _read(project_dir / "proj" / "server.py")
        assert "s = simple_store.Store()" in content

    def test_server_contains_store_param(self, project_dir):
        scaffold("proj", "myapp", [SIMPLE_STORE])
        content = _read(project_dir / "proj" / "server.py")
        assert '"store": s' in content


class TestScaffoldJinja2:
    def test_handler_file_copied(self, project_dir):
        scaffold("proj", "myapp", [JINJA2])
        assert (project_dir / "proj" / "apps" / "myapp" / "jinja2-example.ex.get.py").is_file()

    def test_template_file_copied_to_app_folder(self, project_dir):
        scaffold("proj", "myapp", [JINJA2])
        assert (project_dir / "proj" / "templates" / "myapp" / "jinja2-example.html").is_file()
        assert not (project_dir / "proj" / "templates" / "jinja2-example.html").exists()

    def test_render_template_factory_gets_app_name(self, project_dir):
        scaffold("proj", "myapp", [JINJA2])
        content = _read(project_dir / "proj" / "server.py")
        assert '"render_template": render_template_factory("myapp")' in content
        assert "# APPNAME #" not in content

    def test_server_imports_urllib_parse(self, project_dir):
        scaffold("proj", "myapp", [JINJA2])
        content = _read(project_dir / "proj" / "server.py")
        assert "import urllib.parse" in content.splitlines()

    def test_server_contains_jinja2_import(self, project_dir):
        scaffold("proj", "myapp", [JINJA2])
        content = _read(project_dir / "proj" / "server.py")
        assert "import jinja2" in content

    def test_server_contains_render_template_param(self, project_dir):
        scaffold("proj", "myapp", [JINJA2])
        content = _read(project_dir / "proj" / "server.py")
        assert "render_template" in content

    def test_generated_link_in_landing_page(self, project_dir):
        scaffold("proj", "myapp", [JINJA2])
        content = _read(project_dir / "proj" / "templates" / "example.html")
        assert "jinja2-example" in content


class TestScaffoldAddG:
    def test_server_contains_simple_namespace_import(self, project_dir):
        scaffold("proj", "myapp", [ADD_G])
        content = _read(project_dir / "proj" / "server.py")
        assert "SimpleNamespace" in content

    def test_server_contains_g_param(self, project_dir):
        scaffold("proj", "myapp", [ADD_G])
        content = _read(project_dir / "proj" / "server.py")
        assert '"g"' in content


class TestScaffoldAddHttp:
    def test_server_contains_urllib3_import(self, project_dir):
        scaffold("proj", "myapp", [ADD_HTTP])
        content = _read(project_dir / "proj" / "server.py")
        assert "import urllib3" in content

    def test_server_creates_pool_manager_once(self, project_dir):
        scaffold("proj", "myapp", [ADD_HTTP])
        content = _read(project_dir / "proj" / "server.py")
        assert content.count("urllib3.PoolManager(") == 1

    def test_server_contains_http_param(self, project_dir):
        scaffold("proj", "myapp", [ADD_HTTP])
        content = _read(project_dir / "proj" / "server.py")
        assert '"http": http' in content


class TestScaffoldSessions:
    def test_server_contains_secrets_import(self, project_dir):
        scaffold("proj", "myapp", [SESSIONS])
        content = _read(project_dir / "proj" / "server.py")
        assert "import secrets" in content

    def test_server_contains_session_dict_class(self, project_dir):
        scaffold("proj", "myapp", [SESSIONS])
        content = _read(project_dir / "proj" / "server.py")
        assert "SessionDict" in content

    def test_server_contains_session_param(self, project_dir):
        scaffold("proj", "myapp", [SESSIONS])
        content = _read(project_dir / "proj" / "server.py")
        assert '"session"' in content


class TestScaffoldDeduplication:
    def test_duplicate_imports_are_deduplicated(self, project_dir):
        dup_feature = Feature(imports=["import foo", "import foo"])
        scaffold("proj", "myapp", [dup_feature])
        content = _read(project_dir / "proj" / "server.py")
        assert content.count("import foo") == 1

    def test_same_import_across_two_features(self, project_dir):
        f1 = Feature(imports=["import shared"])
        f2 = Feature(imports=["import shared", "import other"])
        scaffold("proj", "myapp", [f1, f2])
        content = _read(project_dir / "proj" / "server.py")
        assert content.count("import shared") == 1
        assert "import other" in content


class TestScaffoldAllFeatures:
    def test_all_features_together(self, project_dir):
        scaffold("proj", "myapp", [SIMPLE_STORE, JINJA2, ADD_G, SESSIONS, ADD_HTTP])
        content = _read(project_dir / "proj" / "server.py")
        assert "simple_store" in content
        assert "jinja2" in content
        assert "SimpleNamespace" in content
        assert "secrets" in content
        assert "urllib3" in content
        assert (project_dir / "proj" / "apps" / "myapp" / "storeexample.ex.get.py").is_file()
        assert (project_dir / "proj" / "apps" / "myapp" / "jinja2-example.ex.get.py").is_file()

    def test_generated_server_is_valid_python(self, project_dir):
        scaffold("proj", "myapp", [SIMPLE_STORE, JINJA2, ADD_G, SESSIONS, ADD_HTTP])
        content = _read(project_dir / "proj" / "server.py")
        compile(content, "server.py", "exec")


# ---------------------------------------------------------------------------
# Generated code quality, across every feature combination
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def all_combo_projects(tmp_path_factory):
    """Scaffold one project per feature combination; return (root, python files)."""
    root = tmp_path_factory.mktemp("combos")
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(root)
        for combo in FEATURE_COMBOS:
            scaffold("p_" + ("_".join(combo) or "none"), "app", [ALL_FEATURES[c] for c in combo])
    return root, sorted(root.glob("p_*/**/*.py"))


class TestGeneratedCodeQuality:
    def test_every_combination_compiles(self, all_combo_projects):
        _, files = all_combo_projects
        assert sum(f.name == "server.py" for f in files) == len(FEATURE_COMBOS)
        for f in files:
            compile(_read(f), str(f), "exec")

    def test_every_generated_file_is_already_tidy(self, all_combo_projects):
        _, files = all_combo_projects
        untidy = [str(f) for f in files if tidy_python(_read(f)) != _read(f)]
        assert untidy == []

    # ruff runs from the combos root (as a user would from their project) so cylutils is
    # classified as third-party, and is given the directory to stay under Windows' argv limit.
    @pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="ruff not installed")
    def test_ruff_check_passes(self, all_combo_projects):
        root, files = all_combo_projects
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--isolated", "--no-cache", "--preview",
             "--select", "E,W,F,I", "--output-format", "concise", "."],
            cwd=root, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    @pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="ruff not installed")
    def test_ruff_format_check_passes(self, all_combo_projects):
        root, files = all_combo_projects
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "format", "--isolated", "--no-cache", "--check", "."],
            cwd=root, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"{len(files)} files already formatted" in result.stdout

    def test_generated_link_keeps_landing_page_indentation(self, all_combo_projects):
        root, _ = all_combo_projects
        html = _read(root / "p_jinja2" / "templates" / "example.html")
        api_link = next(line for line in html.splitlines() if "api/v1/foo" in line)
        jinja_link = next(line for line in html.splitlines() if "jinja2-example" in line)
        indent = len(api_link) - len(api_link.lstrip())
        assert len(jinja_link) - len(jinja_link.lstrip()) == indent
        assert "GENERATED LINKS" not in _read(root / "p_none" / "templates" / "example.html")
