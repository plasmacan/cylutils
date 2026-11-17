def main(response, store):

    # put() never overwrites a key; increment() is atomic and creates it on first use.
    hits = store.increment("hits", init_value=1)

    response.data = f"Hello, world! This page has been visited {hits} times."
    return response
