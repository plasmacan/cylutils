import pathlib
import shutil

from .feature import Feature

_MODULE_ROOT = pathlib.Path(__file__).resolve().parent / "resources"
QUICKSTART_DIR = _MODULE_ROOT / "quickstart"


def _unique_ordered(items: list[str]) -> list[str]:
    """Return items with duplicates removed, preserving first-seen order."""
    seen: set[str] = set()
    return [x for x in items if not (x in seen or seen.add(x))]


def scaffold(project_name: str, app_name: str, selected_features: list[Feature]) -> None:
    """Scaffold a new Cylinder project by merging selected feature contributions."""

    import_list: list[str] = []
    init_list: list[str] = []
    params_list: list[str] = []
    app_map_params_list: list[str] = []
    app_map_code_list: list[str] = []
    generated_links_list: list[str] = []
    extra_files: list[tuple[pathlib.Path, str]] = []

    for feature in selected_features:
        import_list.extend(feature.imports)
        init_list.extend(feature.init_code)
        params_list.extend(feature.params)
        app_map_params_list.extend(feature.app_map_params)
        app_map_code_list.extend(feature.app_map_code)
        generated_links_list.extend(feature.generated_links)
        extra_files.extend(feature.extra_files)

    import_def = "\n".join(_unique_ordered(import_list))
    init_def = "\n".join(init_list)
    app_map_params = ", ".join(_unique_ordered(app_map_params_list))
    app_map_def = "\n\n".join(app_map_code_list)
    generated_links = "\n    ".join(generated_links_list)

    if params_list:
        param_def = "{\n    " + ",\n    ".join(params_list) + ",\n}"
    else:
        param_def = "{}"

    replacements = {
        "# APPNAME #": app_name,
        "# IMPORTDEF #": import_def,
        "# INITDEF #": init_def,
        "# APPMAPPARAMS #": app_map_params,
        "# APPMAPDEF #": app_map_def,
        "# PARAMSDEF #": "params = " + param_def,
        "<!--GENERATED LINKS-->": generated_links,
    }

    target_dir = pathlib.Path.cwd() / project_name

    # Copy the base quickstart template
    shutil.copytree(
        src=QUICKSTART_DIR,
        dst=target_dir,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    # Apply placeholder replacements and rename APPNAME files
    filepaths = [f for f in target_dir.glob("**/*") if f.is_file()]
    dirpaths = [d for d in target_dir.glob("**/*") if d.is_dir()]
    dirpaths.reverse()

    for fp in filepaths:
        with fp.open("r", encoding="utf-8") as f:
            content = f.readlines()

        with fp.open("w", encoding="utf-8") as f:
            for line in content:
                newline = line
                for placeholder, value in replacements.items():
                    newline = newline.replace(placeholder, value)
                f.write(newline)

        if "APPNAME" in fp.name.upper():
            new_name = fp.name.replace("APPNAME", app_name).replace("appname", app_name)
            fp.rename(fp.parent / new_name)

    for dp in dirpaths:
        if "APPNAME" in dp.name.upper():
            new_name = dp.name.replace("APPNAME", app_name).replace("appname", app_name)
            dp.rename(dp.parent / new_name)

    # Copy feature-specific extra files
    for src_path, dst_template in extra_files:
        dst_rel = dst_template.format(app_name=app_name)
        dst_path = target_dir / dst_rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src_path, dst_path)
