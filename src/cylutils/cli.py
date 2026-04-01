import pathlib
import shutil
import sys
import sysconfig

import click
import questionary

QUICKSTART_DIR = pathlib.Path(sysconfig.get_path("data")) / "cylutils-resources" / "quickstart"


@click.group()
def cli():
    pass


@cli.command()
@click.argument("project-name", required=False)
@click.argument("app-name", required=False)
@click.option("--store-type", type=click.Choice(["simple_store", "g_object"]), required=False)
def start_project(project_name, app_name, store_type):
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

    shutil.copytree(
        src=QUICKSTART_DIR,
        dst=target_dir,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    filepaths = [f for f in target_dir.glob("**/*") if f.is_file()]
    dirpaths = [d for d in target_dir.glob("**/*") if d.is_dir()]
    for fp in filepaths:
        with fp.open("r", encoding="utf-8") as f:
            print("opening " + fp.name)
            content = f.readlines()

        with fp.open("w", encoding="utf-8") as f:
            for line in content:
                newline = line
                for placeholder, value in replacements.items():
                    newline = newline.replace(placeholder, value)
                f.write(newline)

        if "APPNAME" in str(fp):
            new_fp = fp.parent / fp.name.replace("APPNAME", app_name)
            fp.rename(new_fp)

    for dp in dirpaths:
        if "APPNAME" in str(dp):
            new_fp = dp.parent / dp.name.replace("APPNAME", app_name)
            dp.rename(new_fp)

    click.echo("✅ Done!")


if __name__ == "__main__":
    cli()
