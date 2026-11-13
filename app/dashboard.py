"""Single-file dashboard. Plain HTML/CSS/JS, no build step.
All data is inserted with textContent, never innerHTML, so bank narrations can't inject script."""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PayMatch · {{BUSINESS}}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root { --bg:#F3F6F5; --panel:#FFFFFF; --ink:#0F2A25; --muted:#5B6F6A; --line:#D6E0DD; --green:#0F7B5B;
          --green-soft:#E3F2EC; --amber:#9A6200; --amber-soft:#FFF3D9; --red:#B42318; --red-soft:#FDE8E6; --blue:#1D5FA8; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 "IBM Plex Sans",system-ui,sans-serif;
         font-variant-numeric: tabular-nums; }
  :focus-visible { outline:3px solid var(--green); outline-offset:2px; }
  header { background:var(--ink); color:#fff; padding:18px 28px; display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; }
  header h1 { margin:0; font-size:20px; font-weight:700; letter-spacing:-.01em; }
  header .sub { color:#A9C2BB; font-size:13px; }
  header button { background:transparent; color:#fff; border:1px solid #4E6B64; border-radius:6px; padding:7px 12px; font:inherit; font-size:13px; cursor:pointer; }
  nav { display:flex; gap:4px; padding:0 28px; background:var(--panel); border-bottom:1px solid var(--line); overflow-x:auto; }
  nav button { background:none; border:0; border-bottom:3px solid transparent; padding:14px 14px 11px; font:inherit; font-weight:600; color:var(--muted); cursor:pointer; white-space:nowrap; }
  nav button[aria-selected=true] { color:var(--ink); border-bottom-color:var(--green); }
  .badge { display:inline-block; min-width:20px; padding:0 6px; margin-left:6px; border-radius:10px; background:var(--amber-soft); color:var(--amber); font-size:12px; }
  main { max-width:1180px; margin:0 auto; padding:24px 28px 60px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; margin-bottom:20px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px 16px; }
  .card .label { color:var(--muted); font-size:13px; }
  .card .value { font-size:24px; font-weight:700; margin-top:2px; }
  .card .note { color:var(--muted); font-size:12px; }
  h2 { font-size:17px; margin:0 0 4px; }
  .lede { color:var(--muted); margin:0 0 16px; max-width:70ch; }
  .grid2 { display:grid; grid-template-columns:1.1fr 1fr; gap:16px; }
  @media (max-width:900px) { .grid2 { grid-template-columns:1fr; } }
  .grid2 > .panel { min-width:0; overflow-x:auto; }
  @media (max-width:600px) { main { padding:16px 14px 48px; } header, nav { padding-left:14px; padding-right:14px; } .bar { grid-template-columns:84px 1fr 96px; } }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:18px; }
  .bar { display:grid; grid-template-columns:110px 1fr 120px; align-items:center; gap:10px; margin:9px 0; font-size:14px; }
  .bar .track { height:14px; background:#EDF2F0; border-radius:3px; overflow:hidden; }
  .bar .fill { height:100%; background:var(--green); }
  .bar.late .fill { background:var(--amber); } .bar.bad .fill { background:var(--red); }
  .bar .amt { text-align:right; font-weight:600; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th { text-align:left; color:var(--muted); font-weight:500; font-size:13px; padding:8px 10px; border-bottom:1px solid var(--line); }
  td { padding:10px; border-bottom:1px solid var(--line); vertical-align:top; }
  td.num { text-align:right; white-space:nowrap; font-weight:600; }
  .narr { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:13px; word-break:break-word; }
  .pill { display:inline-block; padding:1px 8px; border-radius:10px; font-size:12px; font-weight:600; white-space:nowrap; }
  .pill.auto, .pill.confirmed { background:var(--green-soft); color:var(--green); }
  .pill.suggested { background:var(--amber-soft); color:var(--amber); }
  .pill.unmatched, .pill.rejected { background:var(--red-soft); color:var(--red); }
  .muted { color:var(--muted); font-size:13px; }
  .review { display:grid; gap:12px; }
  .item { background:var(--panel); border:1px solid var(--line); border-left:4px solid var(--amber); border-radius:8px; padding:16px; display:grid; grid-template-columns:1fr auto; gap:12px 20px; }
  .item.unmatched { border-left-color:var(--red); }
  @media (max-width:700px) { .item { grid-template-columns:1fr; } }
  .item .top { display:flex; gap:12px; align-items:baseline; flex-wrap:wrap; }
  .item .amount { font-size:20px; font-weight:700; }
  .alloc { margin:8px 0 0; padding:0; list-style:none; }
  .alloc li { font-size:14px; }
  .actions { display:flex; gap:8px; align-items:flex-start; flex-wrap:wrap; }
  .btn { font:inherit; font-weight:600; font-size:14px; border-radius:6px; padding:8px 14px; cursor:pointer; border:1px solid var(--line); background:var(--panel); color:var(--ink); }
  .btn.primary { background:var(--green); border-color:var(--green); color:#fff; }
  .btn.danger { color:var(--red); }
  select { font:inherit; font-size:14px; padding:7px; border:1px solid var(--line); border-radius:6px; max-width:260px; }
  .filters { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
  .filters button[aria-pressed=true] { background:var(--ink); color:#fff; border-color:var(--ink); }
  .empty { padding:32px; text-align:center; color:var(--muted); background:var(--panel); border:1px dashed var(--line); border-radius:8px; }
  dialog { border:0; border-radius:10px; max-width:640px; width:calc(100% - 32px); padding:0; box-shadow:0 20px 60px rgba(15,42,37,.3); }
  dialog .head { padding:16px 20px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; gap:12px; }
  dialog .body { padding:16px 20px; }
  dialog pre { white-space:pre-wrap; font:inherit; background:var(--bg); padding:12px; border-radius:6px; margin:8px 0 0; }
  .toast { position:fixed; bottom:20px; left:50%; transform:translateX(-50%); background:var(--ink); color:#fff; padding:10px 16px; border-radius:6px; font-size:14px; opacity:0; transition:opacity .2s; pointer-events:none; }
  .toast.show { opacity:1; }
  [hidden] { display:none !important; }
</style>
</head>
<body>
<header>
  <div>
    <h1>PayMatch</h1>
    <div class="sub"><span>{{BUSINESS}}</span> · <span id="asof"></span> · <span id="engine"></span></div>
  </div>
  <button type="button" id="reset">Reset demo data</button>
</header>
<nav role="tablist" aria-label="Sections">
  <button role="tab" data-tab="overview" aria-selected="true">Overview</button>
  <button role="tab" data-tab="review" aria-selected="false">To review<span class="badge" id="review-count">0</span></button>
  <button role="tab" data-tab="payments" aria-selected="false">All payments</button>
  <button role="tab" data-tab="overdue" aria-selected="false">Overdue invoices</button>
</nav>
<main>
  <section id="tab-overview">
    <div class="cards" id="cards"></div>
    <div class="grid2">
      <div class="panel"><h2>What customers owe, by age</h2><p class="lede">Outstanding balances after every matched payment.</p><div id="aging"></div></div>
      <div class="panel"><h2>Biggest balances</h2><p class="lede">Who to call first.</p><table><thead><tr><th>Customer</th><th>Invoices</th><th>Oldest</th><th style="text-align:right">Owes</th></tr></thead><tbody id="debtors"></tbody></table></div>
    </div>
  </section>
  <section id="tab-review" hidden>
    <h2>Payments to review</h2>
    <p class="lede">PayMatch only applies a payment by itself when it's certain. These are the rest: confirm the suggestion, reject it, or pick the right invoices yourself.</p>
    <div class="review" id="review"></div>
  </section>
  <section id="tab-payments" hidden>
    <h2>All payments received</h2>
    <p class="lede">Every credit on the statement and what it was matched to.</p>
    <div class="filters" id="filters"></div>
    <div class="panel" style="padding:0;overflow-x:auto"><table><thead><tr><th>Date</th><th>Narration</th><th style="text-align:right">Amount</th><th>Status</th><th>Matched to</th></tr></thead><tbody id="payments"></tbody></table></div>
  </section>
  <section id="tab-overdue" hidden>
    <h2>Overdue invoices</h2>
    <p class="lede">Unpaid past their due date, oldest first. Draft a reminder: the tone gets firmer the longer it's overdue.</p>
    <div class="panel" style="padding:0;overflow-x:auto"><table><thead><tr><th>Invoice</th><th>Customer</th><th>Due</th><th>Overdue</th><th style="text-align:right">Outstanding</th><th></th></tr></thead><tbody id="overdue"></tbody></table></div>
  </section>
</main>
<dialog id="dlg" aria-labelledby="dlg-title">
  <div class="head"><strong id="dlg-title">Reminder</strong><button class="btn" type="button" id="dlg-close">Close</button></div>
  <div class="body">
    <div class="muted" id="dlg-to"></div>
    <div style="margin-top:8px"><strong id="dlg-subject"></strong></div>
    <pre id="dlg-body"></pre>
    <div class="actions" style="margin-top:12px"><button class="btn primary" type="button" id="dlg-copy">Copy email</button><span class="muted" id="dlg-engine"></span></div>
  </div>
</dialog>
<div class="toast" id="toast" role="status"></div>
<script>
const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, ...kids) => { const e = document.createElement(tag); for (const [k, v] of Object.entries(attrs)) { if (k === "class") e.className = v; else if (k === "text") e.textContent = v; else e.setAttribute(k, v); } kids.forEach(k => k && e.append(k)); return e; };
const api = async (path, opts) => { const r = await fetch(path, opts); const data = await r.json().catch(() => ({})); if (!r.ok) throw new Error(data.detail || ("Request failed: " + r.status)); return data; };
const toast = (msg) => { const t = $("toast"); t.textContent = msg; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 2600); };
const LABEL = { auto: "Matched automatically", suggested: "Needs review", confirmed: "Confirmed", rejected: "Rejected", unmatched: "Unmatched" };
const METHOD = { reference: "invoice number in narration", name_amount: "payer name + exact amount", multi_invoice: "one transfer, several invoices", partial: "part payment", overpayment: "overpayment", amount_only: "amount only", ai: "AI suggestion", manual: "assigned by a person" };
let openInvoices = [];
let filter = "";

document.querySelectorAll("nav [role=tab]").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav [role=tab]").forEach(x => x.setAttribute("aria-selected", x === b));
  document.querySelectorAll("main > section").forEach(s => s.hidden = s.id !== "tab-" + b.dataset.tab);
});

function card(label, value, note) { return el("div", { class: "card" }, el("div", { class: "label", text: label }), el("div", { class: "value", text: value }), note ? el("div", { class: "note", text: note }) : null); }

async function loadOverview() {
  const [s, h, a] = await Promise.all([api("/api/summary"), api("/health"), api("/api/aging")]);
  $("asof").textContent = "as of " + new Date(s.as_of).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  $("engine").textContent = h.engine === "rules only" ? "rules engine" : "AI: " + h.engine;
  $("review-count").textContent = s.counts.suggested + s.counts.unmatched;
  $("cards").replaceChildren(
    card("Payments received", s.amount_received, s.credits + " transfers"),
    card("Reconciled", Math.round(s.reconciled_share * 100) + "%", s.amount_reconciled + " applied to invoices"),
    card("Matched automatically", s.counts.auto + " of " + s.credits, "no human needed"),
    card("Waiting for review", String(s.counts.suggested + s.counts.unmatched), s.counts.suggested + " suggestions, " + s.counts.unmatched + " unmatched"),
    card("Overdue", s.overdue_amount, s.overdue_count + " invoices past due"));
  const max = Math.max(...a.buckets.map(b => b.amount), 1);
  $("aging").replaceChildren(...a.buckets.map((b, i) => {
    const fill = el("div", { class: "fill" }); fill.style.width = (b.amount / max * 100) + "%";
    return el("div", { class: "bar" + (i >= 3 ? " bad" : i >= 1 ? " late" : "") }, el("span", { text: b.bucket }), el("div", { class: "track" }, fill), el("span", { class: "amt", text: b.display }));
  }));
  $("debtors").replaceChildren(...a.customers.slice(0, 6).map(c => el("tr", {}, el("td", { text: c.customer }), el("td", { text: String(c.invoices) }),
    el("td", { text: c.oldest_days_overdue > 0 ? c.oldest_days_overdue + " days late" : "not due" }), el("td", { class: "num", text: c.total_display }))));
}

function allocList(t) {
  if (!t.allocations.length) return null;
  return el("ul", { class: "alloc" }, ...t.allocations.map(a => el("li", { text: "→ INV-" + a.invoice + "  " + a.amount_display })),
    t.unapplied_display && t.status !== "unmatched" ? el("li", { class: "muted", text: "Unapplied credit: " + t.unapplied_display }) : null);
}

async function act(path, body, done) {
  try { await api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined }); toast(done); await refresh(); }
  catch (e) { toast(e.message); }
}

async function loadReview() {
  const [sug, un, inv] = await Promise.all([api("/api/transactions?status=suggested"), api("/api/transactions?status=unmatched"), api("/api/invoices/open")]);
  openInvoices = inv;
  const items = [...sug, ...un];
  if (!items.length) { $("review").replaceChildren(el("div", { class: "empty", text: "Nothing to review. Every payment is accounted for." })); return; }
  $("review").replaceChildren(...items.map(t => {
    const info = el("div", {},
      el("div", { class: "top" }, el("span", { class: "amount", text: t.amount_display }), el("span", { class: "pill " + t.status, text: LABEL[t.status] }), el("span", { class: "muted", text: t.date })),
      el("div", { class: "narr", text: t.narration }),
      t.customer ? el("div", { style: "margin-top:6px" }, el("strong", { text: t.customer }), el("span", { class: "muted", text: "  ·  " + (METHOD[t.method] || "") + (t.confidence ? "  ·  " + Math.round(t.confidence * 100) + "% sure" : "") })) : null,
      allocList(t), el("div", { class: "muted", style: "margin-top:6px", text: t.reason }));
    const actions = el("div", { class: "actions" });
    if (t.status === "suggested") {
      const ok = el("button", { class: "btn primary", type: "button", text: "Confirm" }); ok.onclick = () => act(`/api/transactions/${t.id}/confirm`, null, "Payment applied");
      const no = el("button", { class: "btn danger", type: "button", text: "Reject" }); no.onclick = () => act(`/api/transactions/${t.id}/reject`, null, "Suggestion rejected");
      actions.append(ok, no);
    } else {
      const sel = el("select", { "aria-label": "Invoice for this payment" }, el("option", { value: "", text: "Assign to invoice…" }),
        ...openInvoices.map(i => el("option", { value: i.invoice, text: `INV-${i.invoice} · ${i.customer}` })));
      const go = el("button", { class: "btn", type: "button", text: "Assign" });
      go.onclick = () => sel.value ? act(`/api/transactions/${t.id}/assign`, { invoice_numbers: [sel.value] }, "Assigned to INV-" + sel.value) : toast("Pick an invoice first");
      actions.append(sel, go);
    }
    return el("div", { class: "item " + t.status }, info, actions);
  }));
}

async function loadPayments() {
  const statuses = ["", "auto", "suggested", "confirmed", "unmatched"];
  $("filters").replaceChildren(...statuses.map(s => { const b = el("button", { class: "btn", type: "button", "aria-pressed": String(filter === s), text: s ? LABEL[s] : "All" }); b.onclick = () => { filter = s; loadPayments(); }; return b; }));
  const rows = await api("/api/transactions" + (filter ? "?status=" + filter : ""));
  $("payments").replaceChildren(...rows.map(t => el("tr", {}, el("td", { text: t.date }), el("td", { class: "narr", text: t.narration }), el("td", { class: "num", text: t.amount_display }),
    el("td", {}, el("span", { class: "pill " + t.status, text: LABEL[t.status] })),
    el("td", {}, t.customer ? el("div", { text: t.customer }) : el("span", { class: "muted", text: "—" }), el("div", { class: "muted", text: t.allocations.map(a => "INV-" + a.invoice).join(", ") })))));
}

async function loadOverdue() {
  const rows = await api("/api/overdue");
  $("overdue").replaceChildren(...rows.map(r => {
    const b = el("button", { class: "btn", type: "button", text: "Draft reminder" });
    b.onclick = async () => {
      b.disabled = true; b.textContent = "Drafting…";
      try { const d = await api(`/api/invoices/${r.invoice}/reminder`, { method: "POST" }); showReminder(d); }
      catch (e) { toast(e.message); } finally { b.disabled = false; b.textContent = "Draft reminder"; }
    };
    let action = b;
    if (r.covered_by_pending) {
      action = el("button", { class: "btn", type: "button", text: "Review payment first" });
      action.onclick = () => document.querySelector("[data-tab=review]").click();
    }
    return el("tr", {}, el("td", { text: "INV-" + r.invoice }), el("td", { text: r.customer }), el("td", { text: r.due_date }),
      el("td", {}, el("span", { class: "pill " + (r.days_overdue > 45 ? "unmatched" : "suggested"), text: r.days_overdue + " days" }),
        r.part_paid ? el("div", { class: "muted", text: "part paid" }) : null,
        r.payment_pending_review ? el("div", { class: "muted", text: r.payment_pending_review + " received, awaiting review" }) : null),
      el("td", { class: "num", text: r.outstanding }), el("td", {}, action));
  }));
}

function showReminder(d) {
  $("dlg-to").textContent = "To: " + (d.to || "(no email on file)");
  $("dlg-subject").textContent = d.subject; $("dlg-body").textContent = d.body;
  $("dlg-engine").textContent = d.engine.startsWith("template") ? "Written from a template" : "Drafted by " + d.engine;
  $("dlg").showModal();
}
$("dlg-close").onclick = () => $("dlg").close();
$("dlg-copy").onclick = async () => { try { await navigator.clipboard.writeText($("dlg-subject").textContent + "\n\n" + $("dlg-body").textContent); toast("Copied"); } catch { toast("Copy failed: select the text instead"); } };
$("reset").onclick = async () => { $("reset").disabled = true; try { await api("/api/demo/reset", { method: "POST" }); toast("Demo data reloaded"); await refresh(); } catch (e) { toast(e.message); } finally { $("reset").disabled = false; } };

async function refresh() { await Promise.all([loadOverview(), loadReview(), loadPayments(), loadOverdue()]); }
refresh().catch(e => toast(e.message));
setTimeout(() => refresh().catch(() => {}), 4000);  // first visit: sample data may still be loading
</script>
</body>
</html>
"""
