"""Stdlib-only tidying for generated Python source.

Sorts the module's leading imports the way isort/ruff do, and normalizes blank lines and
trailing whitespace the way black/ruff format do. Unlike ast.unparse, it keeps comments,
string contents and the code's own layout.
"""

from __future__ import annotations

import ast
import io
import sys
import tokenize
from dataclasses import dataclass

LINE_LENGTH = 88


def tidy_python(source: str) -> str:
    """Return source with sorted imports, normalized blank lines and no trailing whitespace.

    Source that doesn't parse is returned unchanged.
    """
    return normalize_blank_lines(sort_imports(source))


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


def sort_imports(source: str) -> str:
    """Sort and group the import statements at the top of a module, isort style.

    Sections (__future__, stdlib, third-party, relative) are separated by a blank line.
    Within a section, `import x` lines come before `from x import y` lines, each sorted by
    module name, and from-imports of the same module are merged. The block is left alone
    if it holds comments or shares a line with other code.
    """
    try:
        body = ast.parse(source).body
    except SyntaxError:
        return source

    imports = []
    for node in body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            break
        imports.append(node)
    if not imports:
        return source

    lines = source.splitlines(keepends=True)
    first, last = imports[0].lineno, imports[-1].end_lineno
    rest = body[len(imports) :]
    if "#" in "".join(lines[first - 1 : last]) or (rest and rest[0].lineno <= last):
        return source

    return "".join(lines[: first - 1]) + _format_imports(imports) + "".join(lines[last:])


def _format_imports(nodes: list[ast.Import | ast.ImportFrom]) -> str:
    straight: dict[int, set[str]] = {}
    froms: dict[tuple[int, str], set[str]] = {}

    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                straight.setdefault(_section(alias.name, 0), set()).add(_alias(alias))
        else:
            module = "." * node.level + (node.module or "")
            key = (_section(node.module or "", node.level), module)
            froms.setdefault(key, set()).update(_alias(alias) for alias in node.names)

    sections = []
    for section in sorted(set(straight) | {sec for sec, _ in froms}):
        block = [f"import {name}" for name in sorted(straight.get(section, ()), key=_name_key)]
        for sec, module in sorted(froms, key=lambda k: (k[0], _name_key(k[1]))):
            if sec == section:
                block.append(_from_line(module, sorted(froms[sec, module], key=_member_key)))
        sections.append("\n".join(block))

    return "\n\n".join(sections) + "\n"


def _section(module: str, level: int) -> int:
    if level:
        return 3
    top = module.partition(".")[0]
    if top == "__future__":
        return 0
    if top in sys.stdlib_module_names:
        return 1
    return 2


def _alias(alias: ast.alias) -> str:
    return f"{alias.name} as {alias.asname}" if alias.asname else alias.name


def _name_key(name: str) -> tuple[str, str]:
    return name.lower(), name


def _member_key(name: str) -> tuple[int, str, str]:
    # isort's order-by-type: CONSTANTS, then Classes, then everything else.
    base = name.partition(" ")[0]
    if base.isupper() and len(base) > 1:
        rank = 0
    elif base[:1].isupper():
        rank = 1
    else:
        rank = 2
    return rank, base.lower(), name


def _from_line(module: str, names: list[str]) -> str:
    line = f"from {module} import {', '.join(names)}"
    if len(line) <= LINE_LENGTH:
        return line
    members = "".join(f"    {name},\n" for name in names)
    return f"from {module} import (\n{members})"


# ---------------------------------------------------------------------------
# Blank lines and trailing whitespace
# ---------------------------------------------------------------------------


@dataclass
class _Item:
    """A statement (one or more physical rows) or a comment on its own line."""

    first: int
    last: int
    indent: int
    words: list[str]
    blank_before: int = 0
    starts_with_string: bool = False

    @property
    def is_comment(self) -> bool:
        return self.words == ["#"]

    @property
    def is_function(self) -> bool:
        return self.words[:1] == ["def"] or self.words == ["async", "def"]

    @property
    def is_decorator(self) -> bool:
        return self.words[:1] == ["@"]

    @property
    def is_import(self) -> bool:
        return self.words[:1] in (["import"], ["from"])

    @property
    def is_def(self) -> bool:
        return self.words[:1] in (["def"], ["class"], ["@"]) or self.words == ["async", "def"]


def normalize_blank_lines(source: str) -> str:
    """Normalize blank lines and strip trailing whitespace, black style.

    - two blank lines around top-level functions/classes, one around nested ones
      (comments directly above a definition move with it)
    - one blank line after imports, or two if a definition follows
    - no blank lines at the start/end of the file or the start of a block, except one
      allowed at the top of a function body (not before a docstring), as ruff format does
    - otherwise existing blank lines are kept, at most two at top level and one nested
    """
    try:
        items, string_rows = _scan(source)
    except (tokenize.TokenError, SyntaxError):
        return source

    rows = source.split("\n")
    out: list[str] = []
    for i, item in enumerate(items):
        if i:
            out.extend([""] * _blank_lines_before(items, i))
        for row in range(item.first, item.last + 1):
            text = rows[row - 1]
            out.append(text if row in string_rows else text.rstrip())
    return "\n".join(out) + "\n" if out else ""


_WORDS_KEPT = 2  # enough to recognize `async def`


def _scan(source: str) -> tuple[list[_Item], set[int]]:
    items: list[_Item] = []
    string_rows: set[int] = set()  # rows whose line break sits inside a multi-line string
    current: _Item | None = None
    last_row = 0
    skip = (tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER)

    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.end[0] > tok.start[0]:
            string_rows.update(range(tok.start[0], tok.end[0]))
        if tok.type in skip or (current is None and tok.type == tokenize.NL):
            continue
        if current is None:
            if tok.type == tokenize.COMMENT:
                items.append(_Item(tok.start[0], tok.start[0], tok.start[1], ["#"]))
                items[-1].blank_before = tok.start[0] - last_row - 1
                last_row = tok.start[0]
                continue
            current = _Item(tok.start[0], tok.start[0], tok.start[1], [])
            current.blank_before = tok.start[0] - last_row - 1
            current.starts_with_string = tok.type == tokenize.STRING
        if tok.type == tokenize.NEWLINE:
            current.last = last_row = tok.start[0]
            items.append(current)
            current = None
        elif len(current.words) < _WORDS_KEPT and tok.type != tokenize.COMMENT:
            current.words.append(tok.string)

    return items, string_rows


def _blank_lines_before(items: list[_Item], i: int) -> int:
    item, prev = items[i], items[i - 1]
    top_level = item.indent == 0
    limit = 2 if top_level else 1

    # Start of a block: right after `def ...:`, `if ...:` etc. Like ruff format, allow one
    # blank line at the top of a function body, unless a docstring follows.
    next_code = next((n for n in items[i:] if not n.is_comment), None)
    if not prev.is_comment and next_code is not None and next_code.indent > prev.indent:
        if prev.is_function and not item.starts_with_string:
            return min(item.blank_before, 1)
        return 0
    if prev.is_decorator:
        return 0
    # A comment directly above a definition stays attached to it.
    if prev.is_comment and _starts_definition(items, i - 1):
        return 0
    if _starts_definition(items, i):
        return limit
    # Leaving a function/class body.
    if prev.indent > item.indent:
        code_above = (p for p in reversed(items[:i]) if not p.is_comment)
        opener = next((p for p in code_above if p.indent <= item.indent), None)
        if opener is not None and opener.indent == item.indent and opener.is_def:
            return limit
    # isort's lines-after-imports (the definition case is handled above).
    if top_level and prev.is_import and not item.is_comment and not item.is_import:
        return 1
    return min(item.blank_before, limit)


def _starts_definition(items: list[_Item], i: int) -> bool:
    """True if items[i] is a definition, or a comment run leading straight into one."""
    item = items[i]
    while item.is_comment:
        if i + 1 == len(items):
            return False
        following = items[i + 1]
        if following.blank_before or following.indent != item.indent:
            return False
        i, item = i + 1, following
    return item.is_def
