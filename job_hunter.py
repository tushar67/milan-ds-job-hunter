import argparse
import csv
import html
import json
import os
from datetime import datetime
import requests
from google import genai
from google.genai import types

from outreach_drafter import (
    build_linkedin_search_urls,
    draft_outreach,
    extract_cv_text,
    push_to_gmail_drafts,
    save_drafts,
    suggest_cv_tweaks,
)

GREENHOUSE_SLUGS = [
    "scalapaysrl", "databricks", "speechify", "stripe", "datadog",
    "cloudflare", "canonical", "coinbase", "airbnb", "asana", "airtable",
]
LEVER_EU_SLUGS = ["prima", "objectway", "orasio"]
ASHBY_SLUGS = ["satispay", "sibill", "livia", "powco.ai", "enpal", "ancora"]

KEYWORDS = ["data", "machine learning", "ml", "ai", "nlp", "analytics", "scientist"]
SEEN_FILE = "seen_jobs.json"
CSV_FILE = "jobs.csv"

client = genai.Client()  # Reads GEMINI_API_KEY from environment

SCORE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "match_score": {"type": "INTEGER"},
        "italian_required": {"type": "STRING"},
        "seniority_fit": {"type": "STRING"},
        "outreach_hook": {"type": "STRING"},
    },
    "required": ["match_score", "italian_required", "seniority_fit", "outreach_hook"],
}


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, indent=2)


def fetch_greenhouse(slug):
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        return []
    jobs = []
    for j in resp.json().get("jobs", []):
        title = j.get("title", "")
        loc = j.get("location", {}).get("name", "")
        if any(k in title.lower() for k in KEYWORDS) and any(
            x in loc.lower() for x in ["milan", "milano", "italy", "remote"]
        ):
            jobs.append({
                "id": f"gh_{slug}_{j['id']}",
                "company": slug.capitalize(),
                "title": title,
                "location": loc,
                "url": j.get("absolute_url", ""),
                "description": j.get("content", "")[:4000],
            })
    return jobs


def fetch_lever_eu(slug):
    url = f"https://api.eu.lever.co/v0/postings/{slug}?mode=json"
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        return []
    jobs = []
    for j in resp.json():
        title = j.get("text", "")
        loc = j.get("categories", {}).get("location", "")
        if any(k in title.lower() for k in KEYWORDS) and any(
            x in loc.lower() for x in ["milan", "milano", "italy", "remote"]
        ):
            jobs.append({
                "id": f"lveu_{slug}_{j['id']}",
                "company": slug.capitalize(),
                "title": title,
                "location": loc,
                "url": j.get("hostedUrl", ""),
                "description": j.get("descriptionPlain", "")[:4000],
            })
    return jobs


def fetch_ashby(slug):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        return []
    jobs = []
    for j in resp.json().get("jobs", []):
        title = j.get("title", "")
        loc = j.get("location", "")
        if any(k in title.lower() for k in KEYWORDS) and any(
            x in loc.lower() for x in ["milan", "milano", "italy", "remote"]
        ):
            jobs.append({
                "id": f"ashby_{slug}_{j['id']}",
                "company": slug.capitalize(),
                "title": title,
                "location": loc,
                "url": j.get("jobUrl", ""),
                "description": j.get("descriptionPlain", "")[:4000],
            })
    return jobs


def score_job(job):
    cv_text = extract_cv_text()
    prompt = f"""
    Evaluate this job posting in Milan against the candidate's actual CV below.

    Candidate CV:
    {cv_text}

    Additional Context:
    - Currently based in Milan, Italy.
    - Fluent English, basic A1 Italian.

    Target Role: {job['title']} at {job['company']} ({job['location']})
    Job Description:
    {job['description']}

    Rules:
    - match_score: integer 0-100 based on concrete overlap between the CV's projects/stack and the job description.
    - italian_required: strictly one of "None/English", "Basic", or "Fluent Required".
    - seniority_fit: strictly "Good Fit" (Intern, Junior, Entry, Graduate, Associate) or "Too Senior" (3+ years required / Senior / Lead).
    - outreach_hook: 1-sentence tailored angle referencing a specific project or skill from the CV.
    """
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SCORE_SCHEMA,
        ),
    )
    return json.loads(response.text)


def send_telegram_alert(matches):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram credentials not set; skipping alert.")
        return

    header = f"<b>Milan DS Job Hunter: {len(matches)} New Match(es)</b>\n"
    blocks = []

    for m in matches:
        company = html.escape(m["Company"])
        role = html.escape(m["Role"])
        italian = html.escape(m["Italian"])
        hook = html.escape(m["Outreach_Hook"])
        apply_url = html.escape(m["URL"], quote=True)

        li_links = build_linkedin_search_urls(m["Company"])
        hm_url = html.escape(li_links["hiring_managers_url"], quote=True)
        rec_url = html.escape(li_links["recruiters_url"], quote=True)

        blocks.append(
            f"• <b>{role}</b> at <b>{company}</b> (Score: {m['Score']}/100)\n"
            f"  <i>Italian:</i> {italian}\n"
            f"  <i>Hook:</i> {hook}\n"
            f'  <a href="{apply_url}">Apply</a> | '
            f'<a href="{hm_url}">Hiring Managers</a> | '
            f'<a href="{rec_url}">Recruiters</a>\n'
        )

    chunks, current = [], header
    for block in blocks:
        if len(current) + len(block) > 3900:
            chunks.append(current)
            current = block
        else:
            current += "\n" + block
    if current:
        chunks.append(current)

    for chunk in chunks:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"Telegram alert failed: {resp.text}")


def main(dry_run=False, limit=None):
    seen = load_seen()
    all_jobs = []
    for slug in GREENHOUSE_SLUGS:
        all_jobs.extend(fetch_greenhouse(slug))
    for slug in LEVER_EU_SLUGS:
        all_jobs.extend(fetch_lever_eu(slug))
    for slug in ASHBY_SLUGS:
        all_jobs.extend(fetch_ashby(slug))

    unseen_jobs = [j for j in all_jobs if j["id"] not in seen]
    if limit:
        unseen_jobs = unseen_jobs[:limit]

    print(f"Fetched {len(all_jobs)} total roles; evaluating {len(unseen_jobs)} unseen role(s)...")

    new_matches = []
    for job in unseen_jobs:
        if not dry_run:
            seen.add(job["id"])

        try:
            result = score_job(job)
            passed = (
                result.get("match_score", 0) >= 75
                and result.get("italian_required") != "Fluent Required"
                and result.get("seniority_fit") == "Good Fit"
            )

            if dry_run:
                status = "MATCH" if passed else "SKIP"
                print(
                    f"[{status}] {job['company']} — {job['title']} ({job['location']})\n"
                    f"        Score: {result.get('match_score')}/100 | "
                    f"Italian: {result.get('italian_required')} | "
                    f"Seniority: {result.get('seniority_fit')}\n"
                    f"        Hook: {result.get('outreach_hook')}\n"
                )

            if passed:
                new_matches.append({
                    "Date": datetime.now().strftime("%Y-%m-%d"),
                    "Company": job["company"],
                    "Role": job["title"],
                    "Location": job["location"],
                    "Score": result["match_score"],
                    "Italian": result["italian_required"],
                    "Outreach_Hook": result["outreach_hook"],
                    "URL": job["url"],
                    "Status": "To Apply",
                    "Description": job["description"],
                })
        except Exception as e:
            print(f"Skipping {job['id']}: {e}")

    if dry_run:
        print(f"Dry run complete: {len(new_matches)} match(es) would have been logged and alerted.")
        return

    save_seen(seen)

    if new_matches:
        csv_fields = ["Date", "Company", "Role", "Location", "Score", "Italian", "Outreach_Hook", "URL", "Status"]
        file_exists = os.path.exists(CSV_FILE)
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            writer.writerows(new_matches)
        print(f"Added {len(new_matches)} new high-signal jobs to {CSV_FILE}.")

        send_telegram_alert(new_matches)

        email_drafts = []
        for m in new_matches:
            draft = draft_outreach(m["Company"], m["Role"], m["URL"])
            tweaks = suggest_cv_tweaks(m["Company"], m["Role"], m.get("Description", ""))
            email_drafts.append({
                "company": m["Company"],
                "role": m["Role"],
                "url": m["URL"],
                "cv_tweaks": tweaks,
                **draft,
            })
        save_drafts(email_drafts)
        push_to_gmail_drafts(email_drafts)
    else:
        print("No new matching jobs today.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Milan DS Job Hunter")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and score jobs locally without saving files, sending Telegram alerts, or creating Gmail drafts.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of unseen jobs to score (useful for quick local tests).",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run, limit=args.limit)
