#!/usr/bin/env python3
"""Paid traffic report: engagement by channel, source/medium, campaign and
landing page, using the same metrics as the GA4 "Traffic acquisition" report.

Usage:
  python3 paid_traffic_report.py --property 123456789 --start 2026-01-01 --end 2026-01-31
  GA4_PROPERTY_ID=123456789 python3 paid_traffic_report.py --start 30daysAgo --end today

Metrics (chosen so numbers match the GA4 UI):
  totalUsers, sessions, engagedSessions, engagementRate, userEngagementDuration

Why these and not others:
  * Average engagement time per session = userEngagementDuration / sessions.
    The UI column "Average engagement time per session" is calculated this way.
    Do NOT use averageSessionDuration: it measures session length including
    idle time, so it runs higher than the UI number.
  * engagementRate is returned by GA4 as a ratio per row (engagedSessions /
    sessions). Do not average it across rows; recompute from the counts.
  * totalUsers is de-duplicated within each row only. Users who appear under
    two campaigns are counted once in each row, so summing rows overcounts.
    The TOTAL section runs with no dimension to get a de-duplicated figure.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ga4_common as c  # noqa: E402

METRICS = ["totalUsers", "sessions", "engagedSessions", "engagementRate",
           "userEngagementDuration"]
METRIC_LABELS = ["Total Users", "Sessions", "Engaged Sessions", "Eng. Rate",
                 "Avg Eng. Time/Session"]
SESSIONS_IDX = METRICS.index("sessions")


def format_metric_values(metric_values):
    """Turn raw API metric strings (in METRICS order) into display strings."""
    users, sessions, engaged, rate, duration = [float(v) for v in metric_values]
    return [
        c.fmt_int(users),
        c.fmt_int(sessions),
        c.fmt_int(engaged),
        c.fmt_pct(rate, 2),
        c.fmt_avg_engagement(duration, sessions),
    ]


def format_row(dim_values, metric_values):
    return list(dim_values) + format_metric_values(metric_values)


def breakdown(client, prop, dimension, label, start, end, flt, limit=50):
    resp = c.run_report(client, prop, [dimension], METRICS, start, end,
                        dim_filter=flt,
                        order=[c.order_by_metric("sessions")], limit=limit)
    rows = [format_row([d.value for d in r.dimension_values],
                       [m.value for m in r.metric_values]) for r in resp.rows]
    return c.fmt_table([label] + METRIC_LABELS, rows)


def build_report(client, prop, start, end, landing_page_limit):
    flt = c.paid_filter()
    out = ["=" * 70, "  PAID TRAFFIC REPORT", f"  {start} to {end}", "=" * 70]

    out.append(c.section_title("TOTAL (no dimension, de-duplicated users)", 70))
    total = c.run_report(client, prop, [], METRICS, start, end, dim_filter=flt, limit=1)
    if total.rows:
        out.append(c.fmt_table(METRIC_LABELS, [format_metric_values(
            [m.value for m in total.rows[0].metric_values])]))
    else:
        out.append("(no data)")

    sections = [
        ("BY CHANNEL", "sessionDefaultChannelGroup", "Channel", 50),
        ("BY SOURCE / MEDIUM", "sessionSourceMedium", "Source / Medium", 50),
        ("BY CAMPAIGN", "sessionCampaignName", "Campaign", 50),
        (f"BY LANDING PAGE (top {landing_page_limit})", "landingPagePlusQueryString",
         "Landing Page", landing_page_limit),
    ]
    for title, dimension, label, limit in sections:
        out.append(c.section_title(title, 70))
        out.append(breakdown(client, prop, dimension, label, start, end, flt, limit))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="GA4 paid traffic report")
    c.add_common_args(ap)
    ap.add_argument("--landing-pages", type=int, default=20,
                    help="Number of landing pages to list (default 20)")
    args = ap.parse_args()

    prop = c.resolve_property(args.property)
    report = build_report(c.get_client(), prop, args.start, args.end, args.landing_pages)
    print(report)
    c.write_output(args.output, report)


if __name__ == "__main__":
    main()
