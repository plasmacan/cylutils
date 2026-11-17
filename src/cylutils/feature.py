from __future__ import annotations

import pathlib
from dataclasses import dataclass, field


@dataclass
class Feature:
    """Describes what a feature contributes to a generated project.

    To add a new feature, create a Feature instance in features.py and add it
    to the appropriate registry dict (STORE_TYPES, TEMPLATE_ENGINES, or ADDONS).
    No other files need to be modified.
    """

    # Generated Python is tidied (imports sorted and grouped, blank lines normalized),
    # so contributions only need to be valid code; ordering and spacing are handled.

    # Import statements added to server.py, e.g. "import json"
    imports: list[str] = field(default_factory=list)

    # Top-level code blocks added to server.py (any indentation; they are dedented)
    init_code: list[str] = field(default_factory=list)

    # Entries added to the params dict passed to the app, e.g. '"store": s'
    params: list[str] = field(default_factory=list)

    # Parameters added to the app_map function signature, e.g. "request"
    app_map_params: list[str] = field(default_factory=list)

    # Code blocks run inside the app_map function body before params are built
    # (any indentation; they are re-indented into the function body)
    app_map_code: list[str] = field(default_factory=list)

    # HTML anchor tags injected into the quickstart landing page
    generated_links: list[str] = field(default_factory=list)

    # Extra files to copy into the generated project.
    # Each entry is (absolute_src_path, dst_path_template).
    # Use {app_name} in the dst template to reference the app directory,
    # e.g. "apps/{app_name}/example.ex.get.py".
    extra_files: list[tuple[pathlib.Path, str]] = field(default_factory=list)
