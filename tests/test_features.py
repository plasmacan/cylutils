from cylutils.feature import Feature
from cylutils.features import ADDONS, SIMPLE_STORE, JINJA2, ADD_G, SESSIONS, STORE_TYPES, TEMPLATE_ENGINES


class TestRegistryKeys:
    def test_store_types_has_simple_store_and_none(self):
        assert set(STORE_TYPES.keys()) == {"simple_store", "none"}

    def test_template_engines_has_jinja2_and_none(self):
        assert set(TEMPLATE_ENGINES.keys()) == {"jinja2", "none"}

    def test_addons_has_g_and_sessions(self):
        assert set(ADDONS.keys()) == {"g", "sessions"}


class TestRegistryValues:
    def test_none_store_type_is_none(self):
        assert STORE_TYPES["none"] is None

    def test_none_template_engine_is_none(self):
        assert TEMPLATE_ENGINES["none"] is None

    def test_store_types_simple_store_is_feature(self):
        assert isinstance(STORE_TYPES["simple_store"], Feature)

    def test_template_engines_jinja2_is_feature(self):
        assert isinstance(TEMPLATE_ENGINES["jinja2"], Feature)

    def test_addons_g_is_feature(self):
        assert isinstance(ADDONS["g"], Feature)

    def test_addons_sessions_is_feature(self):
        assert isinstance(ADDONS["sessions"], Feature)


class TestSimpleStoreFeature:
    def test_has_import(self):
        assert any("simple_store" in imp for imp in SIMPLE_STORE.imports)

    def test_has_init_code(self):
        assert any("Store()" in line for line in SIMPLE_STORE.init_code)

    def test_has_store_param(self):
        assert any("store" in p for p in SIMPLE_STORE.params)

    def test_has_extra_file(self):
        assert len(SIMPLE_STORE.extra_files) == 1
        src, dst = SIMPLE_STORE.extra_files[0]
        assert src.exists(), f"Source file missing: {src}"
        assert "storeexample" in dst


class TestJinja2Feature:
    def test_has_jinja2_import(self):
        assert any("jinja2" in imp for imp in JINJA2.imports)

    def test_has_render_template_param(self):
        assert any("render_template" in p for p in JINJA2.params)

    def test_has_generated_link(self):
        assert len(JINJA2.generated_links) == 1

    def test_has_two_extra_files(self):
        assert len(JINJA2.extra_files) == 2
        for src, _ in JINJA2.extra_files:
            assert src.exists(), f"Source file missing: {src}"


class TestAddGFeature:
    def test_has_simple_namespace_import(self):
        assert any("SimpleNamespace" in imp for imp in ADD_G.imports)

    def test_has_g_param(self):
        assert any('"g"' in p for p in ADD_G.params)


class TestSessionsFeature:
    def test_has_secrets_import(self):
        assert any("secrets" in imp for imp in SESSIONS.imports)

    def test_has_app_map_params(self):
        assert "request" in SESSIONS.app_map_params
        assert "response" in SESSIONS.app_map_params

    def test_has_session_params(self):
        assert any("session" in p for p in SESSIONS.params)
