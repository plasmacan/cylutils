import argparse
import os
import pathlib
import sys
from typing import Any, Callable

import questionary

from .features import ADDONS, STORE_TYPES, TEMPLATE_ENGINES
from .project import scaffold

OPENAPI_HELP = "Generate and scaffold from OpenAPI specifications."


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


def _existing_path(value: str) -> str:
    """argparse type for a path that must already exist."""
    if not os.path.exists(value):
        raise argparse.ArgumentTypeError(f"path '{value}' does not exist")
    return value


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def start_project(args: argparse.Namespace) -> None:
    """Scaffold a new Cylinder project, prompting for anything not given."""
    print("⚡CYLINDER QUICKSTART⚡", flush=True)  # before any prompt or stderr error

    project_name = _ask(
        args.project_name, lambda: questionary.text("Project name:", default="my-project").ask()
    )
    if os.path.exists(project_name):
        print(f"Error: Directory '{project_name}' already exists.", file=sys.stderr)
        sys.exit(1)

    app_name = _ask(args.app_name, lambda: questionary.text("App name:", default="my-app").ask())
    store_type = _ask(
        args.store_type,
        lambda: questionary.select("Select a store type:", choices=list(STORE_TYPES)).ask(),
    )
    template_engine = _ask(
        args.template_engine,
        lambda: questionary.select("Select a template engine:", choices=list(TEMPLATE_ENGINES)).ask(),
    )
    add_g = _ask(
        args.add_g,
        lambda: questionary.confirm("Would you like to include a global context variable (g)?").ask(),
    )
    add_sessions = _ask(
        args.add_sessions, lambda: questionary.confirm("Would you like to include sessions?").ask()
    )
    add_http = _ask(
        args.add_http,
        lambda: questionary.confirm("Would you like to include a shared HTTP client (urllib3)?").ask(),
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

    if add_http:
        selected_features.append(ADDONS["http"])

    scaffold(project_name, app_name, selected_features)
    print("✅ Done!")


def openapi_export(args: argparse.Namespace) -> None:
    """Export a Cylinder app's routes as an OpenAPI 3.0 YAML document."""
    import yaml

    from .openapi.export import generate_openapi

    ref_spec = None
    if args.reference:
        ref_spec = yaml.safe_load(pathlib.Path(args.reference).read_text(encoding="utf-8"))

    doc = generate_openapi(args.app_path, title=args.title, version=args.api_version, reference=ref_spec)
    result = yaml.dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False)

    if args.output:
        pathlib.Path(args.output).write_text(result, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        sys.stdout.write(result)


def openapi_scaffold(args: argparse.Namespace) -> None:
    """Scaffold Cylinder handler files from an OpenAPI spec."""
    from .openapi.scaffold import scaffold_from_openapi

    created = scaffold_from_openapi(args.spec_file, args.output_dir, overwrite=args.overwrite)
    for f in created:
        print(f"Created: {f}")
    if not created:
        print("No files created.")


def openapi_ui(args: argparse.Namespace) -> None:
    """Generate a static OpenAPI UI with Swagger UI cdn + spec file."""
    # Not implemented yet.


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _add_command(
    commands: "argparse._SubParsersAction[argparse.ArgumentParser]",
    name: str,
    handler: Callable[[argparse.Namespace], None],
) -> argparse.ArgumentParser:
    """Add a subcommand whose help and description come from the handler's docstring."""
    help_text = (handler.__doc__ or "").strip()
    command = commands.add_parser(name, help=help_text, description=help_text)
    command.set_defaults(handler=handler)
    return command


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cylutils", description="Utilities for plasmacan/cylinder applications."
    )
    parser.set_defaults(parser=parser)
    commands = parser.add_subparsers(title="commands", metavar="COMMAND")

    start = _add_command(commands, "start-project", start_project)
    start.epilog = "Anything not given on the command line is asked for interactively."
    start.add_argument("project_name", nargs="?", metavar="PROJECT_NAME")
    start.add_argument("app_name", nargs="?", metavar="APP_NAME")
    start.add_argument("--store-type", choices=list(STORE_TYPES))
    start.add_argument("--template-engine", choices=list(TEMPLATE_ENGINES))
    # default=None (not False) so an omitted flag means "ask", not "no".
    start.add_argument(
        "--add-sessions", action="store_true", default=None, help="Include cookie sessions."
    )
    start.add_argument(
        "--add-g", action="store_true", default=None, help="Include a per-request g namespace."
    )
    start.add_argument(
        "--add-http",
        action="store_true",
        default=None,
        help="Include a shared HTTP client (urllib3).",
    )

    openapi = commands.add_parser("openapi", help=OPENAPI_HELP, description=OPENAPI_HELP)
    openapi.set_defaults(parser=openapi)
    openapi_commands = openapi.add_subparsers(title="commands", metavar="COMMAND")

    export = _add_command(openapi_commands, "export", openapi_export)
    export.add_argument("app_path", type=_existing_path, metavar="APP_PATH")
    export.add_argument("-o", "--output", help="Write to file instead of stdout.")
    export.add_argument("--title", default="Cylinder App", help="API title. (default: %(default)s)")
    export.add_argument("--api-version", default="1.0.0", help="API version. (default: %(default)s)")
    export.add_argument(
        "--ref",
        dest="reference",
        type=_existing_path,
        metavar="PATH",
        help="Reference spec to source info, servers, and security from.",
    )

    scaffold_cmd = _add_command(openapi_commands, "scaffold", openapi_scaffold)
    scaffold_cmd.add_argument("spec_file", type=_existing_path, metavar="SPEC_FILE")
    scaffold_cmd.add_argument("output_dir", metavar="OUTPUT_DIR")
    scaffold_cmd.add_argument("--overwrite", action="store_true", help="Overwrite existing files.")

    ui = _add_command(openapi_commands, "ui", openapi_ui)
    ui.add_argument("spec_file", type=_existing_path, metavar="SPEC_FILE")
    ui.add_argument("target_dir", metavar="TARGET_DIR")

    return parser


def cli(argv: list[str] | None = None) -> None:
    """Run the cylutils command line (argv defaults to sys.argv[1:])."""
    args = build_parser().parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        # A command group was given without a subcommand: show its help, as a usage error.
        args.parser.print_help(sys.stderr)
        sys.exit(2)
    handler(args)


if __name__ == "__main__":
    cli()
