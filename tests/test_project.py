import pathlib

import pytest

from cylutils.feature import Feature
from cylutils.features import ADD_G, ADDONS, JINJA2, SESSIONS, SIMPLE_STORE
from cylutils.project import _unique_ordered, scaffold


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

    def test_template_file_copied(self, project_dir):
        scaffold("proj", "myapp", [JINJA2])
        assert (project_dir / "proj" / "templates" / "jinja2-example.html").is_file()

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
        scaffold("proj", "myapp", [SIMPLE_STORE, JINJA2, ADD_G, SESSIONS])
        content = _read(project_dir / "proj" / "server.py")
        assert "simple_store" in content
        assert "jinja2" in content
        assert "SimpleNamespace" in content
        assert "secrets" in content
        assert (project_dir / "proj" / "apps" / "myapp" / "storeexample.ex.get.py").is_file()
        assert (project_dir / "proj" / "apps" / "myapp" / "jinja2-example.ex.get.py").is_file()
