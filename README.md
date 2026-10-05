# marketing-analytics-scripts

Small command-line scripts for pulling marketing numbers out of Google Analytics 4, the Meta Marketing API and Google Tag Manager. Each script is independent, prints plain text or Markdown, and can optionally save its output. The reports are read-only. The one script that can change anything (`gtm/gtm.py`) prints a dry run unless you pass `--apply`.

These started as internal reporting scripts. The IDs, names and paths have been removed; everything is configured with arguments or environment variables.

## What each script answers

| Script | Question |
|---|---|
| `ga4/paid_traffic_report.py` | How does paid traffic engage, by channel, source/medium, campaign and landing page? |
| `ga4/organic_report.py` | How much traffic is organic, how is it trending by month, and which landing pages bring key events? |
| `ga4/ai_assistant_ads_report.py` | Do sessions from ads inside an AI assistant engage differently from other paid traffic? |
| `ga4/email_launch_monitor.py` | Is traffic arriving after an email send, from which email, to which page, and did it trigger key events? |
| `ga4/broken_links_404_audit.py` | Which URLs return a 404 page, how often, and who links to them? |
| `meta/meta_ads_client.py` | Read-only wrapper for ad account info, campaigns and insights (also a small CLI). |
| `meta/daily_report.py` | How did yesterday compare to the last 7 days, how is the month pacing, and is anything off? |
| `gtm/gtm.py` | What is in this GTM workspace, what looks wrong, and (with `--apply`) pause, delete, version or publish. |

## Setup

```
pip install -r requirements.txt
```

Python 3.9 or newer.

### GA4

1. In Google Cloud, create a project (or use an existing one) and enable the **Google Analytics Data API**.
2. Create a service account and download its JSON key. Keep the key out of the repo (`.gitignore` already excludes `*service-account*.json`).
3. In GA4, go to Admin > Property access management and add the service account's email address as a **Viewer**.
4. Find your numeric property ID in Admin > Property details (not the `G-` measurement ID).

```
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
export GA4_PROPERTY_ID=123456789        # or pass --property on each run
```

### Meta

1. Create a Meta developer app and a system user (or use a user token) with the `ads_read` permission on the ad account.
2. Export the token and pass the ad account ID as an argument:

```
export META_ACCESS_TOKEN=...
python3 meta/daily_report.py act_1234567890
```

The token goes in an `Authorization` header, not in URLs. Do not paste it into scripts or commit it. `META_API_VERSION` overrides the default Graph API version.

### Google Tag Manager

1. Enable the **Tag Manager API** in the same Google Cloud project.
2. In GTM, Admin > User management, add the service account's email to the account or container. Read commands need read access; `--apply` commands need edit (and publish, for `publish`) permission.
3. Use the numeric IDs from the GTM URL (`accounts/<id>/containers/<id>/workspaces/<id>`), not the `GTM-XXXXXXX` public ID:

```
export GTM_ACCOUNT_ID=1234567890
export GTM_CONTAINER_ID=12345678
export GTM_WORKSPACE_ID=1
```

## Usage

```
# GA4: dates are YYYY-MM-DD or GA4 relative values like 30daysAgo / today
python3 ga4/paid_traffic_report.py --start 2026-01-01 --end 2026-01-31 --output output/paid.txt
python3 ga4/organic_report.py --start 365daysAgo --end today --json-out output/organic.json
python3 ga4/ai_assistant_ads_report.py --source-contains chatgpt --source-contains perplexity
python3 ga4/email_launch_monitor.py --campaign spring_launch --path-contains /webinar
python3 ga4/broken_links_404_audit.py --hostname www.example.com \
    --start 2026-01-01 --end 2026-01-31 --output-dir output/404-audit

# Meta
python3 meta/meta_ads_client.py act_1234567890 insights --since 2026-01-01 --until 2026-01-07 --level campaign
python3 meta/daily_report.py act_1234567890 --date 2026-01-15 --month-budget 5000

# GTM: reads
python3 gtm/gtm.py workspaces list
python3 gtm/gtm.py tags list
python3 gtm/gtm.py audit
# GTM: writes print a plan; add --apply to run them
python3 gtm/gtm.py tags pause 12
python3 gtm/gtm.py tags pause 12 --apply
python3 gtm/gtm.py create-version --name "Cleanup" --apply
python3 gtm/gtm.py publish 34 --apply
```

Run `--help` on any script for all options.

## Tests

```
python3 -m unittest discover -s tests
```

The tests cover the pure logic (paid classification, formatting, URL normalization, segment matching, Meta metric math, GTM audit rules, the `--apply` default). They do not call any API.

## GA4 metric gotchas

These are the places where a script's numbers most often disagree with what you see in the GA4 interface.

- **Average engagement time per session is `userEngagementDuration / sessions`.** `userEngagementDuration` is total engaged seconds for the rows in the report. Dividing by sessions matches the "Average engagement time per session" column in the UI. `averageSessionDuration` is a different measure that includes idle time and gives larger numbers.
- **`engagementRate` is a ratio.** Never average it across rows. For a total, request it with no dimension, or compute `engagedSessions / sessions` from the counts.
- **Users are not additive.** `totalUsers` is de-duplicated within a row. Summing rows (by campaign, by day) overcounts people who appear in several rows. The paid report prints a no-dimension total for this reason; the 404 audit's merged user counts are an upper bound.
- **Sessions vs. active users.** `sessions` and `totalUsers` are session-scoped when paired with `session*` dimensions. Mixing in event-scoped dimensions such as `pagePath` changes what the numbers mean (see the "top pages viewed" section of the AI assistant report, which uses `activeUsers` and `screenPageViews`).
- **Key events vs. conversions.** GA4 renamed conversions to key events. The scripts try `keyEvents` and fall back to `conversions` for older properties, and say which one they used.
- **Channel group vs. medium.** The paid filter matches a session if its default channel group is Paid Search / Paid Social / Display / Paid Other, or its medium is `cpc` or `ppc`, or contains `paid` or `sponsored`. The medium rules catch custom-tagged links that GA4 did not group as paid, but they can also include things you do not consider ads. Check the source/medium table.
- **UTM tagging decides attribution.** The AI assistant and email scripts only see traffic whose links carry the expected `utm_source` / `utm_medium`. Untagged clicks land in direct or referral. The AI assistant segment is `source contains <term> AND medium contains paid`; organic referrals from the same product are excluded on purpose.
- **Realtime vs. standard reports.** The email monitor's realtime sections cover about 30 minutes. Its "today" sections come from standard reports, which lag; an empty table shortly after a send is not necessarily an error.
- **404 detection uses page titles.** It finds error pages by `pageTitle`, so it depends on your 404 template having a recognisable title and on the URL staying on the broken path. The default pattern `error` is loose; pass `--pattern` to tighten it.
- **Date ranges are in the property's time zone.** Relative values like `today` and `30daysAgo` follow the property's reporting time zone.

## Meta notes

- Conversions are counted from the `actions` array using a list of action types (`lead`, pixel lead, pixel registration, grouped on-site lead). These can describe the same event, so the sum may double count. Check against Ads Manager, and use `--conversion-types` to count only what you trust.
- The benchmark defaults in `daily_report.py` are placeholders. Set your own with `--ctr-target`, `--cpc-target`, `--cpm-target`, `--cpl-target` and `--cpc-critical`.
- The month-end projection is a straight line from month-to-date spend. It ignores weekday patterns and budget changes.

## GTM audit checks

`gtm.py audit` runs heuristics, not a verdict. It reports paused tags, active tags with no trigger (these can be fired by tag sequencing), duplicate tag names, custom HTML tags, legacy Universal Analytics tags, GA4 measurement IDs typed directly into tags, triggers no tag uses, and variables nothing references. Variables can be used by features the check cannot see, so verify before deleting anything.

Publishing a version changes the live site. Use `create-version` and `publish` deliberately, and preview in GTM first.

## License

MIT. See `LICENSE`.
