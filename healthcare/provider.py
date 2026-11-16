"""Resolve the permitted inference transport without exposing credentials."""

import os
from urllib.parse import urlsplit


def settings(local: bool):
    endpoint = os.environ["CLAIMS_LLM_ENDPOINT"]
    address = urlsplit(endpoint)
    if (
        not address.hostname
        or address.username is not None
        or address.fragment
        or address.query
    ):
        raise ValueError("Invalid model endpoint")
    if local:
        if address.scheme != "http" or address.hostname not in (
            "localhost",
            "127.0.0.1",
            "::1",
            "llm",
        ):
            raise ValueError(
                "Use a loopback endpoint or the local Compose inference service"
            )
        key = ""
    else:
        if address.scheme != "https":
            raise ValueError("Hosted inference requires HTTPS")
        key = os.environ["CLAIMS_LLM_API_KEY"]
    return endpoint, key, os.environ["CLAIMS_LLM_MODEL"]
