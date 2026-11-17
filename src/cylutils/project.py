import pathlib
import shutil
import textwrap

from .feature import Feature
from .tidy import tidy_python

_MODULE_ROOT = pathlib.Path(__file__).resolve().parent / "resources"
QUICKSTART_DIR = _MODULE_ROOT / "quickstart"


def _unique_ordered(items: list[str]) -> list[str]:
    """Return items with duplicates removed, preserving first-seen order."""
    seen: set[str] = set()
    return [x for x in items if not (x in seen or seen.add(x))]


def _join_blocks(blocks: list[str]) -> str:
    """Dedent each code block and join them with a blank line between."""
    return "\n\n".join(textwrap.dedent(block).strip("\n") for block in blocks)


def _fill_placeholders(text: str, replacements: dict[str, str]) -> str:
    """Replace placeholders in text.

    A placeholder alone on its line is replaced by its value with that line's indentation
    applied to every line of the value, or removed with its line if the value is empty.
    Placeholders inside a line (or inside an inserted value) are replaced in place.
    """
    lines = []
    for line in text.splitlines(keepends=True):
        value = replacements.get(line.strip())
        if value is None:
            lines.append(line)
        elif value:
            indent = line[: len(line) - len(line.lstrip())]
            lines.append(textwrap.indent(value, indent) + "\n")

    text = "".join(lines)
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text


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

    if params_list:
        param_def = "params = {\n" + "".join(f"    {p},\n" for p in params_list) + "}"
    else:
        param_def = "params = {}"

    replacements = {
        "# IMPORTDEF #": "\n".join(_unique_ordered(import_list)),
        "# INITDEF #": _join_blocks(init_list),
        "# APPMAPPARAMS #": ", ".join(_unique_ordered(app_map_params_list)),
        "# APPMAPDEF #": _join_blocks(app_map_code_list),
        "# PARAMSDEF #": param_def,
        "<!--GENERATED LINKS-->": "\n".join(generated_links_list),
        "# APPNAME #": app_name,
    }

    target_dir = pathlib.Path.cwd() / project_name

    # Copy the base quickstart template
    shutil.copytree(
        src=QUICKSTART_DIR,
        dst=target_dir,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    # Apply placeholder replacements, tidy Python files, and rename APPNAME files
    filepaths = [f for f in target_dir.glob("**/*") if f.is_file()]
    dirpaths = [d for d in target_dir.glob("**/*") if d.is_dir()]
    dirpaths.reverse()

    for fp in filepaths:
        content = _fill_placeholders(fp.read_text(encoding="utf-8"), replacements)
        if fp.suffix == ".py":
            content = tidy_python(content)
        fp.write_text(content, encoding="utf-8")

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
