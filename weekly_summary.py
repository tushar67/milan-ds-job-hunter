import argparse
import csv
import html
import json
import os
from datetime import date, timedelta
import requests

CSV_FILE = "jobs.csv"
LOG_FILE = "outreach_log.json"
LOOKBACK_DAYS = 7


def load_jobs():
    if not os.path.exists(CSV_FILE):
        return []
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_outreach():
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_summary():
    today = date.today()
    cutoff = today - timedelta(days=LOOKBACK_DAYS)

    jobs = load_jobs()
    outreach = load_outreach()

    weekly_jobs = []
    for j in jobs:
        try:
            if date.fromisoformat(j.get("Date", "")) >= cutoff:
                weekly_jobs.append(j)
        except ValueError:
            continue

    to_apply_total = sum(1 for j in jobs if j.get("Status", "").strip().lower() == "to apply")
    applied_total = sum(1 for j in jobs if j.get("Status", "").strip().lower() == "applied")

    top_weekly = sorted(
        weekly_jobs,
        key=lambda x: int(x.get("Score", 0) or 0),
        reverse=True,
    )[:3]

    weekly_sent = []
    pending_followups = []
    replied_total = 0

    for e in outreach:
        status = e.get("status", "")
        if status == "replied":
            replied_total += 1
        try:
            sent_dt = date.fromisoformat(e.get("sent_date", ""))
        except ValueError:
            continue

        if sent_dt >= cutoff:
            weekly_sent.append(e)
        if status in ("sent", "reminded"):
            days_ago = (today - sent_dt).days
            pending_followups.append((e, days_ago))

    pending_followups.sort(key=lambda pair: pair[1], reverse=True)

    lines = [
        f"<b>Milan DS Job Hunter — Weekly Digest ({cutoff.isoformat()} to {today.isoformat()})</b>\n",
        "<b>Pipeline Snapshot</b>",
        f"• New high-signal roles found (7d): <b>{len(weekly_jobs)}</b>",
        f"• Backlog still marked <i>To Apply</i>: <b>{to_apply_total}</b> | Applied: <b>{applied_total}</b>",
        f"• Outreach messages logged (7d): <b>{len(weekly_sent)}</b>",
        f"• Total replies received: <b>{replied_total}</b>\n",
    ]

    if top_weekly:
        lines.append("<b>Top Roles Found This Week</b>")
        for j in top_weekly:
            role = html.escape(j.get("Role", "Unknown"))
            company = html.escape(j.get("Company", "Unknown"))
            score = html.escape(str(j.get("Score", "-")))
            url = html.escape(j.get("URL", ""), quote=True)
            lines.append(f'• <a href="{url}">{role}</a> at <b>{company}</b> ({score}/100)')
        lines.append("")
    else:
        lines.append("<i>No new roles matched your threshold this week.</i>\n")

    if pending_followups:
        lines.append(f"<b>Pending Follow-Ups ({len(pending_followups)})</b>")
        for e, days in pending_followups[:8]:
            contact = html.escape(e.get("contact", "Unknown"))
            company = html.escape(e.get("company", "Unknown"))
            flag = " — bump draft ready" if e.get("status") == "reminded" else ""
            lines.append(f"• <b>{contact}</b> ({company}) — {days}d ago{flag}")
    else:
        lines.append("<b>Pending Follow-Ups:</b> None — inbox is clear.")

    return "\n".join(lines)[:4000]


def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram credentials not set; skipping send.")
        return

    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        },
        timeout=15,
    )
    if resp.status_code == 200:
        print("Weekly Telegram digest sent.")
    else:
        print(f"Telegram digest failed: {resp.text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send Sunday weekly Milan DS Job Hunter digest")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the formatted digest to the terminal without sending it to Telegram.",
    )
    args = parser.parse_args()

    digest = build_summary()
    if args.dry_run:
        print(digest)
    else:
        send_telegram(digest)
