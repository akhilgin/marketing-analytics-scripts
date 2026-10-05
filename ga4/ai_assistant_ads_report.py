#!/usr/bin/env python3
"""Engagement and session quality for paid traffic from an AI assistant.

Answers: do sessions that arrive from ads placed inside an AI assistant or
answer engine engage differently from other paid traffic and from the site
overall?

Segment definition (the only thing this script assumes):
    session source CONTAINS one of the --source-contains terms (case-insensitive)
    AND session medium CONTAINS "paid" (case-insensitive)

This depends entirely on how your ad links are tagged. If the ads use
utm_source=assistantname&utm_medium=paid, they match. Untagged clicks are
not in this segment. Organic referrals from the same product (for example
source "assistant.example.com" with medium "referral", or a medium like
"ai-assistant") are excluded on purpose because they are not ads.

Usage:
  python3 ai_assistant_ads_report.py --property 123456789 --source-contains chatgpt
  python3 ai_assistant_ads_report.py --source-contains perplexity --source-contains copilot \\
      --start 2026-01-01 --end 2026-01-31

Sections: overview, session quality, top landing pages, top pages viewed,
weekly trend, and a benchmark against all paid traffic and the whole site.
The segment is a subset of "all paid"; read the benchmark as relative quality,
not additive volume.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ga4_common as c  # noqa: E402

CORE = ["totalUsers", "newUsers", "sessions", "engagedSessions",
        "engagementRate", "userEngagementDuration", "screenPageViews"]


def matches_ai_ads(source, medium, terms):
    """Pure version of the segment filter, used for tests and documentation."""
    src = (source or "").lower()
    med = (medium or "").lower()
    return "paid" in med and any(t.lower() in src for t in terms)


def segment_filter(terms):
    source_any = c.or_group([c.string_filter("sessionSource", t, "CONTAINS") for t in terms])
    return c.and_group([source_any, c.string_filter("sessionMedium", "paid", "CONTAINS")])


def overview(client, prop, start, end, flt, key_metric):
    """Totals with NO dimension so GA4 de-duplicates users and computes the
    ratio metrics itself. engagementRate is re-derived from counts as a check."""
    mets = CORE + ([key_metric] if key_metric else [])
    resp = c.run_report(client, prop, [], mets, start, end, dim_filter=flt, limit=1)
    if not resp.rows:
        return {m: 0.0 for m in mets}
    d = dict(zip(mets, [float(v.value) for v in resp.rows[0].metric_values]))
    if d.get("sessions"):
        d["engagementRate"] = d["engagedSessions"] / d["sessions"]
    return d


def quality_rows(d, key_metric):
    s, u = d["sessions"], d["totalUsers"]
    rows = [
        ("Engagement Rate", c.fmt_pct(d["engagementRate"])),
        ("Avg Engagement Time / Session", c.fmt_avg_engagement(d["userEngagementDuration"], s)),
        ("Sessions / User", f"{c.safe_div(s, u):.2f}"),
        ("Engaged Sessions / User", f"{c.safe_div(d['engagedSessions'], u):.2f}"),
        ("Page Views / Session", f"{c.safe_div(d['screenPageViews'], s):.2f}"),
    ]
    if key_metric:
        rows.append((f"{key_metric} / Session", f"{c.safe_div(d.get(key_metric, 0), s):.3f}"))
    return rows


def benchmark_row(label, d):
    s = d["sessions"]
    return [label, c.fmt_int(s), c.fmt_pct(d["engagementRate"]),
            c.fmt_avg_engagement(d["userEngagementDuration"], s),
            f"{c.safe_div(d['screenPageViews'], s):.2f}"]


def build_report(client, prop, start, end, terms):
    flt = segment_filter(terms)
    key_metric = c.detect_key_event_metric(client, prop, start, end, CORE)
    mets = CORE + ([key_metric] if key_metric else [])
    seg = overview(client, prop, start, end, flt, key_metric)

    out = ["=" * 74, "  AI ASSISTANT ADS REPORT", f"  Window: {start} to {end}",
           f"  Segment: source contains {terms} AND medium contains 'paid'", "=" * 74]

    out.append(c.section_title("1. OVERVIEW", 74))
    kv = [("Total Users", c.fmt_int(seg["totalUsers"])), ("New Users", c.fmt_int(seg["newUsers"])),
          ("Sessions", c.fmt_int(seg["sessions"])), ("Engaged Sessions", c.fmt_int(seg["engagedSessions"])),
          ("Page Views", c.fmt_int(seg["screenPageViews"]))]
    if key_metric:
        kv.append((f"Key Events ({key_metric})", c.fmt_int(seg.get(key_metric, 0))))
    out.append(c.fmt_table(["Metric", "Value"], kv))

    out.append(c.section_title("2. SESSION QUALITY", 74))
    out.append(c.fmt_table(["Quality Metric", "Value"], quality_rows(seg, key_metric)))

    out.append(c.section_title("3. TOP LANDING PAGES", 74))
    resp = c.run_report(client, prop, ["landingPagePlusQueryString"], mets, start, end,
                        dim_filter=flt, order=[c.order_by_metric("sessions")], limit=20)
    rows = []
    for r in resp.rows:
        v = dict(zip(mets, [float(m.value) for m in r.metric_values]))
        rows.append([r.dimension_values[0].value, c.fmt_int(v["sessions"]),
                     c.fmt_pct(v["engagementRate"]),
                     c.fmt_avg_engagement(v["userEngagementDuration"], v["sessions"]),
                     c.fmt_int(v["screenPageViews"])])
    out.append(c.fmt_table(["Landing Page", "Sessions", "Eng. Rate", "Avg Eng.", "Page Views"], rows))

    out.append(c.section_title("4. TOP PAGES VIEWED (all pages in the session)", 74))
    resp = c.run_report(client, prop, ["pagePathPlusQueryString"],
                        ["screenPageViews", "activeUsers", "userEngagementDuration"], start, end,
                        dim_filter=flt, order=[c.order_by_metric("screenPageViews")], limit=20)
    rows = []
    for r in resp.rows:
        pv, au, eng = [float(m.value) for m in r.metric_values]
        rows.append([r.dimension_values[0].value, c.fmt_int(pv), c.fmt_int(au),
                     c.fmt_avg_engagement(eng, au)])
    out.append(c.fmt_table(["Page Path", "Page Views", "Active Users", "Avg Eng./User"], rows))

    out.append(c.section_title("5. WEEKLY TREND", 74))
    resp = c.run_report(client, prop, ["yearWeek"], mets, start, end, dim_filter=flt,
                        order=[c.order_by_dimension("yearWeek")], limit=60)
    rows = []
    for r in resp.rows:
        v = dict(zip(mets, [float(m.value) for m in r.metric_values]))
        rows.append([r.dimension_values[0].value, c.fmt_int(v["totalUsers"]), c.fmt_int(v["sessions"]),
                     c.fmt_pct(v["engagementRate"]),
                     c.fmt_avg_engagement(v["userEngagementDuration"], v["sessions"]),
                     c.fmt_int(v["screenPageViews"])])
    out.append(c.fmt_table(["Year-Week", "Users", "Sessions", "Eng. Rate", "Avg Eng.", "Page Views"], rows))

    out.append(c.section_title("6. BENCHMARK", 74))
    all_paid = overview(client, prop, start, end, c.paid_filter(), key_metric)
    site = overview(client, prop, start, end, None, key_metric)
    out.append(c.fmt_table(
        ["Segment", "Sessions", "Eng. Rate", "Avg Eng./Session", "Views/Session"],
        [benchmark_row("AI assistant ads", seg), benchmark_row("All paid", all_paid),
         benchmark_row("Site-wide", site)]))
    out.append("\nNote: the segment is a subset of 'All paid'. Compare quality, do not add volumes.")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="GA4 report for AI assistant ad traffic")
    c.add_common_args(ap, default_start="30daysAgo", default_end="today")
    ap.add_argument("--source-contains", action="append",
                    help="Substring of utm_source to treat as the assistant (repeatable, "
                         "default: chatgpt)")
    args = ap.parse_args()
    terms = args.source_contains or ["chatgpt"]

    prop = c.resolve_property(args.property)
    report = build_report(c.get_client(), prop, args.start, args.end, terms)
    print(report)
    c.write_output(args.output, report)


if __name__ == "__main__":
    main()
