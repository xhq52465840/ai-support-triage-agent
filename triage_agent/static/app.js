const $ = (s) => document.querySelector(s);
let tickets = [], selected = null, filter = "all";
const STATUS = { escalated: "Escalated", needs_review: "Needs review", draft_ready: "Draft ready", sent: "Sent" };
const SENT = { angry: "😠 angry", negative: "🙁 negative", neutral: "😐 neutral", positive: "🙂 positive" };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function load() {
  tickets = await (await fetch("/api/tickets")).json();
  renderStats(); renderFilters(); renderRows();
  if (selected) renderDetail(tickets.find((t) => t.id === selected));
}

function renderStats() {
  const n = (f) => tickets.filter(f).length;
  const items = [
    ["Processed", tickets.length, ""],
    ["P1 urgent", n((t) => t.priority === "P1"), "red"],
    ["Escalated", n((t) => t.status === "escalated"), "amber"],
    ["Drafts ready", n((t) => t.status === "draft_ready"), "green"],
    ["Avg confidence", tickets.length ? Math.round(tickets.reduce((s, t) => s + t.confidence, 0) / tickets.length * 100) + "%" : "–", "blue"],
  ];
  $("#stats").innerHTML = items.map(([l, v, c]) => `<div class="stat ${c}"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");
}

function renderFilters() {
  const cats = ["all", ...new Set(tickets.map((t) => t.category))];
  $("#filters").innerHTML = cats.map((c) => `<button class="chip ${c === filter ? "on" : ""}" data-f="${c}">${c.replace("_", " ")}</button>`).join("");
  document.querySelectorAll("[data-f]").forEach((b) => (b.onclick = () => { filter = b.dataset.f; renderFilters(); renderRows(); }));
}

function renderRows() {
  const list = tickets.filter((t) => filter === "all" || t.category === filter);
  if (!list.length) return;
  $("#rows").innerHTML = list.map((t) => `
    <tr data-id="${t.id}" class="${t.id === selected ? "sel" : ""}">
      <td><div class="subj">${esc(t.subject)}</div><div class="from">${esc(t.sender.replace(/<.*>/, ""))} · ${t.id}</div></td>
      <td><span class="pri ${t.priority}">${t.priority}</span></td>
      <td><span class="cat">${t.category.replace("_", " ")}</span></td>
      <td class="sent">${SENT[t.sentiment]}</td>
      <td><span class="st ${t.status}">${STATUS[t.status] || t.status}</span></td>
      <td class="muted">${esc(t.assignee)}</td>
    </tr>`).join("");
  document.querySelectorAll("tr[data-id]").forEach((r) => (r.onclick = () => { selected = r.dataset.id; renderRows(); renderDetail(tickets.find((t) => t.id === selected)); }));
}

function renderDetail(t) {
  if (!t) return;
  const cust = t.context.lookup_customer || {};
  const fields = [["Customer", cust.found ? `${esc(cust.name)} · ${esc(cust.plan)} · LTV $${cust.ltv_usd.toLocaleString()}` : esc(t.customer_email)],
    ["Order ID", t.order_id], ["Amount", t.amount != null ? "$" + t.amount.toFixed(2) : null], ["Product", t.product], ["Summary", t.summary]]
    .filter(([, v]) => v).map(([k, v]) => `<div class="kv"><span>${k}</span><b>${v}</b></div>`).join("");
  const trace = t.trace.map((s, i) => `<li><span class="step">${i + 1}</span><code>${s.node}</code><span class="td">${esc(s.detail)}</span></li>`).join("");
  $("#detail").innerHTML = `
    <div class="dh"><span class="pri ${t.priority}">${t.priority}</span><span class="st ${t.status}">${STATUS[t.status] || t.status}</span><span class="conf">confidence ${Math.round(t.confidence * 100)}%</span></div>
    <h2>${esc(t.subject)}</h2>
    <div class="from">${esc(t.sender)} · ${t.received_at.replace("T", " ")}</div>
    <p class="body">${esc(t.body)}</p>
    <h4>Extracted fields</h4><div class="fields">${fields}</div>
    <h4>Agent trace</h4><ol class="trace">${trace}</ol>
    <h4>Draft reply</h4><textarea id="reply" rows="9">${esc(t.reply)}</textarea>
    <div class="row"><button class="ghost" id="rev">Send to human</button><button class="primary" id="approve">${t.status === "sent" ? "✓ Sent" : "Approve & send"}</button></div>`;
  $("#approve").onclick = () => patch(t.id, { status: "sent", reply: $("#reply").value });
  $("#rev").onclick = () => patch(t.id, { status: "needs_review" });
}

async function patch(id, body) {
  await fetch(`/api/tickets/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  load();
}

$("#run").onclick = async () => {
  $("#run").textContent = "Running agent…"; $("#run").disabled = true;
  await fetch("/api/process-inbox", { method: "POST" });
  $("#run").textContent = "Run agent on inbox"; $("#run").disabled = false;
  load();
};
$("#compose").onclick = () => $("#dlg").showModal();
$("#dlgForm").onsubmit = async (e) => {
  if (e.submitter?.value !== "default") return;
  const fd = Object.fromEntries(new FormData($("#dlgForm")));
  const t = await (await fetch("/api/emails", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(fd) })).json();
  selected = t.id; load();
};

fetch("/api/meta").then((r) => r.json()).then((m) => ($("#mode").textContent = m.mode === "mock" ? "● Mock LLM (offline)" : "● OpenAI"));
load();
