import json


def main(request, response):

    data = request.form
    name = data.get("name", "world")
    response.data = json.dumps({"message": f"Hello, {name}"})
    return response
