import sys

import cylinder
import waitress

# IMPORTDEF #

# INITDEF #


def main(host: str | None, port: int | None) -> None:

    if not host and not port:
        print("\nTo change the host and port, run: python server.py [host] [port]")
    host = host or "127.0.0.1"
    port = port or 8080
    print(f"Starting server at http://{host}:{port}\n")


    app = cylinder.get_app(app_map=app_map)
    waitress.serve(app, host=host, port=port)


def app_map(# APPMAPPARAMS #):

    # APPMAPDEF #

    params = {}
    # PARAMSDEF #

    return "apps", "# APPNAME #", params


if __name__ == "__main__":
    host, port = None, None

    try:
        if len(sys.argv) > 1:
            host = sys.argv[1]
        if len(sys.argv) > 2:
            port = int(sys.argv[2])

        main(host, port)
    except Exception:
        print("Error starting server:", file=sys.stderr)
        print("Usage: python server.py [host] [port]", file=sys.stderr)
        raise
