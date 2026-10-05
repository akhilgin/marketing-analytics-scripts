#!/usr/bin/env python3
"""Find 404 / error pages in GA4 so you know what to redirect.

Looks for pages whose page title contains a 404-style phrase ("404",
"not found", "page not found", "error"), then reports views, users and
sessions by path, by source/medium and by referrer. It also lists the top
pages overall as a sanity check.

Usage:
  python3 broken_links_404_audit.py --property 123456789 --hostname www.example.com \\
      --start 2026-01-01 --end 2026-01-31 --output-dir output/404-audit

How it works and where it can mislead:
  * Detection is by pageTitle. It works when your 404 template has a
    recognisable title and the browser URL stays on the broken URL (so
    pagePath is the broken link). If your site redirects to a /404 page,
    pagePath will be that page and you need pageReferrer to find the source.
  * "error" is a loose pattern. A blog post titled "Common SQL errors" will
    match. Pass your own --pattern values to tighten it.
  * pagePath has no query string; paths that differ only by a trailing slash
    or duplicate slashes are merged here (see normalize_path).
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ga4_common as c  # noqa: E402

DEFAULT_PATTERNS = ["404", "not found", "page not found", "error"]
METRICS = ["screenPageViews", "totalUsers", "sessions"]
METRIC_LABELS = ["Views", "Users", "Sessions"]


def is_error_title(title, patterns=DEFAULT_PATTERNS):
    t = (title or "").lower()
    return any(p.lower() in t for p in patterns)


def normalize_path(path):
    """Drop query/fragment, collapse repeated slashes, strip a trailing slash
    (except for the root). Case is preserved because paths can be case-sensitive."""
    p = urlsplit(path or "/").path or "/"
    while "//" in p:
        p = p.replace("//", "/")
    if len(p) > 1 and p.endswith("/"):
        p = p.rstrip("/")
    return p


def merge_by_normalized_path(rows):
    """rows: [path, title, views, users, sessions, ...] with numeric strings.
    Returns rows merged on (normalized path, title), sorted by views desc.
    Users are summed across merged rows, which can overcount people who hit
    two variants; treat merged user counts as an upper bound."""
    merged = defaultdict(lambda: [0, 0, 0])
    for path, title, views, users, sessions in (r[:5] for r in rows):
        key = (normalize_path(path), title)
        for i, v in enumerate((views, users, sessions)):
            merged[key][i] += int(v)
    out = [[p, t] + vals for (p, t), vals in merged.items()]
    return sorted(out, key=lambda r: r[2], reverse=True)


def write_csv(path, headers, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description="GA4 404 / error page audit")
    c.add_common_args(ap)
    ap.add_argument("--hostname", required=True, help="Hostname to audit, e.g. www.example.com")
    ap.add_argument("--pattern", action="append",
                    help="Title substring that marks an error page (repeatable; "
                         f"default: {DEFAULT_PATTERNS})")
    ap.add_argument("--output-dir", help="Also write CSVs (pages, sources, referrers) here")
    args = ap.parse_args()
    patterns = args.pattern or DEFAULT_PATTERNS

    prop = c.resolve_property(args.property)
    client = c.get_client()
    host = c.string_filter("hostName", args.hostname)
    err = c.or_group([c.string_filter("pageTitle", p, "CONTAINS") for p in patterns])
    both = c.and_group([host, err])
    order = [c.order_by_metric("screenPageViews")]

    def q(dims, flt, limit):
        return c.rows_to_list(c.run_report(client, prop, dims, METRICS, args.start, args.end,
                                           dim_filter=flt, order=order, limit=limit))

    def ints(rows, n_dims):
        return [r[:n_dims] + [f"{int(v):,}" for v in r[n_dims:]] for r in rows]

    out = ["=" * 80, f"  404 / ERROR PAGE AUDIT: {args.hostname}",
           f"  {args.start} to {args.end}", "=" * 80]

    pages = merge_by_normalized_path(q(["pagePath", "pageTitle"], both, 250))
    total = sum(r[2] for r in pages)
    out.append(c.section_title(f"ERROR PAGES (title contains any of {patterns})", 80))
    out.append(f"Total error page views: {total:,} across {len(pages)} path+title combinations\n")
    out.append(c.fmt_table(["Path", "Title"] + METRIC_LABELS, ints(pages[:50], 2), 55))

    sources = q(["sessionSourceMedium"], both, 50)
    out.append(c.section_title("TOP SOURCES / MEDIUMS LANDING ON ERROR PAGES", 80))
    out.append(c.fmt_table(["Source / Medium"] + METRIC_LABELS, ints(sources[:25], 1)))

    referrers = q(["pageReferrer"], both, 50)
    out.append(c.section_title("TOP REFERRERS TO ERROR PAGES", 80))
    out.append(c.fmt_table(["Referrer"] + METRIC_LABELS, ints(referrers[:25], 1), 70))

    top = q(["pagePath", "pageTitle"], host, 25)
    out.append(c.section_title("TOP 25 PAGES OVERALL (sanity check)", 80))
    out.append(c.fmt_table(["Path", "Title"] + METRIC_LABELS, ints(top, 2), 50))

    report = "\n".join(out)
    print(report)
    c.write_output(args.output, report)
    if args.output_dir:
        write_csv(os.path.join(args.output_dir, "error_pages.csv"),
                  ["pagePath", "pageTitle", "views", "users", "sessions"], pages)
        write_csv(os.path.join(args.output_dir, "error_sources.csv"),
                  ["sourceMedium", "views", "users", "sessions"], sources)
        write_csv(os.path.join(args.output_dir, "error_referrers.csv"),
                  ["referrer", "views", "users", "sessions"], referrers)
        print(f"CSVs written to: {args.output_dir}")


if __name__ == "__main__":
    main()
