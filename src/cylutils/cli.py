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
@click.option("--store-type", type=click.Choice(["simple_store", "none"]), required=False)
@click.option("--template-engine", type=click.Choice(["jinja2", "none"]))
@click.option("--add-sessions", is_flag=True, required=False, default=None)
@click.option("--add-g", is_flag=True, required=False, default=None)
def start_project(project_name, app_name, store_type, template_engine, add_sessions, add_g):
    click.echo("⚡CYLINDER QUICKSTART⚡")

    if project_name is None:
        project_name = questionary.text("Project name:", default="my-project").ask()
    if project_name is None:
        sys.exit(0)
    if os.path.exists(project_name):
        print(f"Error: Directory '{project_name}' already exists.", file=sys.stderr)
        sys.exit(1)

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

    if add_g is None:
        add_g = questionary.confirm("Would you like to include a global context variable (g)?").ask()
    if add_g is None:
        sys.exit(0)

    if add_sessions is None:
        add_sessions = questionary.confirm("Would you like to include sessions?").ask()
    if add_sessions is None:
        sys.exit(0)

    import_list = []
    init_list = []
    params_list = []
    app_map_def_list = []
    app_map_params_list = []
    generated_links_list = []

    match store_type:
        case "simple_store":
            import_list.append("from cylutils import simple_store")
            init_list.append("s = simple_store.Store()")
            params_list.append('"store": s')

    match template_engine:
        case "jinja2":
            import_list.append("import jinja2")
            import_list.append("import urllib")
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
            generated_links_list.append('<a href="/jinja2-example">View Jinja2 Example</a>')

    if add_g:
        import_list.append("from types import SimpleNamespace")
        params_list.append('"g": SimpleNamespace()')

    if add_sessions:
        import_list.append("import secrets")
        import_list.append("import json")
        import_list.append("import sqlite3")
        import_list.append("from collections import UserDict")
        init_list.append("""
class SessionDict(UserDict):
    def __init__(self, uid):
        self.uid = uid
        self.conn = sqlite3.connect("sessions.sqlite")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS store (uid TEXT PRIMARY KEY, data TEXT)"
        )
        row = self.conn.execute(
            "SELECT data FROM store WHERE uid=?", (self.uid,)
        ).fetchone()
        super().__init__(json.loads(row[0]) if row else {})

    def _save(self):
        self.conn.execute(
            "INSERT OR REPLACE INTO store VALUES (?, ?)",
            (self.uid, json.dumps(self.data)),
        )
        self.conn.commit()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._save()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._save()""")
        app_map_params_list.append("request")
        app_map_params_list.append("response")
        app_map_def_list.append("""
    session_id = request.cookies.get("session_id") or secrets.token_urlsafe(32)
    response.set_cookie("session_id", session_id, httponly=True) # should also set `secure=True` in production
    session = SessionDict(session_id)
""")
        params_list.append('"session": session')
        params_list.append('"session_id": session_id')

    import_def = "\n".join(import_list)
    init_def = "\n".join(init_list)
    param_def = "{\n" + ",\n".join(params_list) + "\n}"
    app_map_def = "\n\n".join(app_map_def_list)
    app_map_params = ", ".join(app_map_params_list)
    generated_links = "\n    ".join(generated_links_list)

    replacements = {
        "# APPNAME #": app_name,
        "# IMPORTDEF #": import_def,
        "# INITDEF #": init_def,
        "# APPMAPDEF #": app_map_def,
        "# APPMAPPARAMS #": app_map_params,
        "# PARAMSDEF #": "params = " + param_def,
        "<!--GENERATED LINKS-->": generated_links,
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

        shutil.copy(py_path, target_dir / "apps" / app_name / "jinja2-example.ex.get.py")
        shutil.copy(template_path, target_dir / "templates" / "jinja2-example.html")

    click.echo("✅ Done!")


if __name__ == "__main__":
    cli()
