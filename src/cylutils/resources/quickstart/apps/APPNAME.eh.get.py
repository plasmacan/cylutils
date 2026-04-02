from werkzeug.wrappers import Request, Response
from werkzeug.exceptions import Aborter
from logging import Logger


def main(request: Request, response: Response, logger: Logger, abort: Aborter) -> Response:

    logger.info("Hello from the early hook!")
    user_agent = request.headers.get("User-Agent", "unknown")
    logger.info(f"User-Agent: {user_agent}")

    if "coffee" in user_agent.lower():
        logger.critical("Coffee detected! Aborting with 418 I'm a teapot.")
        abort(code=418)

    return response
