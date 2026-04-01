from werkzeug.wrappers import Response
from logging import Logger


def main(response: Response, logger: Logger) -> Response:

    logger.info("Hello from the main handler!")
    response.data = """
        <!DOCTYPE html>
        <html>
        <body>
            <h1>Welcome to My App!</h1>

            <p>This is the main handler.</p>

            <br>

            <h2>Here are some secrets:</h2>
            <p>top_sneaky, super_secret, don't_tell_anyone</p>
        </body>
        </html>
    """
    response.content_type = "text/html; charset=utf-8"

    return response
