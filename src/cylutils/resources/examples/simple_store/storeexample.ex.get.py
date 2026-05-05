def main(response, store):

    hits = store.get("hits") or 0 + 1
    store.put("hits", hits)

    response.body(f"Hello, world! This page has been visited {hits} times.")
    return response
