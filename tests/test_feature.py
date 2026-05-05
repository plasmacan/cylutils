import pathlib

from cylutils.feature import Feature


def test_feature_defaults():
    f = Feature()
    assert f.imports == []
    assert f.init_code == []
    assert f.params == []
    assert f.app_map_params == []
    assert f.app_map_code == []
    assert f.generated_links == []
    assert f.extra_files == []


def test_feature_custom_values():
    src = pathlib.Path("/some/file.py")
    f = Feature(
        imports=["import foo"],
        init_code=["x = foo.Bar()"],
        params=['"foo": x'],
        app_map_params=["request"],
        app_map_code=["    result = do_something(request)"],
        generated_links=['<a href="/foo">Foo</a>'],
        extra_files=[(src, "apps/{app_name}/foo.py")],
    )
    assert f.imports == ["import foo"]
    assert f.init_code == ["x = foo.Bar()"]
    assert f.params == ['"foo": x']
    assert f.app_map_params == ["request"]
    assert f.app_map_code == ["    result = do_something(request)"]
    assert f.generated_links == ['<a href="/foo">Foo</a>']
    assert f.extra_files == [(src, "apps/{app_name}/foo.py")]


def test_feature_instances_are_independent():
    a = Feature(imports=["import a"])
    b = Feature(imports=["import b"])
    assert a.imports != b.imports
