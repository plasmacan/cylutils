import ast
import textwrap

from cylutils.tidy import normalize_blank_lines, sort_imports, tidy_python


def src(text: str) -> str:
    """Dedent a triple-quoted snippet, dropping the leading newline."""
    return textwrap.dedent(text).lstrip("\n")


# ---------------------------------------------------------------------------
# sort_imports
# ---------------------------------------------------------------------------


class TestSortImports:
    def test_groups_and_orders_like_isort(self):
        before = src(
            """
            from .local import thing
            import waitress
            from types import SimpleNamespace
            import sys
            from __future__ import annotations
            import Cylinder
            from collections import UserDict
            import urllib.parse
            import functools
            from markupsafe import Markup

            x = 1
            """
        )
        assert sort_imports(before) == src(
            """
            from __future__ import annotations

            import functools
            import sys
            import urllib.parse
            from collections import UserDict
            from types import SimpleNamespace

            import Cylinder
            import waitress
            from markupsafe import Markup

            from .local import thing

            x = 1
            """
        )

    def test_merges_from_imports_and_orders_members_by_type(self):
        before = "from x import b, A\nfrom x import CONST, Zed, a\n"
        assert sort_imports(before) == "from x import CONST, A, Zed, a, b\n"

    def test_dedupes_and_keeps_aliases(self):
        before = "import os as o\nimport json\nimport json\nfrom a import b as c, b\n"
        assert sort_imports(before) == (
            "import json\nimport os as o\n\nfrom a import b, b as c\n"
        )

    def test_relative_import_without_module(self):
        assert sort_imports("from . import views\nimport os\n") == (
            "import os\n\nfrom . import views\n"
        )

    def test_wraps_long_from_import(self):
        names = ", ".join(f"name_{i:02d}" for i in range(12))
        result = sort_imports(f"from some_package.module import {names}\n")
        assert result.startswith("from some_package.module import (\n    name_00,\n")
        assert result.endswith("    name_11,\n)\n")
        assert all(len(line) <= 88 for line in result.splitlines())

    def test_unchanged_when_source_does_not_parse(self):
        assert sort_imports("import (\n") == "import (\n"

    def test_unchanged_without_leading_imports(self):
        before = "x = 1\nimport os\n"
        assert sort_imports(before) == before

    def test_unchanged_when_block_has_comments(self):
        before = "import sys\n# keep me here\nimport os\n"
        assert sort_imports(before) == before

    def test_unchanged_when_import_shares_line_with_code(self):
        before = "import sys; x = 1\n"
        assert sort_imports(before) == before


# ---------------------------------------------------------------------------
# normalize_blank_lines
# ---------------------------------------------------------------------------


class TestNormalizeBlankLines:
    def test_strips_file_edges_and_trailing_whitespace(self):
        assert normalize_blank_lines("\n\n\nx = 1   \ny = 2\t\n\n\n") == "x = 1\ny = 2\n"

    def test_adds_final_newline(self):
        assert normalize_blank_lines("x = 1") == "x = 1\n"

    def test_empty_source(self):
        assert normalize_blank_lines("") == ""
        assert normalize_blank_lines("\n\n") == ""

    def test_keeps_whitespace_and_blank_lines_inside_strings(self):
        before = 'x = """\nkeep   \n\n\n\nme\n"""   \n'
        assert normalize_blank_lines(before) == 'x = """\nkeep   \n\n\n\nme\n"""\n'

    def test_caps_blank_runs(self):
        before = src(
            """
            x = 1




            y = 2
            if y:
                a = 1



                b = 2
            """
        )
        assert normalize_blank_lines(before) == src(
            """
            x = 1


            y = 2
            if y:
                a = 1

                b = 2
            """
        )

    def test_two_blank_lines_around_top_level_definitions(self):
        before = src(
            """
            x = 1
            def f():
                return 1
            @decorator

            def g():
                pass
            class A:
                pass
            async def h():
                pass
            y = 2
            """
        )
        assert normalize_blank_lines(before) == src(
            """
            x = 1


            def f():
                return 1


            @decorator
            def g():
                pass


            class A:
                pass


            async def h():
                pass


            y = 2
            """
        )

    def test_one_blank_line_around_nested_definitions(self):
        before = src(
            """
            class A:
                x = 1
                def f(self):

                    def inner():
                        return 1
                    return inner
                y = 2
            """
        )
        assert normalize_blank_lines(before) == src(
            """
            class A:
                x = 1

                def f(self):

                    def inner():
                        return 1

                    return inner

                y = 2
            """
        )

    def test_block_start_blank_lines(self):
        before = src(
            """
            def keeps_one():



                x = 1


            def no_blank_before_docstring():

                \"\"\"Doc.\"\"\"


            async def async_keeps_one():

                pass


            class A:

                x = 1


            if x:

                # comment
                y = 1
            """
        )
        assert normalize_blank_lines(before) == src(
            """
            def keeps_one():

                x = 1


            def no_blank_before_docstring():
                \"\"\"Doc.\"\"\"


            async def async_keeps_one():

                pass


            class A:
                x = 1


            if x:
                # comment
                y = 1
            """
        )

    def test_comments_stay_attached_to_definitions(self):
        before = src(
            """
            x = 1
            # about f
            # more about f
            def f():
                pass
            # unrelated

            def g():
                pass
            # about y
            y = 2
            """
        )
        assert normalize_blank_lines(before) == src(
            """
            x = 1


            # about f
            # more about f
            def f():
                pass


            # unrelated


            def g():
                pass


            # about y
            y = 2
            """
        )

    def test_comment_runs_that_do_not_reach_a_definition(self):
        before = "x = 1\n# trailing comment"
        assert normalize_blank_lines(before) == "x = 1\n# trailing comment\n"
        before = "x = 1\n# indented differently\n    # from the code\ny = 2\n"
        assert normalize_blank_lines(before) == before

    def test_leaving_a_non_definition_block_keeps_spacing(self):
        before = "if x:\n    y = 1\nz = 2\n"
        assert normalize_blank_lines(before) == before

    def test_trailing_comment_in_function_body(self):
        before = "def f():\n    pass\n    # end of f\nx = 1\n"
        assert normalize_blank_lines(before) == "def f():\n    pass\n    # end of f\n\n\nx = 1\n"

    def test_dedented_comments_without_a_matching_opener(self):
        before = "    # odd leading comment\nx = 1\n"
        assert normalize_blank_lines(before) == before
        before = "def f():\n    x = 1\n  # odd comment\n    y = 2\n"
        assert normalize_blank_lines(before) == before

    def test_lines_after_imports(self):
        assert normalize_blank_lines("import os\nx = 1\n") == "import os\n\nx = 1\n"
        assert normalize_blank_lines("import os\n\n\n\nx = 1\n") == "import os\n\nx = 1\n"
        assert normalize_blank_lines("import os\ndef f():\n    pass\n") == (
            "import os\n\n\ndef f():\n    pass\n"
        )
        assert normalize_blank_lines("import os\n# note\nx = 1\n") == "import os\n# note\nx = 1\n"
        nested = "def f():\n    import os\n    return os\n"
        assert normalize_blank_lines(nested) == nested

    def test_unchanged_when_source_does_not_tokenize(self):
        assert normalize_blank_lines("x = (\n\n\n") == "x = (\n\n\n"

    def test_preserves_the_ast(self):
        before = src(
            '''
            import os
            class SessionDict(dict):
                """Doc."""
                def __init__(self, uid):
                    self.sql = """
                        SELECT


                        1
                    """
                    if uid:

                        self.uid = uid
                @property

                def uid_len(self):
                    return len(self.uid)
            x = [
                1,

                2,
            ]
            '''
        )
        after = normalize_blank_lines(before)
        assert after != before
        assert ast.dump(ast.parse(after)) == ast.dump(ast.parse(before))


# ---------------------------------------------------------------------------
# tidy_python
# ---------------------------------------------------------------------------


class TestTidyPython:
    def test_sorts_imports_then_normalizes_spacing(self):
        before = "import waitress\nimport sys\ndef main():\n    pass\n"
        assert tidy_python(before) == "import sys\n\nimport waitress\n\n\ndef main():\n    pass\n"

    def test_unchanged_when_source_is_invalid(self):
        assert tidy_python("x = (\n") == "x = (\n"
