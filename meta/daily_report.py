#!/usr/bin/env python3
"""Meta Ads daily performance report (Markdown to stdout).

Sections:
  1. Snapshot: one day vs the average of the previous 7 days
  2. Month-to-date pacing and straight-line end-of-month projection
  3. Top campaigns by spend for the day
  4. Alerts: CTR drop, CPC over a ceiling, spend with no conversions

Usage:
  export META_ACCESS_TOKEN=...
  python3 daily_report.py act_1234567890                       # yesterday
  python3 daily_report.py act_1234567890 --date 2026-01-15
  python3 daily_report.py act_1234567890 --month-budget 5000   # enables pacing %

The benchmark values are placeholders for illustration. Set targets that fit
your account with --ctr-target, --cpc-target, --cpm-target, --cpl-target and
--cpc-critical.

Conversions use the action types in meta_ads_client.DEFAULT_CONVERSION_ACTIONS
(override with --conversion-types). Those can overlap, so confirm the counts
against Ads Manager before trusting CPL.
"""

import argparse
import calendar
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meta_ads_client import (DEFAULT_CONVERSION_ACTIONS, MetaAdsClient,  # noqa: E402
                             extract_conversions)

DEFAULT_BENCHMARKS = {"ctr": 1.0, "cpc": 3.0, "cpc_critical": 10.0, "cpm": 15.0, "cpl": 75.0}


def parse_insights_row(row, action_types=DEFAULT_CONVERSION_ACTIONS):
    spend = float(row.get("spend", 0))
    impressions = int(row.get("impressions", 0))
    clicks = int(row.get("clicks", 0))
    conversions = extract_conversions(row.get("actions"), action_types)
    return {
        "spend": spend, "impressions": impressions, "clicks": clicks,
        "conversions": conversions, "reach": int(row.get("reach", 0)),
        **ratios(spend, impressions, clicks, conversions),
        "date_start": row.get("date_start"),
        "campaign_name": row.get("campaign_name", ""),
        "campaign_id": row.get("campaign_id", ""),
    }


def ratios(spend, impressions, clicks, conversions):
    return {
        "ctr": clicks / impressions * 100 if impressions else 0,
        "cpc": spend / clicks if clicks else 0,
        "cpm": spend / impressions * 1000 if impressions else 0,
        "cpl": spend / conversions if conversions else 0,
    }


def aggregate_metrics(rows):
    """Sum counts across rows and recompute ratios from the sums."""
    t = {k: sum(r.get(k, 0) for r in rows)
         for k in ("spend", "impressions", "clicks", "conversions", "reach")}
    t.update(ratios(t["spend"], t["impressions"], t["clicks"], t["conversions"]))
    return t


def delta_str(current, previous):
    if previous == 0:
        return "n/a" if current == 0 else "new"
    pct = (current - previous) / previous * 100
    return f"{'+' if pct >= 0 else ''}{pct:.0f}%"


def benchmark_flag(value, target, higher_is_better=True):
    """OK within target, WARN within 20% of it, BAD beyond. '-' when no data."""
    if value == 0:
        return "-"
    if higher_is_better:
        return "OK" if value >= target else "WARN" if value >= target * 0.8 else "BAD"
    return "OK" if value <= target else "WARN" if value <= target * 1.2 else "BAD"


def pacing_status(spent, budget, day, days_in_month, tolerance=15):
    """Compare % of budget used with % of month elapsed."""
    if budget <= 0:
        return "no budget set"
    used, expected = spent / budget * 100, day / days_in_month * 100
    if abs(used - expected) < tolerance:
        return "on track"
    return "underpacing" if used < expected else "overpacing"


def build_alerts(yday, avg7, campaigns_yday, camp_7d, b, min_spend_no_conv):
    alerts = []
    if yday["ctr"] > 0 and avg7["ctr"] > 0:
        change = (yday["ctr"] - avg7["ctr"]) / avg7["ctr"]
        if change < -0.20:
            alerts.append(("P1", "Account", "CTR drop",
                           f'{yday["ctr"]:.2f}% vs 7d avg {avg7["ctr"]:.2f}% ({change * 100:.0f}%)',
                           "Check creative fatigue"))
    if yday["clicks"] > 0 and yday["cpc"] > b["cpc_critical"]:
        alerts.append(("P0", "Account", "CPC over ceiling",
                       f'${yday["cpc"]:.2f} > ${b["cpc_critical"]:.2f}',
                       "Review targeting and bids"))
    for c in campaigns_yday:
        if c["spend"] == 0:
            continue
        prior = camp_7d.get(c["campaign_id"], {"spend": 0, "conversions": 0})
        spend, conv = prior["spend"] + c["spend"], prior["conversions"] + c["conversions"]
        if conv == 0 and spend > min_spend_no_conv:
            alerts.append(("P0", c["campaign_name"][:35], "No conversions",
                           f"${spend:.0f} spent over 8 days, 0 conversions",
                           "Check landing page, tracking, or pause"))
    order = {"P0": 0, "P1": 1, "P2": 2}
    return sorted(alerts, key=lambda a: order.get(a[0], 9))


def generate_report(client, report_date, month_budget, b, min_spend_no_conv, action_types):
    mtd_start = report_date.replace(day=1)
    seven_start, seven_end = report_date - timedelta(days=7), report_date - timedelta(days=1)
    days_in_month = calendar.monthrange(report_date.year, report_date.month)[1]
    days_elapsed = report_date.day
    num_7d = 7

    parse = lambda rows: [parse_insights_row(r, action_types) for r in rows]  # noqa: E731
    print("Fetching insights...", file=sys.stderr)
    daily = parse(client.get_insights(min(mtd_start, seven_start), report_date, "account", daily=True))
    camp_yday = parse(client.get_insights(report_date, report_date, "campaign", daily=True))
    camp_7d_rows = parse(client.get_insights(seven_start, seven_end, "campaign", daily=True))

    yday = aggregate_metrics([r for r in daily if r["date_start"] == report_date.isoformat()])
    seven = aggregate_metrics([r for r in daily
                               if seven_start.isoformat() <= (r["date_start"] or "") <= seven_end.isoformat()])
    avg7 = {k: v / num_7d for k, v in seven.items()}
    avg7.update(ratios(seven["spend"], seven["impressions"], seven["clicks"], seven["conversions"]))

    L = [f"# Meta Ads daily report: {report_date.strftime('%A, %B %d, %Y')}", "",
         "## Snapshot", "",
         "| Metric | Day | 7d avg | Delta | Target |", "|---|---|---|---|---|"]
    rows = [("Spend", "spend", "${:,.2f}", None), ("Impressions", "impressions", "{:,.0f}", None),
            ("Reach", "reach", "{:,.0f}", None), ("Clicks", "clicks", "{:,.0f}", None),
            ("Conversions", "conversions", "{:,.0f}", None)]
    for label, key, fmt, _ in rows:
        L.append(f"| {label} | {fmt.format(yday[key])} | {fmt.format(avg7[key])} | "
                 f"{delta_str(yday[key], avg7[key])} | - |")
    L.append(f'| CTR | {yday["ctr"]:.2f}% | {avg7["ctr"]:.2f}% | {delta_str(yday["ctr"], avg7["ctr"])} | '
             f'{benchmark_flag(yday["ctr"], b["ctr"])} (>= {b["ctr"]:.2f}%) |')
    L.append(f'| CPC | ${yday["cpc"]:.2f} | ${avg7["cpc"]:.2f} | {delta_str(yday["cpc"], avg7["cpc"])} | '
             f'{benchmark_flag(yday["cpc"], b["cpc"], False)} (<= ${b["cpc"]:.2f}) |')
    L.append(f'| CPM | ${yday["cpm"]:.2f} | ${avg7["cpm"]:.2f} | {delta_str(yday["cpm"], avg7["cpm"])} | '
             f'{benchmark_flag(yday["cpm"], b["cpm"], False)} (<= ${b["cpm"]:.2f}) |')
    if yday["conversions"] or avg7["conversions"]:
        L.append(f'| CPL | ${yday["cpl"]:.2f} | ${avg7["cpl"]:.2f} | {delta_str(yday["cpl"], avg7["cpl"])} | '
                 f'{benchmark_flag(yday["cpl"], b["cpl"], False)} (<= ${b["cpl"]:.2f}) |')

    mtd = aggregate_metrics([r for r in daily
                             if mtd_start.isoformat() <= (r["date_start"] or "") <= report_date.isoformat()])
    projected = mtd["spend"] / days_elapsed * days_in_month
    L += ["", "## Month-to-date pacing", "", "| Metric | Value |", "|---|---|",
          f'| MTD spend | ${mtd["spend"]:,.2f} |', f"| Day of month | {days_elapsed} / {days_in_month} |"]
    if month_budget:
        L.append(f"| Budget used | {mtd['spend'] / month_budget * 100:.1f}% "
                 f"(month elapsed: {days_elapsed / days_in_month * 100:.1f}%) |")
    L += [f"| Projected end of month (straight line) | ${projected:,.0f} |",
          f"| Status | {pacing_status(mtd['spend'], month_budget or 0, days_elapsed, days_in_month)} |", ""]

    camp_7d = {}
    for r in camp_7d_rows:
        t = camp_7d.setdefault(r["campaign_id"], {"spend": 0, "conversions": 0})
        t["spend"] += r["spend"]
        t["conversions"] += r["conversions"]
    camp_yday.sort(key=lambda x: x["spend"], reverse=True)
    L += ["## Top 5 campaigns by spend", "",
          "| Campaign | Spend | Clicks | Conv | CTR | CPC | Spend vs 7d avg |", "|---|---|---|---|---|---|---|"]
    for cmp_ in [x for x in camp_yday if x["spend"] > 0][:5]:
        avg_spend = camp_7d.get(cmp_["campaign_id"], {}).get("spend", 0) / num_7d
        L.append(f'| {cmp_["campaign_name"][:35]} | ${cmp_["spend"]:.2f} | {cmp_["clicks"]} | '
                 f'{cmp_["conversions"]} | {cmp_["ctr"]:.2f}% | ${cmp_["cpc"]:.2f} | '
                 f'{delta_str(cmp_["spend"], avg_spend)} |')

    L += ["", "## Alerts", ""]
    alerts = build_alerts(yday, avg7, camp_yday, camp_7d, b, min_spend_no_conv)
    if not alerts:
        L.append("None. Everything is within the thresholds.")
    for sev, who, issue, detail, action in alerts:
        L += [f"**{sev} {who}: {issue}**", f"- {detail}", f"- Action: {action}", ""]
    L += ["---", f'Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}']
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Meta Ads daily report")
    ap.add_argument("account_id", help="Ad account ID, e.g. act_1234567890")
    ap.add_argument("--date", type=date.fromisoformat, help="Report date YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--month-budget", type=float, help="Monthly budget, enables pacing %%")
    ap.add_argument("--min-spend-no-conv", type=float, default=200.0,
                    help="Alert when 8-day spend exceeds this with 0 conversions (default 200)")
    ap.add_argument("--conversion-types", help="Comma-separated Meta action types to count as conversions")
    for key, default in DEFAULT_BENCHMARKS.items():
        ap.add_argument(f"--{key.replace('_', '-')}{'' if key == 'cpc_critical' else '-target'}",
                        dest=f"b_{key}", metavar="N", type=float, default=default,
                        help=f"{key} benchmark (default {default})")
    args = ap.parse_args()

    b = {k: getattr(args, f"b_{k}") for k in DEFAULT_BENCHMARKS}
    types = tuple(args.conversion_types.split(",")) if args.conversion_types else DEFAULT_CONVERSION_ACTIONS
    report_date = args.date or date.today() - timedelta(days=1)
    try:
        client = MetaAdsClient(args.account_id)
        print(generate_report(client, report_date, args.month_budget, b, args.min_spend_no_conv, types))
    except (ValueError, RuntimeError) as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
