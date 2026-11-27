"""Scholarship discovery + Gemini eligibility engine."""
import os, sys, json, time, hashlib, datetime as dt
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_FILE = DATA_DIR / "scholarships.json"
SEEN_FILE = DATA_DIR / "seen.json"
PROFILE = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"


def call_groq(prompt: str, system_prompt: str = "You return clean structured scholarship data.") -> str:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is missing.")
    response = requests.post(
        GROQ_URL,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()
# Add more RSS URLs here (e.g. a DAAD feed if you find a working one).
FEEDS = [
    "https://www.scholars4dev.com/feed/",
    "https://opportunitydesk.org/feed/",
    "https://www.scholarship-positions.com/feed/",
    "https://www.youthop.com/feed",
    "https://www.opportunitiesforyouth.org/feed/",
]
PER_FEED = 25
MAX_NEW = int(os.getenv("MAX_NEW_PER_RUN", "12"))   # keeps within Gemini free-tier limits
SLEEP_BETWEEN_CALLS = 7                              # seconds (free tier ~10 requests/min)
MODEL = "gemini-3.8-flash"
UA = {"User-Agent": "Mozilla/5.0 (ScholarshipHunter/1.0)"}
TODAY = dt.date.today()


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def strip_html(html):
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)


def fetch_entries():
    entries, seen_links = [], set()
    for url in FEEDS:
        try:
            feed = feedparser.parse(url, agent=UA["User-Agent"])
            if not feed.entries:
                print(f"[warn] no entries: {url}")
            for e in feed.entries[:PER_FEED]:
                link = (e.get("link") or "").strip()
                if not link or link in seen_links:
                    continue
                seen_links.add(link)
                entries.append({
                    "title": strip_html(e.get("title", "")),
                    "link": link,
                    "summary": strip_html(e.get("summary", ""))[:1500],
                    "source": url,
                })
        except Exception as ex:
            print(f"[warn] feed failed {url}: {ex}")
    return entries


def page_text(url):
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "nav", "footer", "header", "aside"]):
            t.decompose()
        return soup.get_text(" ", strip=True)[:6000]
    except Exception:
        return ""


def build_prompt(entry, text):
    return (
        "You are a scholarship eligibility analyst. Today's date is " + TODAY.isoformat() + ".\n\n"
        "STUDENT PROFILE (the only facts you may use about the student):\n"
        + json.dumps(PROFILE, indent=2) + "\n\n"
        "OPPORTUNITY (from " + entry["source"] + "):\n"
        "Title: " + entry["title"] + "\nURL: " + entry["link"] + "\n"
        "Feed summary: " + entry["summary"] + "\n"
        "Page text: " + (text or "(unavailable)") + "\n\n"
        "TASK: Decide if this student can realistically apply NOW. Set eligible=false if ANY of these hold:\n"
        "- It is not a scholarship/fellowship/exchange/internship/funded program (e.g. a job, conference, news item).\n"
        "- Pakistani nationals are excluded, or only specific other nationalities/regions qualify.\n"
        "- It is only for Master's/PhD/postdoc/high-school students, or for fields unrelated to engineering "
        "(unless open to all fields). The student is a current first-semester undergraduate.\n"
        "- The deadline has already passed.\n"
        "If unsure about a requirement, set eligible=true only when nothing found contradicts it, and say what to verify in match_notes.\n\n"
        "Return ONLY JSON with exactly these keys:\n"
        '{"eligible": boolean, "reject_reason": string, "title": string, "university_or_org": string, '
        '"country": string, "degree_level": "Undergraduate" | "Exchange" | "Internship" | "Mixed", '
        '"funding_type": "Fully Funded" | "Partial", '
        '"deadline": "YYYY-MM-DD" or "Rolling" or "Unknown", '
        '"eligibility_summary": string (max 40 words), "match_notes": string (max 40 words, why it fits this student, plus anything to verify), '
        '"apply_url": string, "draft_sop": string}\n'
        "draft_sop: about 250 words, first person, tailored to THIS scholarship/organisation and its goals, "
        "linking the student's chemical engineering studies, skills and renewable-energy career goal. "
        "Use only facts from the profile; do not invent awards, projects or experience. If not eligible, use an empty string."
    )


def evaluate(entry):
    prompt = build_prompt(entry, page_text(entry["link"]))
    for attempt in range(2):
        try:
            raw = call_groq(
                prompt,
                system_prompt="You are a strict scholarship eligibility evaluator. Respond with valid JSON only.",
            )
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
                if cleaned.endswith("```"):
                    cleaned = cleaned.rsplit("```", 1)[0]
            data = json.loads(cleaned.strip())
            if isinstance(data, list):
                data = data[0]
            return data
        except json.JSONDecodeError:
            continue
        except Exception as ex:
            if "429" in str(ex) or "RESOURCE_EXHAUSTED" in str(ex):
                raise
            print(f"[warn] groq error: {ex}")
            time.sleep(3)
    return None
    return None


def still_open(item):
    try:
        return dt.date.fromisoformat(item.get("deadline", "")) >= TODAY - dt.timedelta(days=3)
    except ValueError:
        return True  # Rolling / Unknown


def main():
    db = load_json(DB_FILE, [])
    seen = set(load_json(SEEN_FILE, []))
    seen.update(item.get("source_link", "") for item in db)

    new_entries = [e for e in fetch_entries() if e["link"] not in seen][:MAX_NEW]
    print(f"{len(new_entries)} new entries to evaluate.")

    added = 0
    for n, entry in enumerate(new_entries, 1):
        print(f"[{n}/{len(new_entries)}] {entry['title'][:80]}")
        try:
            res = evaluate( entry)
        except Exception:
            print("[warn] rate limit reached; stopping. Remaining entries will be retried next run.")
            break
        if res is None:
            time.sleep(SLEEP_BETWEEN_CALLS)
            continue
        seen.add(entry["link"])
        if res.get("eligible"):
            res.pop("eligible", None)
            res.pop("reject_reason", None)
            res["apply_url"] = res.get("apply_url") or entry["link"]
            res["source_link"] = entry["link"]
            res["id"] = hashlib.md5(entry["link"].encode()).hexdigest()[:12]
            res["added_on"] = TODAY.isoformat()
            db.append(res)
            added += 1
            print("   -> MATCH")
        else:
            print("   -> skipped:", res.get("reject_reason", "")[:100])
        time.sleep(SLEEP_BETWEEN_CALLS)

    db = [d for d in db if still_open(d)]
    DB_FILE.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")
    SEEN_FILE.write_text(json.dumps(sorted(seen)[-5000:], indent=1), encoding="utf-8")
    print(f"Done. Added {added}; total {len(db)}.")


if __name__ == "__main__":
    main()
