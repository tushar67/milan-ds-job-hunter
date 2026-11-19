import argparse
import html
import imaplib
import json
import os
import re
import time
from datetime import date, datetime
from email.message import EmailMessage
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

import requests
from google import genai
from google.genai import types
from pypdf import PdfReader

client = genai.Client()  # Automatically reads GEMINI_API_KEY from environment

DRAFTS_FILE = "outreach_drafts.md"
LOG_FILE = "outreach_log.json"
DEFAULT_RESUME_PATH = "Tushar_Sinha_CV.pdf"
FOLLOW_UP_DAYS = 5

CANDIDATE_PROFILE = """
Name: Tushar Sinha
Education: MSc in Data Science for Economics and Health, Università degli Studi di Milano (UniMi)
Prior Experience: Former Data/Tech professional at Datamatics
Core Stack: Python, SQL, PyTorch, NLP, Graph Neural Networks (GNNs), Docker, FastAPI, Git
Location: Milan, Italy (Fluent English, basic A1 Italian)
"""

ENTERPRISE_PROFILES = {
    "Pirelli": {
        "target_teams": "AI & Data Analytics for Process Transformation / Materials Lab",
        "milan_focus": "Physical AI, intelligent industrial operations, and data-driven manufacturing analytics in Milan",
        "tone": "Technical, concise, and focused on measurable operational impact",
    },
    "NTT DATA": {
        "target_teams": "Data & AI Consulting / GenAI Solutions (Milan)",
        "milan_focus": "Enterprise GenAI platforms, MLOps frameworks, and NLP/LLM intelligent document processing (Syntphony)",
        "tone": "Solution-oriented, emphasizing end-to-end delivery (FastAPI, Docker, NLP/ML)",
    },
    "PwC Italy": {
        "target_teams": "Digital Innovation / Data & AI Advisory (Milan)",
        "milan_focus": "Industrializing AI for enterprise clients, ML/Deep Learning Decision Support Systems, and agentic workflows",
        "tone": "Consultative, structured, bridging technical ML rigor with business value",
    },
    "Eni": {
        "target_teams": "Digital & Information Technology / AI & Supercomputing (San Donato Milanese)",
        "milan_focus": "Large-scale AI modeling and energy simulations powered by the HPC6 supercomputer and low-carbon AI data center initiatives",
        "tone": "Research-minded, emphasizing PyTorch, scalable compute, and quantitative modeling",
    },
    "Generali": {
        "target_teams": "Group Data & AI / Analytics & Telematics (Milan)",
        "milan_focus": "Insurance and asset management AI transformation, predictive telematics, and centralized data platforms backed by MIT research collaborations",
        "tone": "Structured, analytical, connecting ML modeling to risk, pricing, and customer lifecycle value",
    },
    "Intesa Sanpaolo": {
        "target_teams": "Data Office, Analytics & Trend Analysis / AI Transformation (Milan)",
        "milan_focus": "Enterprise banking AI transformation, applied Data Science for financial services, and large-scale NLP/analytics workflows",
        "tone": "Formal, precise, highlighting statistical rigor, NLP/GNNs, and production readiness",
    },
    "Reply": {
        "target_teams": "Data Reply / Technology Reply / Cluster Reply (Milan)",
        "milan_focus": "Agentic AI (Agent Factory, AI coworkers), Databricks Data + AI platforms, and scalable enterprise automation",
        "tone": "Fast-paced, hands-on engineering tone emphasizing Python, Docker, FastAPI, and agentic/LLM prototypes",
    },
    "BIP": {
        "target_teams": "BIP xTech — AI & Data Engineering (Milan)",
        "milan_focus": "Agentic AI (Agent Guard), conversational AI, and cloud-native Azure AI & Analytics for banking and industrial clients",
        "tone": "Pragmatic, tech-forward, emphasizing rapid prototyping and cloud/API deployment",
    },
    "Accenture": {
        "target_teams": "Accenture Data & AI / GenAI Studio (Milan)",
        "milan_focus": "Enterprise-scale Generative AI, cloud data modernization, and cross-industry ML industrialization",
        "tone": "Polished, impact-focused, balancing strong engineering fundamentals with client-ready communication",
    },
    "Sky Italia": {
        "target_teams": "Data Science & Analytics / Media & Streaming Insights (Milan Santa Giulia)",
        "milan_focus": "Content recommendation systems, audience analytics, churn prediction, and personalization across streaming platforms",
        "tone": "Product-oriented, highlighting recommender systems, user-behavior modeling, and Python/SQL",
    },
}

OUTREACH_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "subject": {"type": "STRING"},
        "email_body": {"type": "STRING"},
        "linkedin_note": {"type": "STRING"},
    },
    "required": ["subject", "email_body", "linkedin_note"],
}

CV_TWEAKS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "tweaks": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "target_section": {"type": "STRING"},
                    "original_bullet": {"type": "STRING"},
                    "rewritten_bullet": {"type": "STRING"},
                    "why_it_fits": {"type": "STRING"},
                },
                "required": [
                    "target_section",
                    "original_bullet",
                    "rewritten_bullet",
                    "why_it_fits",
                ],
            },
        }
    },
    "required": ["tweaks"],
}

FOLLOWUP_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "subject": {"type": "STRING"},
        "email_body": {"type": "STRING"},
    },
    "required": ["subject", "email_body"],
}


@lru_cache(maxsize=1)
def extract_cv_text(resume_path=DEFAULT_RESUME_PATH):
    pdf_file = Path(os.getenv("RESUME_PATH", resume_path))
    if not pdf_file.is_file():
        print(f"Warning: '{pdf_file}' not found. Falling back to CANDIDATE_PROFILE.")
        return CANDIDATE_PROFILE

    try:
        reader = PdfReader(str(pdf_file))
        pages = [page.extract_text() or "" for page in reader.pages]
        full_text = "\n".join(pages).strip()
        return full_text[:8000] if full_text else CANDIDATE_PROFILE
    except Exception as err:
        print(f"PDF text extraction failed ({err}); falling back to CANDIDATE_PROFILE.")
        return CANDIDATE_PROFILE


def build_linkedin_search_urls(company, city="Milan"):
    base_url = "https://www.linkedin.com/search/results/people/"
    location_clause = f'("{city}" OR "Milano")'

    hiring_manager_query = (
        f'"{company}" AND ("Head of Data" OR "Data Science Manager" OR "AI Lead" '
        f'OR "Machine Learning" OR "Analytics Director") AND {location_clause}'
    )
    recruiter_query = (
        f'"{company}" AND ("Talent Acquisition" OR "Recruiter" OR "HR") '
        f'AND ("Data" OR "AI" OR "Tech" OR "Digital") AND {location_clause}'
    )

    return {
        "hiring_managers_url": f"{base_url}?{urlencode({'keywords': hiring_manager_query, 'origin': 'FACETED_SEARCH'})}",
        "recruiters_url": f"{base_url}?{urlencode({'keywords': recruiter_query, 'origin': 'FACETED_SEARCH'})}",
    }


def draft_outreach(company, role_title="Data Science / ML & AI Internship or Junior Role", job_url=""):
    profile = ENTERPRISE_PROFILES.get(
        company,
        {
            "target_teams": "Data Science & AI Team",
            "milan_focus": "Applied Machine Learning and Data Science in Milan",
            "tone": "Professional, concise, and direct",
        },
    )

    prompt = f"""
    Write a cold-outreach email and a short LinkedIn connection note for a Data Science Master's student reaching out to a hiring manager or recruiter in Milan.

    Candidate:
    {CANDIDATE_PROFILE}

    Target Company: {company}
    Target Team: {profile['target_teams']}
    Company Focus in Milan: {profile['milan_focus']}
    Role of Interest: {role_title}
    Tone: {profile['tone']}

    Rules:
    - Write in crisp, natural English (appropriate for Milan international/tech teams).
    - Keep the email under 140 words. No generic fluff ("I hope this email finds you well").
    - Connect 1-2 specific candidate skills (e.g., PyTorch/NLP/GNNs, FastAPI/Docker, prior Datamatics experience) directly to the company's Milan focus.
    - End with a low-friction CTA (e.g., a 10-minute chat or sharing a GitHub portfolio/CV).
    - Keep the LinkedIn note strictly under 280 characters.
    """

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=OUTREACH_SCHEMA,
        ),
    )
    return json.loads(response.text)


def suggest_cv_tweaks(company, role_title, job_description):
    cv_text = extract_cv_text()

    prompt = f"""
    You are a technical career coach tailoring a candidate's existing CV for a Milan Data Science / ML role.

    Candidate's Actual CV Text:
    {cv_text}

    Target Role: {role_title} at {company}
    Job Description:
    {job_description[:4000]}

    Rules:
    - Pick the 3 existing bullet points from the candidate's CV that are most relevant to this job description.
    - Quote each chosen bullet verbatim in "original_bullet".
    - Rewrite each one in "rewritten_bullet" to mirror the job description's exact technical keywords and ATS phrasing.
    - Do NOT invent fake jobs, tools, or metrics—only reframe what is already in the CV (use [X%] if a metric is missing).
    - Keep each rewrite to 1–2 concise lines starting with a strong action verb.
    """

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CV_TWEAKS_SCHEMA,
        ),
    )
    return json.loads(response.text).get("tweaks", [])[:3]


def draft_followup_bump(entry, days_elapsed):
    prompt = f"""
    Write a short, polite follow-up ("bump") email from a Data Science Master's student in Milan
    who sent a cold outreach email {days_elapsed} days ago and hasn't heard back yet.

    Contact: {entry['contact']}
    Company: {entry['company']}
    Role of Interest: {entry['role']}

    Rules:
    - Keep it strictly under 65 words (3–4 sentences max).
    - Warm, respectful, and zero guilt-tripping.
    - Reiterate interest in {entry['company']}'s Milan Data/AI team and offer a quick 10-minute chat.
    - Subject line should start with "Re: " so it feels like a natural thread bump.
    """

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=FOLLOWUP_SCHEMA,
        ),
    )
    return json.loads(response.text)


def save_drafts(drafts):
    with open(DRAFTS_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n## Outreach Batch — {datetime.now().strftime('%Y-%m-%d')}\n\n")
        for d in drafts:
            links = build_linkedin_search_urls(d["company"])
            f.write(f"### {d['company']} — {d['role']}\n")
            if d.get("url"):
                f.write(f"- **Job Link:** {d['url']}\n")
            f.write(
                f"- **Find People on LinkedIn:** "
                f"[Hiring Managers]({links['hiring_managers_url']}) | "
                f"[Tech Recruiters]({links['recruiters_url']})\n"
            )
            f.write(f"- **Subject:** `{d['subject']}`\n\n")
            f.write(f"{d['email_body']}\n\n")
            if d.get("linkedin_note"):
                f.write(f"**LinkedIn Note:**\n> {d['linkedin_note']}\n\n")
            if d.get("cv_tweaks"):
                f.write("**3 Tailored CV Bullet Rewrites (Before → After):**\n")
                for i, t in enumerate(d["cv_tweaks"], 1):
                    f.write(
                        f"{i}. **[{t['target_section']}]**\n"
                        f"   - *Original:* {t['original_bullet']}\n"
                        f"   - *Rewritten:* {t['rewritten_bullet']}\n"
                        f"   - *Why:* {t['why_it_fits']}\n"
                    )
                f.write("\n")
            f.write("---\n\n")


def _get_drafts_mailbox(imap):
    """Detects Gmail's Drafts folder regardless of account language (e.g., Drafts vs Bozze)."""
    status, folders = imap.list()
    if status == "OK":
        for folder in folders:
            decoded = folder.decode("utf-8", errors="ignore")
            if r"\Drafts" in decoded:
                match = re.search(r'"([^"]+)"$', decoded)
                name = match.group(1) if match else decoded.split()[-1]
                return f'"{name}"' if not name.startswith('"') else name
    return '"[Gmail]/Drafts"'


def push_to_gmail_drafts(drafts, resume_path=DEFAULT_RESUME_PATH):
    gmail_user = os.getenv("GMAIL_EMAIL")
    app_password = os.getenv("GMAIL_APP_PASSWORD")
    if not gmail_user or not app_password:
        print("Gmail credentials not set; skipping Gmail Drafts upload.")
        return

    pdf_bytes = None
    pdf_file = Path(os.getenv("RESUME_PATH", resume_path))
    if pdf_file.is_file():
        pdf_bytes = pdf_file.read_bytes()
    else:
        print(f"Warning: '{pdf_file}' not found. Creating drafts without attachment.")

    with imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=30) as imap:
        imap.login(gmail_user, app_password)
        drafts_box = _get_drafts_mailbox(imap)

        for d in drafts:
            msg = EmailMessage()
            msg["From"] = gmail_user
            msg["Subject"] = d["subject"]
            if d.get("to_email"):
                msg["To"] = d["to_email"]
            msg.set_content(d["email_body"])

            if pdf_bytes:
                msg.add_attachment(
                    pdf_bytes,
                    maintype="application",
                    subtype="pdf",
                    filename=pdf_file.name,
                )

            status, resp = imap.append(
                drafts_box,
                r"(\Draft)",
                imaplib.Time2Internaldate(time.time()),
                msg.as_bytes(),
            )
            if status != "OK":
                print(f"Failed to save draft for {d['company']}: {resp}")

    print(f"Saved {len(drafts)} draft(s) directly to Gmail Drafts.")


def run_enterprise_outreach():
    drafts = []
    for company, meta in ENTERPRISE_PROFILES.items():
        try:
            res = draft_outreach(company, meta["target_teams"])
            drafts.append({
                "company": company,
                "role": meta["target_teams"],
                "url": "",
                **res,
            })
        except Exception as err:
            print(f"Failed to draft outreach for {company}: {err}")

    if drafts:
        save_drafts(drafts)
        push_to_gmail_drafts(drafts)
        print(f"Saved {len(drafts)} enterprise outreach drafts to {DRAFTS_FILE} and Gmail Drafts.")


def _load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_log(entries):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def log_outreach(company, contact, role="Data Science / AI", email=""):
    entries = _load_log()
    entries.append({
        "company": company,
        "contact": contact,
        "email": email,
        "role": role,
        "sent_date": date.today().isoformat(),
        "status": "sent",  # sent | reminded | replied
    })
    _save_log(entries)
    print(f"Logged outreach to {contact} at {company}. Follow-up due in {FOLLOW_UP_DAYS} days.")


def mark_replied(company, contact=None):
    entries = _load_log()
    updated = 0
    for e in entries:
        if e["company"].lower() == company.lower() and (
            not contact or contact.lower() in e["contact"].lower()
        ):
            e["status"] = "replied"
            updated += 1
    _save_log(entries)
    print(f"Marked {updated} entry(ies) for {company} as replied.")


def check_followups():
    entries = _load_log()
    today = date.today()
    due = []

    for e in entries:
        if e["status"] != "sent":
            continue
        days_elapsed = (today - date.fromisoformat(e["sent_date"])).days
        if days_elapsed >= FOLLOW_UP_DAYS:
            due.append((e, days_elapsed))

    if not due:
        print("No follow-ups due today.")
        return

    followup_drafts = []
    for e, days in due:
        try:
            bump = draft_followup_bump(e, days)
            followup_drafts.append({
                "company": e["company"],
                "role": e["role"],
                "to_email": e.get("email", ""),
                **bump,
            })
        except Exception as err:
            print(f"Failed to draft follow-up for {e['company']}: {err}")

    if followup_drafts:
        push_to_gmail_drafts(followup_drafts)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram credentials not set; bump drafts saved in Gmail.")
        return

    lines = [f"<b>Follow-Up Reminder ({len(due)} due)</b>\n"]
    for e, days in due:
        company = html.escape(e["company"])
        contact = html.escape(e["contact"])
        role = html.escape(e["role"])
        lines.append(
            f"• <b>{contact}</b> at <b>{company}</b> ({role})\n"
            f"  <i>Sent {days} days ago ({e['sent_date']}) — bump draft saved in Gmail Drafts.</i>\n"
        )

    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": "\n".join(lines)[:4000],
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        },
        timeout=15,
    )
    if resp.status_code == 200:
        for e, _ in due:
            e["status"] = "reminded"
        _save_log(entries)
        print(f"Sent Telegram nudge and saved {len(followup_drafts)} Gmail bump draft(s).")
    else:
        print(f"Telegram reminder failed: {resp.text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Milan DS Outreach Drafter & Tracker")
    sub = parser.add_subparsers(dest="cmd")

    p_log = sub.add_parser("log", help="Log a sent email or LinkedIn message")
    p_log.add_argument("--company", required=True)
    p_log.add_argument("--contact", required=True)
    p_log.add_argument("--role", default="Data Science / AI")
    p_log.add_argument("--email", default="")

    p_rep = sub.add_parser("replied", help="Mark a contact as replied")
    p_rep.add_argument("--company", required=True)
    p_rep.add_argument("--contact", default=None)

    sub.add_parser("check-followups", help="Check for 5-day overdue replies, draft bumps, and alert Telegram")
    sub.add_parser("draft-enterprise", help="Generate drafts for all 10 ENTERPRISE_PROFILES")

    args = parser.parse_args()
    if args.cmd == "log":
        log_outreach(args.company, args.contact, args.role, args.email)
    elif args.cmd == "replied":
        mark_replied(args.company, args.contact)
    elif args.cmd == "check-followups":
        check_followups()
    else:
        run_enterprise_outreach()
