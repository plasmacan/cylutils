from werkzeug.wrappers import Request, Response


def main(request: Request, response: Response, render_template):

    response.data = render_template("jinja2-example.html", args=request.args)
    response.content_type = "text/html; charset=utf-8"
    return response