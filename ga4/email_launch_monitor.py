#!/usr/bin/env python3
"""Watch traffic and key events land after an email send. Read-only.

Shows realtime active users (last 30 minutes), then today's sessions where
sessionMedium = email: by source, by landing page, and by utm_content (which
email in a sequence). Optionally narrow to one campaign with --campaign.

Usage:
  python3 email_launch_monitor.py --property 123456789
  python3 email_launch_monitor.py --path-contains /webinar --campaign spring_launch
  python3 email_launch_monitor.py --json-out output/email_monitor.json

Notes:
  * Realtime data covers roughly the last 30 minutes. Standard reports (the
    "today" sections) lag by minutes to hours, so a quiet "today" table right
    after a send is normal.
  * Email attribution depends on UTM tagging: the links must carry
    utm_medium=email. Untagged email clicks show up as direct or referral.
  * --path-contains filters rows after the query (substring, case-insensitive).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ga4_common as c  # noqa: E402


def minute_windows(by_minute, span=30, step=5):
    """Group {minutes_ago: users} into (start, end, total) windows.
    Example: step=5 gives (0, 4, n), (5, 9, n), ..."""
    return [(m, m + step - 1, sum(v for k, v in by_minute.items() if m <= k < m + step))
            for m in range(0, span, step)]


def filter_rows(rows, needle, index=0):
    """Keep rows whose column `index` contains needle (case-insensitive)."""
    if not needle:
        return rows
    return [r for r in rows if needle.lower() in str(r[index]).lower()]


def email_filter(medium, campaign):
    parts = [c.string_filter("sessionMedium", medium)]
    if campaign:
        parts.append(c.string_filter("sessionCampaignName", campaign, "CONTAINS"))
    return parts[0] if len(parts) == 1 else c.and_group(parts)


def realtime(client, prop, dims, mets, limit=25):
    from google.analytics.data_v1beta.types import Dimension, Metric, RunRealtimeReportRequest
    return client.run_realtime_report(RunRealtimeReportRequest(
        property=f"properties/{prop}",
        dimensions=[Dimension(name=d) for d in dims],
        metrics=[Metric(name=m) for m in mets],
        limit=limit))


def safe(label, fn):
    try:
        return fn()
    except Exception as e:
        print(f"  [{label} unavailable: {type(e).__name__}: {str(e)[:160]}]")
        return None


def main():
    ap = argparse.ArgumentParser(description="GA4 email launch monitor")
    ap.add_argument("--property", help="GA4 property ID (default: $GA4_PROPERTY_ID)")
    ap.add_argument("--medium", default="email", help="sessionMedium to track (default: email)")
    ap.add_argument("--campaign", help="Only sessions whose campaign name contains this")
    ap.add_argument("--path-contains", help="Only pages/landing pages containing this text")
    ap.add_argument("--json-out", help="Write results as JSON to this path")
    args = ap.parse_args()

    prop = c.resolve_property(args.property)
    client = c.get_client()
    flt = email_filter(args.medium, args.campaign)
    out = {"checked_at": datetime.now(timezone.utc).isoformat()}
    print(f"GA4 email launch monitor (property {prop})")
    print(f"checked at {out['checked_at']} UTC")

    def today(dims, mets, limit=25, order_metric="sessions"):
        return c.run_report(client, prop, dims, mets, "today", "today", dim_filter=flt,
                            order=[c.order_by_metric(order_metric)], limit=limit)

    print(c.section_title("ACTIVE USERS RIGHT NOW (all traffic)", 60))
    r = safe("realtime total", lambda: realtime(client, prop, [], ["activeUsers"]))
    total_now = int(c.rows_to_list(r)[0][0]) if r and r.rows else 0
    out["active_users_now"] = total_now
    print(f"  {total_now} active users")

    print(c.section_title("ACTIVE USERS BY MINUTE (last 30 min)", 60))
    r = safe("minutesAgo", lambda: realtime(client, prop, ["minutesAgo"], ["activeUsers"], 31))
    if r:
        buckets = {int(x[0]): int(x[1]) for x in c.rows_to_list(r)}
        out["by_minute"] = buckets
        for lo, hi, n in minute_windows(buckets):
            print(f"  {lo:>2}-{hi:>2} min ago  {n:>4}  {'#' * min(n, 60)}")

    print(c.section_title("TOP PAGES RIGHT NOW", 60))
    r = safe("realtime pages", lambda: realtime(client, prop, ["unifiedScreenName"],
                                                ["activeUsers"], 15))
    if r:
        pages = filter_rows(c.rows_to_list(r), args.path_contains)
        out["top_pages_now"] = pages
        for name, users in pages[:15] or [("(none)", "")]:
            print(f"  {users:>4}  {name[:88]}")

    key_metric = c.detect_key_event_metric(client, prop, "today", "today")
    print(c.section_title(f"TODAY: SESSIONS WHERE MEDIUM = {args.medium}", 60))
    mets = ["sessions", "activeUsers"] + ([key_metric] if key_metric else [])
    r = safe("email sessions", lambda: today(["sessionSource"], mets))
    if r:
        out["email_today"] = c.rows_to_list(r)
        if not r.rows:
            print("  no email sessions yet (standard reports lag a few minutes or more)")
        else:
            print(c.fmt_table(["source"] + mets, out["email_today"]))

    print(c.section_title("TODAY: EMAIL LANDING PAGES", 60))
    r = safe("landing pages", lambda: today(["landingPagePlusQueryString"], ["sessions"]))
    if r:
        lps = filter_rows(c.rows_to_list(r), args.path_contains)
        out["email_landing_pages"] = lps
        print(c.fmt_table(["landing page", "sessions"], lps[:15]))

    print(c.section_title("TODAY: EMAIL SESSIONS BY utm_content", 60))
    r = safe("utm_content", lambda: today(["sessionManualAdContent"], ["sessions"]))
    if r:
        out["email_by_content"] = c.rows_to_list(r)
        print(c.fmt_table(["utm_content", "sessions"], out["email_by_content"]))

    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w") as f:
            json.dump(out, f, indent=2)
        print(f"\nSaved: {args.json_out}")


if __name__ == "__main__":
    main()
