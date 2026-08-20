import os
import sys
from typing import Any, Callable

import click
import questionary

from .features import ADDONS, STORE_TYPES, TEMPLATE_ENGINES
from .project import scaffold


def _ask(value: Any, question_fn: Callable[[], Any]) -> Any:
    """Return value if already provided, otherwise prompt with question_fn.
    Exits if the user cancels (questionary returns None).
    """
    if value is not None:
        return value
    result = question_fn()
    if result is None:
        sys.exit(0)
    return result


@click.group()
def cli():
    pass


@cli.command()
@click.argument("project-name", required=False)
@click.argument("app-name", required=False)
@click.option("--store-type", type=click.Choice(list(STORE_TYPES)), required=False)
@click.option("--template-engine", type=click.Choice(list(TEMPLATE_ENGINES)))
@click.option("--add-sessions", is_flag=True, required=False, default=None)
@click.option("--add-g", is_flag=True, required=False, default=None)
def start_project(project_name, app_name, store_type, template_engine, add_sessions, add_g):
    click.echo("⚡CYLINDER QUICKSTART⚡")

    project_name = _ask(
        project_name, lambda: questionary.text("Project name:", default="my-project").ask()
    )
    if os.path.exists(project_name):
        print(f"Error: Directory '{project_name}' already exists.", file=sys.stderr)
        sys.exit(1)

    app_name = _ask(app_name, lambda: questionary.text("App name:", default="my-app").ask())
    store_type = _ask(
        store_type, lambda: questionary.select("Select a store type:", choices=list(STORE_TYPES)).ask()
    )
    template_engine = _ask(
        template_engine,
        lambda: questionary.select("Select a template engine:", choices=list(TEMPLATE_ENGINES)).ask(),
    )
    add_g = _ask(
        add_g,
        lambda: questionary.confirm("Would you like to include a global context variable (g)?").ask(),
    )
    add_sessions = _ask(
        add_sessions, lambda: questionary.confirm("Would you like to include sessions?").ask()
    )

    selected_features = []

    if feature := STORE_TYPES.get(store_type):
        selected_features.append(feature)

    if feature := TEMPLATE_ENGINES.get(template_engine):
        selected_features.append(feature)

    if add_g:
        selected_features.append(ADDONS["g"])

    if add_sessions:
        selected_features.append(ADDONS["sessions"])

    scaffold(project_name, app_name, selected_features)
    click.echo("✅ Done!")


@cli.group()
def openapi():
    """Generate and scaffold from OpenAPI specifications."""
    pass


@openapi.command("export")
@click.argument("app-path", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Write to file instead of stdout.")
@click.option("--title", default="Cylinder App", show_default=True, help="API title.")
@click.option("--api-version", default="1.0.0", show_default=True, help="API version.")
def openapi_export(app_path, output, title, api_version):
    """Export a Cylinder app's routes as an OpenAPI 3.0 YAML document."""
    import yaml

    from .openapi.export import generate_openapi

    doc = generate_openapi(app_path, title=title, version=api_version)
    result = yaml.dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False)

    if output:
        import pathlib

        pathlib.Path(output).write_text(result, encoding="utf-8")
        click.echo(f"Written to {output}")
    else:
        click.echo(result, nl=False)


@openapi.command("scaffold")
@click.argument("spec-file", type=click.Path(exists=True))
@click.argument("output-dir", type=click.Path())
@click.option("--overwrite", is_flag=True, default=False, help="Overwrite existing files.")
def openapi_scaffold(spec_file, output_dir, overwrite):
    """Scaffold Cylinder handler files from an OpenAPI spec."""
    from .openapi.scaffold import scaffold_from_openapi

    created = scaffold_from_openapi(spec_file, output_dir, overwrite=overwrite)
    for f in created:
        click.echo(f"Created: {f}")
    if not created:
        click.echo("No files created.")


if __name__ == "__main__":
    cli()
