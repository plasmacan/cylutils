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
    imports=["import jinja2", "import urllib"],
    init_code=[
        """
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


jinja_env.globals["url_for"] = url_for"""
    ],
    params=['"render_template": render_template'],
    generated_links=['<a href="/jinja2-example">View Jinja2 Example</a>'],
    extra_files=[
        (
            _EXAMPLES / "jinja2" / "jinja2-example.ex.get.py",
            "apps/{app_name}/jinja2-example.ex.get.py",
        ),
        (
            _EXAMPLES / "jinja2" / "jinja2-example.html",
            "templates/jinja2-example.html",
        ),
    ],
)

ADD_G = Feature(
    imports=["from types import SimpleNamespace"],
    params=['"g": SimpleNamespace()'],
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
}
