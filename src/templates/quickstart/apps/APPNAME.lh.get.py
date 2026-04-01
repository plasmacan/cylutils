from werkzeug.wrappers import Response
from logging import Logger


def main(response: Response, logger: Logger) -> Response:

    logger.info("Hello from the late hook!")

    secrets = ["top_sneaky", "super_secret", "don't_tell_anyone"]

    maybe_secret_data = response.get_data(as_text=True)
    for secret in secrets:
        maybe_secret_data = maybe_secret_data.replace(secret, "[REDACTED]")

    response.data = maybe_secret_data
    return response
