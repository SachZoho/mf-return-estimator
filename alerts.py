"""
Alert system — manages alert configurations, checks fund returns, and sends
email notifications when estimated returns are negative.

Alert configs are stored in alerts.csv in the GitHub repo (shared between
the Streamlit app and the GitHub Actions cron job).

CSV format: email,scheme_code,scheme_name,created_at
"""

import os
import csv
import io
import smtplib
import requests
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple

from mf_data import fetch_holdings
from stock_data import resolve_ticker, fetch_price_changes


ALERTS_CSV_PATH = "alerts.csv"
CSV_HEADERS = ["email", "scheme_code", "scheme_name", "created_at"]
GITHUB_API = "https://api.github.com"


# ---------------------------------------------------------------------------
# Local CSV management
# ---------------------------------------------------------------------------

def read_alerts_local(filepath: str = ALERTS_CSV_PATH) -> List[Dict]:
    alerts = []
    if not os.path.exists(filepath):
        return alerts
    try:
        with open(filepath, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                alerts.append(row)
    except Exception:
        pass
    return alerts


def append_alert_local(filepath: str, email: str, scheme_code: str, scheme_name: str) -> bool:
    file_exists = os.path.exists(filepath)
    try:
        with open(filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "email": email,
                "scheme_code": str(scheme_code),
                "scheme_name": scheme_name,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# GitHub API — read/write alerts.csv
# ---------------------------------------------------------------------------

def read_alerts_github(token: str, owner: str, repo: str, path: str = ALERTS_CSV_PATH,
                        branch: str = "main") -> Tuple[List[Dict], Optional[str]]:
    """Read alerts.csv from GitHub repo. Returns (alerts_list, file_sha)."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    params = {"ref": branch}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code == 404:
            return [], None
        if resp.status_code != 200:
            return [], None
        data = resp.json()
        sha = data.get("sha")
        content = base64.b64decode(data.get("content", "")).decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        alerts = list(reader)
        return alerts, sha
    except Exception:
        return [], None


def save_alert_github(token: str, owner: str, repo: str, email: str,
                      scheme_code: str, scheme_name: str,
                      path: str = ALERTS_CSV_PATH, branch: str = "main") -> Tuple[bool, str]:
    """Save a new alert to alerts.csv in the GitHub repo."""
    alerts, sha = read_alerts_github(token, owner, repo, path, branch)

    for a in alerts:
        if a.get("email", "").lower() == email.lower() and a.get("scheme_code") == str(scheme_code):
            return False, "Alert already exists for this email and fund."

    alerts.append({
        "email": email,
        "scheme_code": str(scheme_code),
        "scheme_name": scheme_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_HEADERS)
    writer.writeheader()
    writer.writerows(alerts)
    csv_content = output.getvalue()

    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    payload = {
        "message": f"Add alert: {email} -> {scheme_name[:50]}",
        "content": base64.b64encode(csv_content.encode("utf-8")).decode("utf-8"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    try:
        resp = requests.put(url, headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201):
            return True, "Alert saved successfully."
        return False, f"GitHub API error: HTTP {resp.status_code}"
    except Exception as e:
        return False, f"Error: {str(e)[:100]}"


def remove_alert_github(token: str, owner: str, repo: str, email: str, scheme_code: str,
                        path: str = ALERTS_CSV_PATH, branch: str = "main") -> Tuple[bool, str]:
    """Remove an alert from the CSV."""
    alerts, sha = read_alerts_github(token, owner, repo, path, branch)
    if sha is None:
        return False, "alerts.csv not found"

    original_len = len(alerts)
    alerts = [a for a in alerts if not (
        a.get("email", "").lower() == email.lower() and
        a.get("scheme_code") == str(scheme_code)
    )]

    if len(alerts) == original_len:
        return False, "Alert not found."

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_HEADERS)
    writer.writeheader()
    writer.writerows(alerts)
    csv_content = output.getvalue()

    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    payload = {
        "message": f"Remove alert: {email} -> scheme {scheme_code}",
        "content": base64.b64encode(csv_content.encode("utf-8")).decode("utf-8"),
        "sha": sha,
        "branch": branch,
    }
    try:
        resp = requests.put(url, headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201):
            return True, "Alert removed."
        return False, f"GitHub API error: HTTP {resp.status_code}"
    except Exception as e:
        return False, f"Error: {str(e)[:100]}"


# ---------------------------------------------------------------------------
# Return Calculation
# ---------------------------------------------------------------------------

def compute_fund_return(scheme_code: str, scheme_name: str) -> Tuple[Optional[float], str]:
    """Fetch holdings, resolve tickers, fetch prices, compute weighted return."""
    holdings, source = fetch_holdings(scheme_name, scheme_code)
    if not holdings:
        return None, f"Could not fetch holdings (source: {source})"

    equity_holdings = [h for h in holdings
                       if h.get("instrument", "").lower() in ("equity", "stock", "foreign equity")]
    if not equity_holdings:
        return None, "No equity holdings found"

    ticker_map = {}
    for h in equity_holdings:
        ticker = resolve_ticker(h["name"])
        if ticker:
            ticker_map[h["name"]] = ticker

    if not ticker_map:
        return None, f"Could not resolve any tickers from {len(equity_holdings)} holdings"

    tickers = list(set(ticker_map.values()))
    price_data = fetch_price_changes(tickers)

    if not price_data:
        return None, "Could not fetch any price data"

    total_return = 0.0
    total_weight = 0.0
    resolved_count = 0
    positive = []
    negative = []

    for h in equity_holdings:
        name = h["name"]
        weight = h["weight"]
        ticker = ticker_map.get(name)
        if ticker and ticker in price_data:
            change_pct = price_data[ticker]["change_pct"]
            contribution = (weight / 100) * change_pct
            total_return += contribution
            total_weight += weight
            resolved_count += 1
            if contribution > 0:
                positive.append((name, contribution))
            elif contribution < 0:
                negative.append((name, contribution))

    coverage = total_weight / sum(h["weight"] for h in equity_holdings) * 100 if equity_holdings else 0

    details = (f"Fund: {scheme_name}\n"
               f"Estimated Return: {total_return:+.4f}%\n"
               f"Coverage: {resolved_count}/{len(equity_holdings)} holdings ({coverage:.1f}% weight)\n"
               f"Data source: {source}\n\n"
               f"Top Negative Contributors:\n"
               + "\n".join(f"  {n}: {c:+.4f}%" for n, c in sorted(negative, key=lambda x: x[1])[:5])
               + f"\n\nTop Positive Contributors:\n"
               + "\n".join(f"  {n}: {c:+.4f}%" for n, c in sorted(positive, key=lambda x: -x[1])[:5]))

    return total_return, details


# ---------------------------------------------------------------------------
# Email Notification
# ---------------------------------------------------------------------------

def send_alert_email(to_email: str, fund_name: str, estimated_return: float,
                     details: str, sender_email: str, sender_password: str) -> Tuple[bool, str]:
    """Send an email alert about negative return via Gmail SMTP."""
    subject = f"⚠️ MF Alert: {fund_name[:40]} is down {estimated_return:.4f}%"

    html_body = f"""
    <html><body style="font-family: Arial, sans-serif; color: #333;">
    <div style="max-width: 600px; margin: 0 auto;">
        <h2 style="color: #dc2626;">⚠️ Negative Return Alert</h2>
        <p>Your tracked mutual fund has an estimated negative return today.</p>
        <table style="border-collapse: collapse; width: 100%; margin: 15px 0;">
            <tr><td style="padding: 8px; font-weight: bold;">Fund:</td><td style="padding: 8px;">{fund_name}</td></tr>
            <tr><td style="padding: 8px; font-weight: bold;">Estimated Return:</td>
                <td style="padding: 8px; color: #dc2626; font-weight: bold; font-size: 1.2em;">{estimated_return:+.4f}%</td></tr>
            <tr><td style="padding: 8px; font-weight: bold;">Checked at:</td><td style="padding: 8px;">{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</td></tr>
        </table>
        <h3 style="color: #666;">Detailed Breakdown</h3>
        <pre style="background: #f8f8f8; padding: 15px; border-radius: 5px; font-size: 0.85em; white-space: pre-wrap;">{details}</pre>
        <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
        <p style="font-size: 0.8em; color: #999;">This is an automated alert from MF Return Estimator.
        The return is estimated from the fund's latest disclosed holdings and current stock prices.
        Actual NAV may differ.</p>
    </div>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"MF Return Estimator <{sender_email}>"
    msg["To"] = to_email
    msg.attach(MIMEText(details, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, msg.as_string())
        return True, "Email sent successfully."
    except Exception as e:
        return False, f"Email error: {str(e)[:100]}"


# ---------------------------------------------------------------------------
# Main Alert Checker
# ---------------------------------------------------------------------------

def run_alert_checks(alerts: List[Dict], sender_email: str, sender_password: str) -> List[Dict]:
    """Check all alerts and send emails for negative returns."""
    results = []
    for alert in alerts:
        email = alert.get("email", "")
        scheme_code = alert.get("scheme_code", "")
        scheme_name = alert.get("scheme_name", "")

        print(f"\nChecking: {email} -> {scheme_name[:60]}")

        est_return, details = compute_fund_return(scheme_code, scheme_name)

        if est_return is None:
            print(f"  ❌ Could not compute return: {details[:80]}")
            results.append({"email": email, "fund": scheme_name,
                           "return": None, "email_sent": False, "error": details[:100]})
            continue

        print(f"  📊 Estimated return: {est_return:+.4f}%")

        if est_return < 0:
            print(f"  ⚠️ Negative! Sending alert email to {email}...")
            sent, msg = send_alert_email(email, scheme_name, est_return, details,
                                         sender_email, sender_password)
            if sent:
                print(f"  ✅ Email sent to {email}")
            else:
                print(f"  ❌ Email failed: {msg}")
            results.append({"email": email, "fund": scheme_name,
                           "return": est_return, "email_sent": sent, "error": msg if not sent else ""})
        else:
            print(f"  ✅ Positive return — no alert needed.")
            results.append({"email": email, "fund": scheme_name,
                           "return": est_return, "email_sent": False, "error": ""})

    return results
