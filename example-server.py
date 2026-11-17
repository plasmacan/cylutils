import json
import os
import sys
from datetime import datetime
from types import SimpleNamespace

import cylinder
import jinja2
import urllib3
import waitress


def ymd_with_time_title(date_str):
    """
    Return (formatted_date, tooltip) tuple or ('-', '') if parsing fails.
    """
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(str(date_str), fmt)
            ymd = dt.strftime("%Y-%m-%d")
            hm = dt.strftime("%H:%M")
            return ymd, hm
        except Exception:
            continue
    return "-", ""


def ymd_date(date_str):
    return ymd_with_time_title(date_str)[0]


def hm_time(date_str):
    return ymd_with_time_title(date_str)[1]


def escapejs(value):
    # Use json.dumps to escape for JS string context.
    return json.dumps(str(value))[1:-1]  # strips off the quotes


def render_template_factory(template_root):

    jinja_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(f"templates/{template_root}"),
        auto_reload=True,
        autoescape=jinja2.select_autoescape(),
    )


    jinja_env.filters["basename"] = os.path.basename
    jinja_env.filters["ymd_date"] = ymd_date
    jinja_env.filters["hm_time"] = hm_time
    jinja_env.filters["escapejs"] = escapejs

    def render_template(template_name, **context):
        template = jinja_env.get_template(template_name)
        return template.render(**context)

    return render_template


http = urllib3.PoolManager(maxsize=8)


def route(request, response):
    return (
        "apps",
        "app.example.com",
        {
            "render_template": render_template_factory("app.example.com"),
            "http": http,
            "g": SimpleNamespace(),
        },
    )


def main(host=None, port=None):
    app = cylinder.get_app(app_map=route)
    waitress.serve(app, host=host or "127.0.0.1", port=port or 80)


if __name__ == "__main__":
    host = None
    port = None
    try:
        if len(sys.argv) > 2:
            port = int(sys.argv[2])
        if len(sys.argv) > 1:
            host = sys.argv[1]
    except Exception:
        print(f"Unable to parse: {sys.argv}")
        print("Usage: python server.py <host> <port>")
    main(host, port)
