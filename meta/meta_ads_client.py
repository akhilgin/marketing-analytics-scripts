#!/usr/bin/env python3
"""Small read-only client for the Meta Marketing API (Graph API).

Covers account info, campaigns and insights. It does not create or modify
anything.

Auth: set META_ACCESS_TOKEN to a user or system-user token with the ads_read
permission. The token is sent in an Authorization header, never in the URL,
and is not printed.

CLI:
  python3 meta_ads_client.py act_1234567890 info
  python3 meta_ads_client.py act_1234567890 campaigns
  python3 meta_ads_client.py 1234567890 insights --since 2026-01-01 --until 2026-01-07 --level campaign

The "act_" prefix on the account ID is optional.
"""

import argparse
import json
import os
import sys
from datetime import date

API_VERSION = os.environ.get("META_API_VERSION", "v21.0")
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"
TIMEOUT = 60

DEFAULT_INSIGHT_FIELDS = [
    "campaign_name", "campaign_id", "spend", "impressions", "clicks",
    "cpc", "cpm", "ctr", "actions", "cost_per_action_type", "reach", "frequency",
]

# Action types treated as a "conversion" (lead). These overlap in some setups:
# a form lead can appear as both "lead" and "offsite_conversion.fb_pixel_lead".
# Check which types your account reports and pass your own list if needed.
DEFAULT_CONVERSION_ACTIONS = (
    "lead",
    "offsite_conversion.fb_pixel_lead",
    "offsite_conversion.fb_pixel_complete_registration",
    "onsite_conversion.lead_grouped",
)


def normalize_account_id(account_id):
    """Return the ID with an 'act_' prefix. Raises ValueError if it is empty
    or not numeric after the prefix."""
    raw = (account_id or "").strip()
    digits = raw[4:] if raw.startswith("act_") else raw
    if not digits.isdigit():
        raise ValueError(f"Invalid ad account ID: {account_id!r} (expected e.g. act_1234567890)")
    return f"act_{digits}"


def extract_conversions(actions, action_types=DEFAULT_CONVERSION_ACTIONS):
    """Sum the values of matching action types in Meta's `actions` array."""
    total = 0
    for action in actions or []:
        if action.get("action_type") in action_types:
            total += int(float(action.get("value", 0)))
    return total


def time_range_param(start, end):
    return json.dumps({"since": start.isoformat(), "until": end.isoformat()},
                      separators=(",", ":"))


class MetaAdsClient:
    def __init__(self, account_id, token=None):
        import requests  # imported here so pure helpers work without it
        self._requests = requests
        self.token = token or os.environ.get("META_ACCESS_TOKEN")
        if not self.token:
            raise ValueError("META_ACCESS_TOKEN is not set")
        self.account_id = normalize_account_id(account_id)

    def _get(self, endpoint_or_url, params=None):
        url = endpoint_or_url if endpoint_or_url.startswith("http") else f"{BASE_URL}/{endpoint_or_url}"
        resp = self._requests.get(url, params=params or {}, timeout=TIMEOUT,
                                  headers={"Authorization": f"Bearer {self.token}"})
        if resp.status_code != 200:
            raise RuntimeError(f"Meta API error {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def _get_all(self, endpoint, params):
        """Follow cursor pagination and return the combined `data` list."""
        result = self._get(endpoint, params)
        data = list(result.get("data", []))
        while result.get("paging", {}).get("next"):
            result = self._get(result["paging"]["next"])
            data.extend(result.get("data", []))
        return data

    def get_account_info(self):
        return self._get(self.account_id, {
            "fields": "name,account_status,currency,timezone_name,amount_spent"})

    def get_campaigns(self, statuses=None):
        """List campaigns. statuses: e.g. ['ACTIVE', 'PAUSED']."""
        params = {"fields": "name,status,objective,daily_budget,lifetime_budget,start_time,stop_time",
                  "limit": 500}
        if statuses:
            params["filtering"] = json.dumps(
                [{"field": "effective_status", "operator": "IN", "value": list(statuses)}])
        return self._get_all(f"{self.account_id}/campaigns", params)

    def get_insights(self, start, end, level="account", fields=None, breakdowns=None, daily=False):
        """Insights rows for a date range.

        level: account, campaign, adset or ad.
        daily: one row per day (time_increment=1).
        breakdowns: e.g. ['publisher_platform'].
        """
        params = {
            "time_range": time_range_param(start, end),
            "level": level,
            "fields": ",".join(fields or DEFAULT_INSIGHT_FIELDS),
            "limit": 500,
        }
        if daily:
            params["time_increment"] = 1
        if breakdowns:
            params["breakdowns"] = ",".join(breakdowns)
        return self._get_all(f"{self.account_id}/insights", params)


def main():
    ap = argparse.ArgumentParser(description="Read-only Meta Marketing API client")
    ap.add_argument("account_id", help="Ad account ID, e.g. act_1234567890")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("info")
    p = sub.add_parser("campaigns")
    p.add_argument("--status", action="append", help="Effective status filter (repeatable)")
    p = sub.add_parser("insights")
    p.add_argument("--since", required=True, type=date.fromisoformat)
    p.add_argument("--until", required=True, type=date.fromisoformat)
    p.add_argument("--level", default="account", choices=["account", "campaign", "adset", "ad"])
    p.add_argument("--daily", action="store_true")
    args = ap.parse_args()

    try:
        client = MetaAdsClient(args.account_id)
        if args.command == "info":
            result = client.get_account_info()
        elif args.command == "campaigns":
            result = client.get_campaigns(args.status)
        else:
            result = client.get_insights(args.since, args.until, args.level, daily=args.daily)
    except (ValueError, RuntimeError) as e:
        sys.exit(str(e))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
