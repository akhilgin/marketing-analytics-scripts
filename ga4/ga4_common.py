"""Shared helpers for the GA4 scripts.

Pure helpers (formatting, classification, argument handling) have no
third-party imports so they can be unit tested without network access.
Anything that needs google-analytics-data imports it lazily.
"""

import os
import re
import sys

# ---------------------------------------------------------------------------
# Paid traffic definition
# ---------------------------------------------------------------------------
# Mirrors the filter used by the paid traffic and AI assistant reports.
# A session counts as paid if EITHER its default channel group is one of the
# paid groups OR its medium looks paid. The medium checks catch untagged or
# custom-tagged traffic that GA4 did not put in a paid channel group.
PAID_CHANNEL_GROUPS = ["Paid Search", "Paid Social", "Display", "Paid Other"]
PAID_MEDIUM_EXACT = ["cpc", "ppc"]
PAID_MEDIUM_CONTAINS = ["paid", "sponsored"]


def is_paid_session(channel_group, medium):
    """Python equivalent of the paid filter. Case-insensitive, like the API
    default for string filters."""
    cg = (channel_group or "").strip().lower()
    med = (medium or "").strip().lower()
    if cg in {g.lower() for g in PAID_CHANNEL_GROUPS}:
        return True
    if med in PAID_MEDIUM_EXACT:
        return True
    return any(token in med for token in PAID_MEDIUM_CONTAINS)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def fmt_int(value):
    return f"{int(round(float(value))):,}"


def fmt_pct(value, digits=1):
    return f"{float(value):.{digits}%}"


def fmt_avg_engagement(total_seconds, sessions):
    """Average engagement time per session.

    userEngagementDuration is the TOTAL engagement time in seconds for the
    rows in the report, so divide by sessions. This is what the GA4 UI shows
    as "Average engagement time per session".
    """
    sessions = float(sessions or 0)
    if sessions <= 0:
        return "0s"
    minutes, seconds = divmod(int(round(float(total_seconds) / sessions)), 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


def safe_div(numerator, denominator):
    return float(numerator) / float(denominator) if denominator else 0.0


def fmt_table(headers, rows, max_col_width=60):
    """Plain-text table. Cells wider than max_col_width are truncated."""
    if not rows:
        return "(no data)"
    str_rows = [[str(c) for c in r] for r in rows]
    widths = [
        min(max(len(str(h)), *(len(r[i]) for r in str_rows)), max_col_width)
        for i, h in enumerate(headers)
    ]
    lines = [" | ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))]
    lines.append("-+-".join("-" * w for w in widths))
    for r in str_rows:
        lines.append(" | ".join(r[i].ljust(widths[i])[:widths[i]] for i in range(len(headers))))
    return "\n".join(lines)


def section_title(title, width=74):
    return f"\n{'-' * width}\n  {title}\n{'-' * width}\n"


# ---------------------------------------------------------------------------
# Arguments and credentials
# ---------------------------------------------------------------------------

def normalize_property_id(value):
    """Accept '123456789' or 'properties/123456789'; return the digits."""
    if value is None:
        return None
    value = str(value).strip()
    if value.startswith("properties/"):
        value = value[len("properties/"):]
    return value if re.fullmatch(r"\d+", value) else None


def resolve_property(cli_value):
    """GA4 property ID from --property, falling back to GA4_PROPERTY_ID."""
    raw = cli_value or os.environ.get("GA4_PROPERTY_ID")
    prop = normalize_property_id(raw)
    if not prop:
        sys.exit("Set the GA4 property with --property or GA4_PROPERTY_ID "
                 "(numeric ID, e.g. 123456789).")
    return prop


def add_common_args(parser, default_start=None, default_end=None):
    parser.add_argument("--property", help="GA4 property ID (default: $GA4_PROPERTY_ID)")
    parser.add_argument("--start", default=default_start, required=default_start is None,
                        help="Start date YYYY-MM-DD or GA4 relative (e.g. 30daysAgo)")
    parser.add_argument("--end", default=default_end, required=default_end is None,
                        help="End date YYYY-MM-DD or GA4 relative (e.g. today)")
    parser.add_argument("--output", help="Also write the report to this file")


def write_output(path, text):
    if not path:
        return
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "w") as f:
        f.write(text + "\n")
    print(f"\nSaved to: {path}")


# ---------------------------------------------------------------------------
# GA4 Data API wrappers (lazy imports)
# ---------------------------------------------------------------------------

def get_client():
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        sys.exit("Set GOOGLE_APPLICATION_CREDENTIALS to your service account JSON path.")
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    return BetaAnalyticsDataClient()


def string_filter(field, value, match="EXACT", case_sensitive=False):
    """Build a single-field string FilterExpression. match: EXACT, CONTAINS,
    BEGINS_WITH, ENDS_WITH, FULL_REGEXP, PARTIAL_REGEXP."""
    from google.analytics.data_v1beta.types import Filter, FilterExpression
    return FilterExpression(filter=Filter(
        field_name=field,
        string_filter=Filter.StringFilter(
            value=value,
            match_type=getattr(Filter.StringFilter.MatchType, match),
            case_sensitive=case_sensitive)))


def or_group(expressions):
    from google.analytics.data_v1beta.types import FilterExpression, FilterExpressionList
    return FilterExpression(or_group=FilterExpressionList(expressions=list(expressions)))


def and_group(expressions):
    from google.analytics.data_v1beta.types import FilterExpression, FilterExpressionList
    return FilterExpression(and_group=FilterExpressionList(expressions=list(expressions)))


def paid_filter():
    """Filter matching is_paid_session()."""
    exprs = [string_filter("sessionDefaultChannelGroup", g) for g in PAID_CHANNEL_GROUPS]
    exprs += [string_filter("sessionMedium", m) for m in PAID_MEDIUM_EXACT]
    exprs += [string_filter("sessionMedium", m, "CONTAINS") for m in PAID_MEDIUM_CONTAINS]
    return or_group(exprs)


def order_by_metric(name, desc=True):
    from google.analytics.data_v1beta.types import OrderBy
    return OrderBy(metric=OrderBy.MetricOrderBy(metric_name=name), desc=desc)


def order_by_dimension(name, desc=False):
    from google.analytics.data_v1beta.types import OrderBy
    return OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name=name), desc=desc)


def run_report(client, property_id, dims, mets, start, end,
               dim_filter=None, order=None, limit=100):
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Metric, RunReportRequest)
    return client.run_report(RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name=d) for d in dims],
        metrics=[Metric(name=m) for m in mets],
        date_ranges=[DateRange(start_date=start, end_date=end)],
        dimension_filter=dim_filter,
        order_bys=order or [],
        limit=limit,
        keep_empty_rows=False,
    ))


def rows_to_list(resp):
    """Each row becomes [dimension values..., metric values...] (all strings)."""
    return [[d.value for d in r.dimension_values] + [m.value for m in r.metric_values]
            for r in resp.rows]


def detect_key_event_metric(client, property_id, start, end, base_metrics=("sessions",)):
    """Return 'keyEvents' (current name) or 'conversions' (older name),
    whichever the property accepts, or None. Probes with a limit=1 query."""
    for candidate in ("keyEvents", "conversions"):
        try:
            run_report(client, property_id, ["sessionDefaultChannelGroup"],
                       list(base_metrics) + [candidate], start, end, limit=1)
            return candidate
        except Exception:
            continue
    return None
