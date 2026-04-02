import os
import pathlib
import shutil
import sys

import click
import questionary

MODULE_ROOT = pathlib.Path(__file__).resolve().parent / "resources"
QUICKSTART_DIR = MODULE_ROOT / "quickstart"
EXAMPLES_DIR = MODULE_ROOT / "examples"


@click.group()
def cli():
    pass


@cli.command()
@click.argument("project-name", required=False)
@click.argument("app-name", required=False)
@click.option("--store-type", type=click.Choice(["simple_store", "g_object", "none"]), required=False)
@click.option("--template-engine", type=click.Choice(["jinja2", "none"]))
def start_project(project_name, app_name, store_type, template_engine):
    click.echo("⚡CYLINDER QUICKSTART⚡")

    if project_name is None:
        project_name = questionary.text("Project name:", default="my-project").ask()
    if project_name is None:
        sys.exit(0)

    if app_name is None:
        app_name = questionary.text("App name:", default="my-app").ask()
    if app_name is None:
        sys.exit(0)

    if store_type is None:
        store_type = questionary.select("Select a store type:", choices=["simple_store", "none"]).ask()
    if store_type is None:
        sys.exit(0)

    if template_engine is None:
        template_engine = questionary.select("Select a template engine:", choices=["jinja2", "none"]).ask()
    if template_engine is None:
        sys.exit(0)

    import_list = []
    init_list = []
    params_list = []

    match store_type:
        case "simple_store":
            import_list.append("from cylutils import simple_store")
            init_list.append("s = simple_store.Store()")
            params_list.append('"store": s')

        case "g_object":
            import_list.append("from types import SimpleNamespace")
            params_list.append('"g": SimpleNamespace()')

    match template_engine:
        case "jinja2":
            import_list.append("import jinja2")
            init_list.append("""
jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader("templates"),
    auto_reload=True,
    autoescape=jinja2.select_autoescape(),
)


def render_template(template_name, **context):
    template = jinja_env.get_template(template_name)
    return template.render(**context)


def url_for(endpoint, **query_params):
    path = "/" + endpoint.strip("/")

    if query_params:
        qs = urllib.parse.urlencode(query_params)
        path = f"{path}?{qs}"

    return path


jinja_env.globals["url_for"] = url_for
""")
            params_list.append('"render_template": render_template')

    imports = "\n".join(import_list)
    inits = "\n".join(init_list)
    params = "{\n" + ",\n".join(params_list) + "\n}"

    replacements = {
        "# APPNAME #": app_name,
        "# IMPORTDEF #": imports,
        "# INITDEF #": inits,
        "# PARAMSDEF #": "params = " + params,
    }

    target_dir = pathlib.Path.cwd() / project_name

    # copy base template
    shutil.copytree(
        src=QUICKSTART_DIR,
        dst=target_dir,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    # replace placeholders in all files and rename app dir and files

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

        if "APPNAME" in str(fp).upper():
            new_name = fp.name.replace("APPNAME", app_name).replace("appname", app_name)
            new_fp = fp.parent / new_name
            fp.rename(new_fp)

    for dp in dirpaths:
        if "APPNAME" in str(dp).upper():
            new_name = dp.name.replace("APPNAME", app_name).replace("appname", app_name)
            new_fp = dp.parent / new_name
            dp.rename(new_fp)

    # add selected example templates

    if template_engine == "jinja2":
        sample_path = EXAMPLES_DIR / "jinja2"
        py_path = sample_path / "jinja2-example.ex.get.py"
        template_path = sample_path / "jinja2-example.html"

        os.mkdir(target_dir / "templates")
        shutil.copy(py_path, target_dir / "apps" / app_name / "jinja2-example.ex.get.py")
        shutil.copy(template_path, target_dir / "templates" / "jinja2-example.html")

    click.echo("✅ Done!")


if __name__ == "__main__":
    cli()
