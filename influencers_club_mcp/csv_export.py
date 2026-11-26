"""
CSV generation utility for exporting discovery results to disk.
Flattens nested API response objects into flat CSV rows with proper escaping.
"""

import csv
import io
from typing import Any

# UTF-8 BOM for Excel compatibility
UTF8_BOM = "\ufeff"

# Preferred column order — these appear first in the CSV
PREFERRED_ORDER = [
    # Discovery columns
    "profile.username",
    "profile.full_name",
    "profile.followers",
    "profile.engagement_percent",
    "user_id",
    "profile.picture",
    # Enrichment columns
    "input_value",
    "email",
    "first_name",
    "full_name",
    "gender",
    "location",
    "email_type",
    "is_creator",
    "is_business",
]


def _flatten(obj: dict[str, Any], prefix: str, *, list_as, scalar) -> dict[str, Any]:
    """Flatten a nested dict into dot-notation keys, e.g. {"profile": {"username": "foo"}}
    -> {"profile.username": "foo"}. ``list_as`` renders a list, ``scalar`` everything else."""
    out: dict[str, Any] = {}
    for key, value in obj.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, full_key, list_as=list_as, scalar=scalar))
        elif isinstance(value, (list, tuple)):
            out[full_key] = list_as(value)
        else:
            out[full_key] = scalar(value)
    return out


def _flatten_object(obj: dict[str, Any]) -> dict[str, Any]:
    """Discovery export rows: lists joined with semicolons, other values kept as they are."""
    return _flatten(
        obj, "",
        list_as=lambda items: "; ".join(str(i) if i is not None else "" for i in items),
        scalar=lambda v: v,
    )


def creators_to_csv(creators: list[dict[str, Any]]) -> str:
    """
    Convert an array of creator objects to a CSV string.
    Returns CSV with UTF-8 BOM, header row, and data rows.
    """
    if not creators:
        return UTF8_BOM + "No results found\n"

    # Flatten all creators
    rows = [_flatten_object(c) for c in creators]

    # Collect all column names across all rows
    all_keys: set[str] = set()
    for row in rows:
        all_keys.update(row.keys())

    # Order: preferred columns first (if present), then remaining sorted
    preferred = [c for c in PREFERRED_ORDER if c in all_keys]
    remaining = sorted(c for c in all_keys if c not in PREFERRED_ORDER)
    columns = preferred + remaining

    # Clean header names for readability (remove "profile." prefix)
    headers = [col.replace("profile.", "") if col.startswith("profile.") else col for col in columns]

    # Build CSV using Python's csv module for proper RFC 4180 escaping
    output = io.StringIO()
    output.write(UTF8_BOM)
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(col, "") for col in columns])

    return output.getvalue()
