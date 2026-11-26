const LS_KEY = "sh_status_v1";
const $ = (s) => document.querySelector(s);
let DATA = [];
let STATUS = loadStatus();

function loadStatus() { try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch { return {}; } }
function saveStatus() { try { localStorage.setItem(LS_KEY, JSON.stringify(STATUS)); } catch {} }
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");

function daysLeft(d) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d || "")) return null;
  return Math.ceil((new Date(d + "T23:59:59") - new Date()) / 864e5);
}

function deadlineBadge(item) {
  const n = daysLeft(item.deadline);
  if (n === null) return `<span class="chip">Deadline: ${esc(item.deadline || "Unknown")}</span>`;
  if (n < 0) return `<span class="chip">Closed ${esc(item.deadline)}</span>`;
  const cls = n <= 7 ? "bg-red-900 text-red-200" : n <= 30 ? "bg-amber-900 text-amber-200" : "bg-slate-800 text-slate-200";
  const txt = n === 0 ? "Closes today" : `${n} day${n === 1 ? "" : "s"} left`;
  return `<span class="chip ${cls}" title="${esc(item.deadline)}">${txt} (${esc(item.deadline)})</span>`;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 1600);
}

async function copy(text, msg) {
  try { await navigator.clipboard.writeText(text); }
  catch {
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove();
  }
  toast(msg);
}

function fillSelect(id, values) {
  const el = $(id);
  [...new Set(values.filter(Boolean))].sort().forEach((v) => {
    const o = document.createElement("option");
    o.value = v; o.textContent = v; el.appendChild(o);
  });
}

function filtered() {
  const q = $("#q").value.trim().toLowerCase();
  const c = $("#f-country").value, l = $("#f-level").value, f = $("#f-funding").value, v = $("#f-view").value;
  return DATA.filter((d) => {
    const st = STATUS[d.id] || {};
    if (c && d.country !== c) return false;
    if (l && d.degree_level !== l) return false;
    if (f && d.funding_type !== f) return false;
    if (v === "saved" && !st.saved) return false;
    if (v === "applied" && !st.applied) return false;
    if (v === "todo" && st.applied) return false;
    if (q && ![d.title, d.university_or_org, d.country, d.eligibility_summary].join(" ").toLowerCase().includes(q)) return false;
    return true;
  }).sort((a, b) => (daysLeft(a.deadline) ?? 9999) - (daysLeft(b.deadline) ?? 9999));
}

function cardHtml(d) {
  const st = STATUS[d.id] || {};
  const url = safeUrl(d.apply_url);
  return `<article class="card ${st.applied ? "is-applied" : ""}">
    <div>
      <h2 class="text-lg font-semibold text-white leading-snug">${esc(d.title)}</h2>
      <p class="text-sm text-slate-400 mt-1">${esc(d.university_or_org)}, ${esc(d.country)}</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <span class="chip">${esc(d.degree_level)}</span>
      <span class="chip ${d.funding_type === "Fully Funded" ? "full" : ""}">${esc(d.funding_type)}</span>
      ${deadlineBadge(d)}
    </div>
    <p class="text-sm text-slate-300">${esc(d.eligibility_summary)}</p>
    <p class="text-sm rounded-lg bg-emerald-950/60 border border-emerald-900 text-emerald-200 px-3 py-2"><strong>Why it fits:</strong> ${esc(d.match_notes)}</p>
    <div class="flex flex-wrap gap-2">
      <button class="btn" data-copy="sop" data-id="${esc(d.id)}">Copy tailored SOP</button>
      <a class="btn primary" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open application</a>
      <button class="btn" data-copy="cmd" data-id="${esc(d.id)}">Copy auto-fill command</button>
    </div>
    <div class="flex gap-5 text-sm text-slate-400 pt-1">
      <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" data-flag="saved" data-id="${esc(d.id)}" ${st.saved ? "checked" : ""}> Saved</label>
      <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" data-flag="applied" data-id="${esc(d.id)}" ${st.applied ? "checked" : ""}> Applied</label>
    </div>
  </article>`;
}

function render() {
  const list = filtered();
  $("#grid").innerHTML = list.length
    ? list.map(cardHtml).join("")
    : `<p class="text-slate-400 md:col-span-2">No matches yet. Run the daily workflow from the GitHub Actions tab, or loosen your filters.</p>`;
  $("#count").textContent = `Showing ${list.length} of ${DATA.length}`;
  $("#s-total").textContent = DATA.length;
  $("#s-soon").textContent = DATA.filter((d) => { const n = daysLeft(d.deadline); return n !== null && n >= 0 && n <= 30; }).length;
  $("#s-full").textContent = DATA.filter((d) => d.funding_type === "Fully Funded").length;
  $("#s-applied").textContent = DATA.filter((d) => (STATUS[d.id] || {}).applied).length;
}

document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-copy]");
  if (!b) return;
  const d = DATA.find((x) => x.id === b.dataset.id);
  if (!d) return;
  if (b.dataset.copy === "sop") copy(d.draft_sop || "", "SOP copied");
  else copy(`python auto_apply.py --url "${d.apply_url}"`, "Command copied");
});

document.addEventListener("change", (e) => {
  const c = e.target.closest("[data-flag]");
  if (!c) return;
  const id = c.dataset.id;
  STATUS[id] = { ...(STATUS[id] || {}), [c.dataset.flag]: c.checked };
  saveStatus();
  render();
});

["#q", "#f-country", "#f-level", "#f-funding", "#f-view"].forEach((s) => $(s).addEventListener("input", render));

(async function init() {
  try {
    const r = await fetch("data/scholarships.json", { cache: "no-store" });
    DATA = await r.json();
  } catch { DATA = []; }
  fillSelect("#f-country", DATA.map((d) => d.country));
  fillSelect("#f-level", DATA.map((d) => d.degree_level));
  fillSelect("#f-funding", DATA.map((d) => d.funding_type));
  render();
})();
