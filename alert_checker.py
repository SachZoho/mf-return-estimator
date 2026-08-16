"""
Alert checker — standalone script that runs in GitHub Actions.
Reads alerts.csv from the repo, checks each fund's estimated return,
and sends email alerts for negative returns.

Environment variables needed (set as GitHub repo secrets):
- GITHUB_TOKEN: GitHub PAT with repo read access (to read alerts.csv)
- REPO_OWNER: GitHub repo owner
- REPO_NAME: GitHub repo name
- SENDER_EMAIL: Gmail address to send from
- SENDER_PASSWORD: Gmail app password

Usage:
    python alert_checker.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from alerts import read_alerts_github, run_alert_checks


def main():
    print("=" * 60)
    print("MF Return Estimator — Alert Checker")
    print("=" * 60)

    github_token = os.environ.get("GITHUB_TOKEN", "")
    repo_owner = os.environ.get("REPO_OWNER", "SachZoho")
    repo_name = os.environ.get("REPO_NAME", "mf-return-estimator")
    sender_email = os.environ.get("SENDER_EMAIL", "")
    sender_password = os.environ.get("SENDER_PASSWORD", "")

    missing = []
    if not github_token:
        missing.append("GITHUB_TOKEN")
    if not sender_email:
        missing.append("SENDER_EMAIL")
    if not sender_password:
        missing.append("SENDER_PASSWORD")

    if missing:
        print(f"\n❌ Missing environment variables: {', '.join(missing)}")
        print("Set these as GitHub repo secrets.")
        sys.exit(1)

    print(f"\nRepo: {repo_owner}/{repo_name}")
    print(f"Sender: {sender_email}")

    print("\n📖 Reading alerts.csv from GitHub...")
    alerts, sha = read_alerts_github(github_token, repo_owner, repo_name)

    if not alerts:
        print("ℹ️ No alerts configured. Exiting.")
        sys.exit(0)

    print(f"✅ Found {len(alerts)} alert(s) to check:")

    seen = set()
    unique_alerts = []
    for a in alerts:
        key = (a.get("email", "").lower(), a.get("scheme_code", ""))
        if key not in seen:
            seen.add(key)
            unique_alerts.append(a)
            print(f"   • {a.get('email', '')} -> {a.get('scheme_name', '')[:50]}")

    print(f"\n🔍 Checking {len(unique_alerts)} alert(s)...")
    results = run_alert_checks(unique_alerts, sender_email, sender_password)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    total = len(results)
    negative = sum(1 for r in results if r.get("return") is not None and r["return"] < 0)
    positive = sum(1 for r in results if r.get("return") is not None and r["return"] >= 0)
    errors = sum(1 for r in results if r.get("return") is None)
    emails_sent = sum(1 for r in results if r.get("email_sent"))

    print(f"Total alerts checked: {total}")
    print(f"  Positive returns:    {positive}")
    print(f"  Negative returns:    {negative}")
    print(f"  Errors:              {errors}")
    print(f"  Emails sent:         {emails_sent}")

    if errors:
        print("\n⚠️ Errors encountered:")
        for r in results:
            if r.get("return") is None:
                print(f"  {r['email']} -> {r['fund'][:40]}: {r.get('error', 'unknown')}")

    print("\nDone.")


if __name__ == "__main__":
    main()
