import pathlib

from .feature import Feature

_RESOURCES = pathlib.Path(__file__).resolve().parent / "resources"
_EXAMPLES = _RESOURCES / "examples"


SIMPLE_STORE = Feature(
    imports=["from cylutils import simple_store"],
    init_code=["s = simple_store.Store()"],
    params=['"store": s'],
    extra_files=[
        (
            _EXAMPLES / "simple_store" / "storeexample.ex.get.py",
            "apps/{app_name}/storeexample.ex.get.py",
        ),
    ],
)

JINJA2 = Feature(
    imports=[
        "import functools",
        "import os",
        "import urllib.parse",
        "from datetime import datetime",
        "import jinja2",
        "from markupsafe import Markup",
    ],
    # Raw string so the \u escapes below land in server.py verbatim.
    init_code=[
        r'''
def ymd_with_time_title(value):
    """
    Split a datetime (or a date/datetime string) into ("YYYY-MM-DD", "HH:MM"),
    e.g. to show the date with the time in a title tooltip.
    Returns ("-", "") if the value can't be parsed.
    """
    if isinstance(value, datetime):
        dt = value
    else:
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(str(value), fmt)
                break
            except ValueError:
                continue
        else:
            return "-", ""
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def ymd_date(value):
    return ymd_with_time_title(value)[0]


def hm_time(value):
    return ymd_with_time_title(value)[1]


# Characters rewritten as \uXXXX so a value can't break out of a JS string literal,
# whether it sits in a <script> block or an on* event attribute.
_JS_ESCAPES = str.maketrans(
    {ch: f"\\u{ord(ch):04X}" for ch in "\\'\"<>&=-;`\u2028\u2029" + "".join(map(chr, range(32)))}
)


def escapejs(value):
    """Escape a value for use inside a quoted JS string, e.g. "{{ name|escapejs }}"."""
    # Markup stops autoescape from HTML-escaping the result a second time.
    return Markup(str(value).translate(_JS_ESCAPES))


def url_for(endpoint, **query_params):
    path = "/" + endpoint.strip("/")

    if query_params:
        qs = urllib.parse.urlencode(query_params)
        path = f"{path}?{qs}"

    return path


@functools.cache
def render_template_factory(template_root):
    """Return a render_template function for templates/<template_root>/, built once per app."""
    jinja_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(f"templates/{template_root}"),
        auto_reload=True,
        autoescape=jinja2.select_autoescape(),
    )

    jinja_env.filters["basename"] = os.path.basename
    jinja_env.filters["ymd_date"] = ymd_date
    jinja_env.filters["hm_time"] = hm_time
    jinja_env.filters["escapejs"] = escapejs
    jinja_env.globals["url_for"] = url_for

    def render_template(template_name, **context):
        template = jinja_env.get_template(template_name)
        return template.render(**context)

    return render_template'''
    ],
    params=['"render_template": render_template_factory("# APPNAME #")'],
    generated_links=['<a href="/jinja2-example">View Jinja2 Example</a>'],
    extra_files=[
        (
            _EXAMPLES / "jinja2" / "jinja2-example.ex.get.py",
            "apps/{app_name}/jinja2-example.ex.get.py",
        ),
        (
            _EXAMPLES / "jinja2" / "jinja2-example.html",
            "templates/{app_name}/jinja2-example.html",
        ),
    ],
)

ADD_G = Feature(
    imports=["from types import SimpleNamespace"],
    params=['"g": SimpleNamespace()'],
)

ADD_HTTP = Feature(
    imports=["import urllib3"],
    init_code=["http = urllib3.PoolManager(maxsize=8)"],
    params=['"http": http'],
)

SESSIONS = Feature(
    imports=[
        "import secrets",
        "import json",
        "import sqlite3",
        "from collections import UserDict",
    ],
    init_code=[
        """
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
        self._save()"""
    ],
    app_map_params=["request", "response"],
    app_map_code=[
        """
    session_id = request.cookies.get("session_id") or secrets.token_urlsafe(32)
    response.set_cookie("session_id", session_id, httponly=True) # should also set `secure=True` in production
    session = SessionDict(session_id)"""
    ],
    params=['"session": session', '"session_id": session_id'],
)


# Registry of selectable store types. Map CLI choice → Feature (or None for no-op).
STORE_TYPES: dict[str, Feature | None] = {
    "simple_store": SIMPLE_STORE,
    "none": None,
}

# Registry of selectable template engines. Map CLI choice → Feature (or None for no-op).
TEMPLATE_ENGINES: dict[str, Feature | None] = {
    "jinja2": JINJA2,
    "none": None,
}

# Optional add-on features enabled by boolean flags.
ADDONS: dict[str, Feature] = {
    "g": ADD_G,
    "sessions": SESSIONS,
    "http": ADD_HTTP,
}
