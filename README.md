# Milan Data Science Job Hunter

A €0/month, serverless job discovery and outreach pipeline for **Data Science and ML/AI roles in Milan & Remote Italy**. Powered by Python, GitHub Actions, the Gemini API, Telegram, and Gmail IMAP Drafts.

## What It Does
1. **Multi-ATS Discovery (`job_hunter.py`):** Queries public JSON endpoints for **Greenhouse**, **Lever EU**, and **Ashby** across 20+ Milan/EMEA tech and fintech companies.
2. **AI Triage & Scoring:** Evaluates each new role with `gemini-3.5-flash-lite` against your actual PDF CV (`Tushar_Sinha_CV.pdf`), filtering out senior-only or native-Italian-only listings.
3. **Instant Telegram Alerts:** Sends daily digests for matches scoring 75+ with direct **Apply**, **Hiring Manager**, and **Recruiter** LinkedIn search links.
4. **Enterprise Cold Outreach (`outreach_drafter.py`):** Generates tailored cold emails, LinkedIn notes, and 3 Before -> After CV bullet rewrites for 10 major Milan enterprise employers (Pirelli, NTT DATA, PwC Italy, Eni, Generali, Intesa Sanpaolo, Reply, BIP, Accenture, Sky Italia) and pushes them directly to **Gmail Drafts** with your PDF CV attached.
5. **5-Day Follow-Up Tracker:** Logs sent outreach in `outreach_log.json`, auto-drafts a short bump email in Gmail Drafts after 5 days, and sends a Telegram reminder.
6. **Sunday Weekly Digest (`weekly_summary.py`):** Sends a weekly Telegram summary of roles found, application backlog, and pending follow-ups.

## Required GitHub Secrets
Add these under **Settings -> Secrets and variables -> Actions** in your **private** repository:

| Secret | Where to Get It |
| :--- | :--- |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/) (free tier) |
| `TELEGRAM_BOT_TOKEN` | Telegram `@BotFather` (`/newbot`) |
| `TELEGRAM_CHAT_ID` | Telegram `@userinfobot` |
| `GMAIL_EMAIL` | Your full Gmail address |
| `GMAIL_APP_PASSWORD` | `myaccount.google.com/apppasswords` (16 chars, no spaces) |

## Quick Local Setup & Dry Run
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY="your_api_key_here"

# Test scraping & Gemini CV scoring without touching files, Telegram, or Gmail
python job_hunter.py --dry-run --limit 5

# Preview the Sunday weekly digest
python weekly_summary.py --dry-run
```

## Local CLI Commands
```bash
# 1. Generate proactive cold emails & Gmail drafts for all 10 Milan enterprise employers
python outreach_drafter.py draft-enterprise

# 2. Log a sent email or LinkedIn message (starts the 5-day follow-up timer)
python outreach_drafter.py log --company "Pirelli" --contact "Mario Rossi" --email "mario.rossi@pirelli.com" --role "AI Intern"

# 3. Stop follow-up reminders once they reply
python outreach_drafter.py replied --company "Pirelli" --contact "Mario"

# 4. Manually run the 5-day follow-up check
python outreach_drafter.py check-followups
```

> **Note:** Place your `Tushar_Sinha_CV.pdf` in the root of this private repository before pushing so GitHub Actions can score roles against your CV and attach it to Gmail Drafts.
