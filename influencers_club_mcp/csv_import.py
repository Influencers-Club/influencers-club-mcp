"""
Handle/email detection for batch enrichment input.
Shared by the upload page and inline csv_content in create_batch_enrichment.
"""

import csv
import io

VALID_HEADERS = ("email", "handle", "emails", "handles")


def _clean(value: str) -> str:
    return value.strip().replace('"', "").replace("'", "")


def _is_email(value: str) -> bool:
    return "@" in value and "." in value.split("@")[-1]


def mostly_emails(values: list[str]) -> bool:
    """True when more than half of the values look like email addresses."""
    return sum(1 for v in values if _is_email(v)) > len(values) / 2


def header_columns(line: str) -> list[str]:
    """Column names of a CSV header line, lower-cased and unquoted."""
    return [_clean(c).lower() for c in line.split(",")]


def count_csv_rows(text: str) -> int:
    """Count data rows in CSV text (excluding header)."""
    lines = [line for line in text.strip().split("\n") if line.strip()]
    return max(0, len(lines) - 1)


def to_single_column(
    lines: list[str], *, first_line_is_header: bool
) -> tuple[list[str], str, int | None] | None:
    """Reduce non-blank CSV lines to one handle/email column under an email/handle header.

    With several columns, the first one named email(s)/handle(s) is kept; failing that, the
    column whose first five values are mostly emails (the one with the most wins), else the
    first column as handles. The first line is dropped as the header.

    A single column already named email(s)/handle(s) needs no change: returns None. Otherwise
    its first five values decide the type. With first_line_is_header (the upload page) the
    first line is replaced by the header; without it (inline lists) the first line is kept
    as a value and the header goes above it.

    Returns (lines, "email" or "handle", kept column index, or None for one-column input).
    Raises ValueError when a single column has no values to decide from.
    """
    header_cols = header_columns(lines[0])

    if len(header_cols) > 1:
        best_col, detected_type = 0, "handle"
        for i, col_name in enumerate(header_cols):
            if col_name in VALID_HEADERS:
                best_col = i
                detected_type = "email" if col_name in ("email", "emails") else "handle"
                break
        else:
            # No valid header name: pick the column with the most emails, if mostly emails
            best_email_count = 0
            for i in range(len(header_cols)):
                sample = []
                for row in lines[1:6]:
                    cells = row.split(",")
                    if i < len(cells) and (value := _clean(cells[i])):
                        sample.append(value)
                email_count = sum(1 for v in sample if _is_email(v))
                if email_count > len(sample) / 2 and email_count > best_email_count:
                    best_col, detected_type, best_email_count = i, "email", email_count

        reader = csv.reader(io.StringIO("\n".join(lines)))
        next(reader, None)  # the original header
        values = [row[best_col].strip() for row in reader if best_col < len(row)]
        return [detected_type] + [v for v in values if v], detected_type, best_col

    if header_cols[0] in VALID_HEADERS:
        return None
    values = lines[1:] if first_line_is_header else lines
    sample = [v for v in map(_clean, values[:5]) if v]
    if not sample:
        raise ValueError("CSV has no data rows")
    detected_type = "email" if mostly_emails(sample) else "handle"
    return [detected_type] + values, detected_type, None
