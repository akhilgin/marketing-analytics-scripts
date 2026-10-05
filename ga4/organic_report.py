#!/usr/bin/env python3
"""Organic and channel report for content-marketing analysis.

Answers: how much traffic comes from organic channels, how is it trending
month by month, which landing pages bring it, and which of them lead to key
events (conversions)?

Usage:
  python3 organic_report.py --property 123456789 --start 2025-10-01 --end 2026-09-30
  python3 organic_report.py --start 365daysAgo --end today --json-out output/organic.json

"Organic" here means these default channel groups: Organic Search, Organic
Social, Organic Video and Referral. Referral is included because it is where
links from other sites land; remove it from ORGANIC_CHANNELS if you want
search and social only.

Key events: GA4 renamed "conversions" to "key events". The script tries
keyEvents first and falls back to conversions for older properties.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ga4_common as c  # noqa: E402

ORGANIC_CHANNELS = ["Organic Search", "Organic Social", "Organic Video", "Referral"]
CORE_METRICS = ["sessions", "totalUsers", "newUsers", "engagedSessions", "userEngagementDuration"]


def organic_filter():
    return c.or_group([c.string_filter("sessionDefaultChannelGroup", g)
                       for g in ORGANIC_CHANNELS])


def collect(client, prop, start, end):
    key_metric = c.detect_key_event_metric(client, prop, start, end, CORE_METRICS)
    mets = CORE_METRICS + ([key_metric] if key_metric else [])
    org = organic_filter()
    by_sessions = [c.order_by_metric("sessions")]

    def q(dims, flt=None, order=None, limit=100):
        return c.rows_to_list(c.run_report(client, prop, dims, mets, start, end,
                                           dim_filter=flt, order=order, limit=limit))

    result = {"window": [start, end], "key_event_metric": key_metric, "metric_order": mets}
    result["by_channel"] = q(["sessionDefaultChannelGroup"], order=by_sessions)
    result["organic_monthly"] = q(["yearMonth"], org, [c.order_by_dimension("yearMonth")], 60)
    result["all_traffic_monthly"] = q(["yearMonth"], None, [c.order_by_dimension("yearMonth")], 60)
    result["organic_landing_pages"] = q(["landingPagePlusQueryString"], org, by_sessions, 30)
    if key_metric:
        result["organic_landing_pages_by_key_events"] = q(
            ["landingPagePlusQueryString"], org, [c.order_by_metric(key_metric)], 20)
    ev_metric = key_metric or "eventCount"
    try:
        resp = c.run_report(client, prop, ["eventName"], [ev_metric], start, end,
                            order=[c.order_by_metric(ev_metric)], limit=30)
        result["events"] = c.rows_to_list(resp)
    except Exception as ex:  # keep the rest of the report if this one fails
        result["events_error"] = str(ex)[:160]
    return result


def format_result(result):
    mets = result["metric_order"]
    out = [f"Window: {result['window'][0]} to {result['window'][1]}",
           f"Key event metric: {result['key_event_metric'] or 'not available'}"]
    titles = [
        ("by_channel", "ALL TRAFFIC BY CHANNEL GROUP", "Channel"),
        ("organic_monthly", "ORGANIC TREND BY MONTH", "Month"),
        ("all_traffic_monthly", "ALL TRAFFIC BY MONTH (context)", "Month"),
        ("organic_landing_pages", "TOP ORGANIC LANDING PAGES (by sessions)", "Landing page"),
        ("organic_landing_pages_by_key_events", "TOP ORGANIC LANDING PAGES (by key events)", "Landing page"),
    ]
    for key, title, label in titles:
        if key in result:
            out.append(c.section_title(title))
            out.append(c.fmt_table([label] + mets, result[key]))
    if "events" in result:
        out.append(c.section_title("EVENTS"))
        out.append(c.fmt_table(["Event", result["key_event_metric"] or "eventCount"], result["events"]))
    if "events_error" in result:
        out.append(f"\n[events unavailable: {result['events_error']}]")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="GA4 organic and channel report")
    c.add_common_args(ap)
    ap.add_argument("--json-out", help="Write raw results as JSON to this path")
    args = ap.parse_args()

    prop = c.resolve_property(args.property)
    result = collect(c.get_client(), prop, args.start, args.end)
    report = format_result(result)
    print(report)
    c.write_output(args.output, report)
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Saved JSON: {args.json_out}")


if __name__ == "__main__":
    main()
