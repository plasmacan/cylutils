from logging import Logger

from werkzeug.wrappers import Response


def main(response: Response, logger: Logger) -> Response:

    logger.info("Hello from the main handler!")
    with open("templates/example.html", "r", encoding="utf-8") as f:
        response.data = f.read()
    response.content_type = "text/html; charset=utf-8"

    return response
