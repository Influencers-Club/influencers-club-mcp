"""Shared pieces of the API client's endpoint modules: the version prefix and the
check that a value may become one segment of an address."""

import re

ROOT = "/public/v1"
# Letters, digits, "_" and "-" only: a dot could spell ".." and a slash another route.
_SEGMENT = re.compile(r"[A-Za-z0-9_-]+")


def segment(value: str, name: str) -> str:
    """Return ``value`` if it can safely be one path segment, else raise ValueError.

    A slash, a query or a fragment in a platform or an id would send the request to
    a different endpoint, so the endpoint modules refuse them before building a path.
    """
    if not isinstance(value, str) or not _SEGMENT.fullmatch(value):
        raise ValueError(f"Invalid {name} {value!r}")
    return value
