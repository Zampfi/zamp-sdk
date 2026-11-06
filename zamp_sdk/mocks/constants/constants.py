# A faked httpx.Response has no real request, but raise_for_status() needs one, so it gets this stand-in.
PLACEHOLDER_REQUEST_METHOD = "GET"
PLACEHOLDER_REQUEST_URL = "https://mock.invalid"
