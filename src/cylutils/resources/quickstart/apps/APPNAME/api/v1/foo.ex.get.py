import json


def main(response):

    bars = [
        "bar1",
        "bar2",
        "bar3",
    ]
    response.data = json.dumps({"bars": bars, "message": "Hello from the quickstart template!"})
    return response
