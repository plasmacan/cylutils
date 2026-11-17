def main(response, store):

    # put() never overwrites an existing key; increment() is atomic and creates the key on first use.
    hits = store.increment("hits", init_value=1)

    response.data = f"Hello, world! This page has been visited {hits} times."
    return response
