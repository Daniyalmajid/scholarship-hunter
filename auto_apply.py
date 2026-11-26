"""Playwright auto-fill helper. Never clicks Submit; you review and submit manually.
Usage: python auto_apply.py --url "https://..."
"""
import argparse, json, re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
P = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))

SCAN_JS = """els => els.map((el, i) => {
  const r = el.getBoundingClientRect(), st = getComputedStyle(el);
  const visible = r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
  let lab = '';
  if (el.labels && el.labels.length) lab = [...el.labels].map(l => l.innerText).join(' ');
  if (!lab) { const a = el.getAttribute('aria-labelledby');
    if (a) lab = a.split(' ').map(id => (document.getElementById(id) || {}).innerText || '').join(' '); }
  if (!lab) { const p = el.closest('label'); if (p) lab = p.innerText; }
  if (!lab) { const pv = el.previousElementSibling; if (pv) lab = pv.innerText || ''; }
  return {i, tag: el.tagName.toLowerCase(), type: (el.getAttribute('type') || '').toLowerCase(),
    name: el.name || '', id: el.id || '', ph: el.getAttribute('placeholder') || '',
    aria: el.getAttribute('aria-label') || '', lab: (lab || '').slice(0, 200),
    value: el.value || '', locked: !!(el.disabled || el.readOnly), visible};
})"""

SKIP_TYPES = {"hidden", "submit", "button", "reset", "image", "file", "password", "checkbox", "radio", "search"}
ESSAY_RE = r"essay|statement|motivation|sop|purpose|cover.?letter|why |describe|tell us|about (yourself|you)|personal|letter"

# (key, regex, value) - order matters: specific before generic.
RULES = [
    ("email", r"e-?mail", P["email"]),
    ("first", r"first.?name|given.?name|forename", P["first_name"]),
    ("last", r"last.?name|surname|family.?name", P["last_name"]),
    ("phone", r"phone|mobile|whatsapp|contact.?(no|number)", P.get("phone", "")),
    ("nationality", r"nationality|citizenship|citizen of", P["nationality"]),
    ("country", r"country", P["country"]),
    ("university", r"universit|institution|college|current school|school name", P["university"]),
    ("major", r"major|field of study|program|course of study|discipline|department|subject", P["major"]),
    ("gpa", r"gpa|cgpa|marks|percentage|grade|score|result", P["gpa_text"]),
    ("name", r"full.?name|your name|applicant.?name|\bname\b", P["full_name"]),
]


def get_essay(url):
    try:
        items = json.loads((ROOT / "data" / "scholarships.json").read_text(encoding="utf-8"))
        norm = lambda u: u.rstrip("/").lower()
        for it in items:
            if norm(it.get("apply_url", "")) == norm(url) or norm(it.get("source_link", "")) == norm(url):
                print(f"Using tailored SOP for: {it['title']}")
                return it["draft_sop"]
    except Exception:
        pass
    print("No tailored SOP found for this URL; using the generic statement from profile.json.")
    return P["generic_sop"]


def descriptor(f):
    return " ".join([f["lab"], f["name"], f["id"], f["ph"], f["aria"]]).lower()


def match(f, essay):
    d = descriptor(f)
    if f["tag"] == "textarea":
        return ("essay", essay) if re.search(ESSAY_RE, d) else None
    for key, rx, val in RULES:
        if val and not str(val).startswith("YOUR_") and re.search(rx, d):
            return key, val
    if f["tag"] == "input" and f["type"] in ("", "text") and re.search(ESSAY_RE, d) and "name" not in d:
        return None
    return None


def highlight(loc):
    loc.evaluate("el => { el.style.outline = '3px solid #22c55e'; el.style.backgroundColor = '#dcfce7'; el.style.color = '#052e16'; }")


def fill_frame(frame, essay, report):
    fields = frame.locator("input, textarea, select")
    for f in fields.evaluate_all(SCAN_JS):
        if not f["visible"] or f["locked"] or f["type"] in SKIP_TYPES:
            continue
        m = match(f, essay)
        if not m:
            if f["tag"] != "select":
                report["unmatched"].append(f["lab"] or f["name"] or f["ph"] or f["id"] or "(unnamed)")
            continue
        key, val = m
        loc = fields.nth(f["i"])
        try:
            if f["tag"] == "select":
                opts = loc.locator("option").all_text_contents()
                pick = next((o for o in opts if str(val).lower() in o.lower()), None)
                if not pick:
                    continue
                loc.select_option(label=pick)
            else:
                if f["value"].strip():
                    continue  # don't overwrite existing content
                loc.fill(str(val))
            highlight(loc)
            report["filled"].append(f"{key}: {(f['lab'] or f['name'] or f['ph'])[:50]}")
        except Exception as ex:
            report["errors"].append(f"{key}: {str(ex)[:80]}")


def run_pass(page, essay):
    report = {"filled": [], "unmatched": [], "errors": []}
    for frame in page.frames:
        try:
            fill_frame(frame, essay, report)
        except Exception:
            continue
    print(f"\nFilled {len(report['filled'])} field(s):")
    for x in report["filled"]:
        print("  +", x)
    if report["unmatched"]:
        print("Left for you to complete:", "; ".join(dict.fromkeys(report["unmatched"]))[:400])
    for x in report["errors"]:
        print("  ! could not fill", x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    url = ap.parse_args().url
    essay = get_essay(url)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=50)
        page = browser.new_context(viewport=None).new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        run_pass(page, essay)
        print("\nSAFETY: this script never clicks Submit.")
        print("Solve any CAPTCHA, upload your PDFs, review everything, then click Submit yourself.")
        while True:
            cmd = input("\n[r] re-scan & fill (e.g. next form step)   [q] close browser > ").strip().lower()
            if cmd == "q":
                break
            if cmd == "r":
                run_pass(page, essay)
        browser.close()


if __name__ == "__main__":
    main()
