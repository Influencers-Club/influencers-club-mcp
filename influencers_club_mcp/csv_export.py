"""
CSV generation utility for exporting discovery results to disk.
Flattens nested API response objects into flat CSV rows with proper escaping.

One flattener, two renderings: creators_to_csv joins lists with semicolons and keeps
values raw; the batch helpers (preview_rows, json_batch_to_csv) keep lists as JSON and
make every value a string.
"""

import csv
import io
import json
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


# ---- batch enrichment results -------------------------------------------------


def _flatten_batch(obj: Any, prefix: str = "") -> dict[str, str]:
    """Batch result rows: lists as JSON, every value a string (None becomes "")."""
    if not isinstance(obj, dict):
        return {}
    return _flatten(
        obj, prefix,
        list_as=lambda items: json.dumps(items) if items else "",
        scalar=lambda v: "" if v is None else str(v),
    )


def preview_rows(data: list[dict], max_rows: int = 5) -> list[dict[str, str]]:
    """Build a preview of the first N rows with key columns for UI display.

    Dynamically selects platform-specific columns based on what's actually
    present in the data, so previews work for any enrichment mode/platform.
    """
    # Always-show columns first, then platform-specific candidates in priority order
    always_keys = ["handle"]
    # Keys from email enrichment results (enrich_by_email / basic mode)
    email_keys = ["platform", "username", "fullname", "followers"]
    common_keys = ["first_name", "gender", "location", "is_creator", "has_brand_deals"]
    platform_keys_by_prefix = {
        "instagram": ["instagram.username", "instagram.follower_count", "instagram.engagement_percent"],
        "tiktok": ["tiktok.username", "tiktok.follower_count", "tiktok.engagement_percent"],
        "youtube": ["youtube.username", "youtube.subscriber_count", "youtube.engagement_percent"],
        "twitter": ["twitter.username", "twitter.follower_count"],
        "twitch": ["twitch.username", "twitch.follower_count"],
    }

    # Filter out not_found / failed rows — only show successful results in preview
    data = [item for item in data if item.get("status") != "not_found" and item.get("status") != "failed"]

    # Flatten a sample of rows to discover which keys exist
    sample_flats = []
    for item in data[:max_rows]:
        flat: dict[str, str] = {}
        for k, v in item.items():
            if k in ("result", "enrichment_data") and isinstance(v, dict):
                flat.update(_flatten_batch(v))
            elif isinstance(v, dict):
                flat.update(_flatten_batch(v, k))
            elif isinstance(v, (list, tuple)):
                flat[k] = json.dumps(v) if v else ""
            else:
                flat[k] = "" if v is None else str(v)
        if "handle" not in flat and "input_value" in flat:
            flat["handle"] = flat.pop("input_value")
        elif "handle" in flat and "input_value" in flat:
            flat.pop("input_value")
        sample_flats.append(flat)

    # Detect which platform columns are present
    all_sample_keys = set()
    for f in sample_flats:
        all_sample_keys.update(f.keys())

    platform_cols: list[str] = []
    for prefix, cols in platform_keys_by_prefix.items():
        if any(k in all_sample_keys for k in cols):
            platform_cols.extend(c for c in cols if c in all_sample_keys)

    preview_keys = always_keys + [k for k in email_keys if k in all_sample_keys] + [k for k in common_keys if k in all_sample_keys] + platform_cols

    rows = []
    for flat in sample_flats:
        row = {k: flat[k] for k in preview_keys if k in flat}
        rows.append(row)
    return rows


def json_batch_to_csv(data: Any) -> str:
    """Convert batch JSON response (list of objects) to CSV string."""
    if isinstance(data, dict):
        # Sometimes API wraps in a dict
        data = data.get("results", data.get("data", [data]))
    if not isinstance(data, list) or not data:
        return ""

    # Flatten all rows and collect all column names
    rows: list[dict[str, str]] = []
    all_keys: list[str] = []
    seen_keys: set[str] = set()

    for item in data:
        flat: dict[str, str] = {}
        # Flatten all top-level fields (input_value, status, handle, email, etc.)
        for k, v in item.items():
            if k in ("result", "enrichment_data") and isinstance(v, dict):
                # Promote result / enrichment_data contents to top-level (no prefix)
                flat.update(_flatten_batch(v))
            elif isinstance(v, dict):
                flat.update(_flatten_batch(v, k))
            elif isinstance(v, (list, tuple)):
                flat[k] = json.dumps(v) if v else ""
            else:
                flat[k] = "" if v is None else str(v)
        # Ensure handle column: use input_value as fallback
        if "handle" not in flat and "input_value" in flat:
            flat["handle"] = flat.pop("input_value")
        elif "handle" in flat and "input_value" in flat:
            flat.pop("input_value")  # avoid duplicate
        rows.append(flat)
        for k in flat:
            if k not in seen_keys:
                seen_keys.add(k)
                all_keys.append(k)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=all_keys, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()
