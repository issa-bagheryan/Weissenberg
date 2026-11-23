(() => {
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(kid));
  return el;
}

const BARE = new Set(["line_items", "duplicate", "currency"]);
const TYPES = ["invoice", "receipt", "contract", "application", "generic"];
const S = { docs: [], pending: [], cur: null, filter: "all", tab: "original", seq: 0, timer: null,
            dayfirst: localStorage.getItem("dayfirst") !== "0" };
const cur = () => S.docs.find(d => d.id === S.cur);
const ACR = { po: "PO", id: "ID", vat: "VAT", dob: "DOB", url: "URL", iban: "IBAN" };
const humanize = n => { const w = n.replace("last4", "last_4").split("_").map(x => ACR[x] || x); w[0] = w[0].charAt(0).toUpperCase() + w[0].slice(1); return w.join(" "); };
const normName = n => n.trim().toLowerCase().replace(/\s+/g, "_");

/* ---------- api + small utils ---------- */
async function api(path, opt) {
  const r = await fetch(path, opt);
  if (!r.ok) { let m = "Request failed"; try { m = (await r.json()).error || m; } catch {} throw new Error(m); }
  return r;
}
let toastT;
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => (t.hidden = true), 2600);
}
function toNum(s) {                       // "1.234,56" / "1,234.56" / "12" -> number
  s = String(s ?? "").replace(/[^\d.,-]/g, ""); if (!s) return null;
  const m = s.match(/[.,](\d{1,2})$/);
  const n = m ? parseFloat(s.slice(0, m.index).replace(/[.,]/g, "") + "." + m[1]) : parseFloat(s.replace(/[.,]/g, ""));
  return isNaN(n) ? null : n;
}
const money = n => n.toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fieldVal = (d, ...names) => { for (const n of names) { const f = d.fields.find(x => x.name === n && x.value); if (f) return f.value; } return ""; };

/* ---------- list ---------- */
const isOpen = d => !d.verified;
function visible() {
  return S.docs.filter(d => S.filter === "all" || (S.filter === "review" ? isOpen(d) : d.verified));
}
function renderList() {
  const total = S.docs.length, ver = S.docs.filter(d => d.verified).length;
  $("#count").replaceChildren(h("b", {}, ver), ` of ${total} verified`);
  $("#barFill").style.width = total ? (ver / total * 100) + "%" : "0";
  const chips = [["all", "All", total], ["review", "To review", total - ver], ["done", "Verified", ver]];
  $("#chips").replaceChildren(...chips.map(([k, label, n]) =>
    h("button", { class: "chip" + (S.filter === k ? " on" : ""), onclick: () => { S.filter = k; renderList(); } }, `${label} ${n}`)));

  const box = $("#items"); box.replaceChildren();
  for (const p of S.pending) {
    box.append(h("div", { class: "item " + (p.error ? "fail" : "pend") },
      p.error ? h("span", { class: "dot error" }) : h("span", { class: "spin" }),
      h("div", {}, h("div", { class: "t" }, p.name), h("div", { class: "s" }, p.error || "Reading…")),
      p.error ? h("button", { class: "x", style: "opacity:1", title: "Dismiss", onclick: () => { S.pending = S.pending.filter(x => x !== p); renderList(); } }, "×") : null));
  }
  const list = visible();
  for (const d of list) {
    const name = fieldVal(d, "vendor", "merchant", "party_1", "full_name") || d.filename;
    const amt = fieldVal(d, "total", "contract_value");
    box.append(h("div", { class: "item" + (d.id === S.cur ? " sel" : ""), onclick: () => select(d.id) },
      h("span", { class: "dot " + (d.verified ? "verified" : d.status) }),
      h("div", { style: "min-width:0" }, h("div", { class: "t" }, name),
        h("div", { class: "s" }, [d.doc_type, name !== d.filename ? d.filename : ""].filter(Boolean).join(" · "))),
      h("div", { style: "display:flex;align-items:center;gap:2px" },
        amt ? h("span", { class: "s", style: "font-variant-numeric:tabular-nums" }, money(toNum(amt) ?? 0)) : null,
        h("button", { class: "x", title: "Remove", onclick: e => { e.stopPropagation(); remove(d); } }, "×"))));
  }
  if (!list.length && !S.pending.length) box.append(h("div", { class: "nothing" }, S.filter === "done" ? "Nothing verified yet" : "All caught up 🎉"));
}

async function select(id) {
  if (S.cur && S.cur !== id) await flush();
  S.cur = id; S.tab = "original"; renderList(); renderDoc();
}
async function remove(d) {
  if (!confirm(`Remove “${d.filename}”?`)) return;
  await api("/api/doc/" + d.id, { method: "DELETE" });
  const i = S.docs.indexOf(d); S.docs.splice(i, 1);
  if (S.cur === d.id) S.cur = (S.docs[i] || S.docs[i - 1] || {}).id || null;
  render();
}

/* ---------- viewer ---------- */
function renderViewer(d) {
  const tabs = d.preview ? [["original", "Original"], ["text", "Extracted text"]] : [["text", "Extracted text"]];
  if (!tabs.some(t => t[0] === S.tab)) S.tab = tabs[0][0];
  $("#tabs").replaceChildren(...tabs.map(([k, l]) => h("button", { class: "tab" + (S.tab === k ? " on" : ""), onclick: () => { S.tab = k; renderViewer(d); } }, l)));
  const st = $("#stage"); st.replaceChildren();
  if (S.tab === "original" && d.preview) {
    const url = "/api/doc/" + d.id + "/file";
    st.append(d.preview === "application/pdf" ? h("iframe", { src: url + "#toolbar=0&navpanes=0", title: d.filename })
                                              : h("div", { class: "imgwrap" }, h("img", { src: url, alt: d.filename })));
  } else st.append(h("pre", { class: "sheet" }, d.raw_text || "(no text found)"));
}

/* ---------- form ---------- */
function fieldRow(f) {
  const custom = !!f.custom;
  const input = h("input", { class: "val", value: f.value, spellcheck: "false", autocomplete: "off",
    placeholder: f.required ? "Required" : "", title: f.source ? "Found: " + f.source : "", oninput: queueSave });
  const del = h("button", { class: "del", title: "Remove field", tabindex: "-1", onclick: e => { e.target.closest(".row").remove(); queueSave(); } }, "×");
  const label = custom ? h("input", { class: "lbl-in", placeholder: "Field name", oninput: queueSave }) : h("label", {}, humanize(f.name));
  return h("div", { class: "row" + (custom ? " custom" : "") + (f.required ? "" : " optional"), dataset: custom ? {} : { name: f.name } },
    label, h("div", { class: "cell" }, input, h("span", { class: "mark" }), del));
}
const rowName = r => r.dataset.name || normName($(".lbl-in", r)?.value || "");

function itemRow(it = {}) {
  const show = (k, v) => v == null || v === "" ? "" : (typeof v === "number" ? (k === "quantity" ? String(+v.toFixed(3)) : v.toFixed(2)) : v);
  const inp = (k, cls) => h("td", { class: cls || "" }, h("input", { value: show(k, it[k]), oninput: queueSave, spellcheck: "false", placeholder: k === "description" ? "Description" : "",
    onblur: k === "unit_price" || k === "amount" ? e => { const n = toNum(e.target.value); if (n != null) e.target.value = n.toFixed(2); } : null }));
  return h("tr", {}, inp("description"), inp("quantity", "n"), inp("unit_price", "n"), inp("amount", "n"),
    h("td", { class: "d" }, h("button", { tabindex: "-1", onclick: e => { e.target.closest("tr").remove(); queueSave(); } }, "×")));
}
function itemsSum() {
  const s = $$("#itemsBody tr").reduce((a, tr) => a + (toNum(tr.children[3].firstChild.value) || 0), 0);
  const el = $("#itemsSum"); if (el) el.textContent = $$("#itemsBody tr").length ? "Σ " + money(s) : "";
}

function renderDoc() {
  const d = cur();
  const form = $("#form"), foot = $("#foot");
  form.dataset.id = S.cur || "";
  if (!d) { form.replaceChildren(); foot.replaceChildren(); $("#stage").replaceChildren(); $("#tabs").replaceChildren(); return; }
  renderViewer(d);
  const sel = h("select", { class: "type", title: "Document type", onchange: async e => {
    clearTimeout(S.timer);
    try { const r = await (await api("/api/doc/" + d.id, { method: "PUT", body: JSON.stringify({ doc_type: e.target.value }) })).json(); merge(r); renderDoc(); }
    catch (err) { toast(err.message); }
  } }, TYPES.map(t => h("option", { value: t, selected: t === d.doc_type }, t)));
  const copy = h("button", { class: "btn ghost", style: "height:30px", title: "Copy this document as JSON", onclick: copyJson }, "Copy JSON");
  form.replaceChildren(
    h("div", { class: "fhead" }, h("div", { class: "ftitle", title: d.filename }, d.filename), sel, copy),
    h("div", { id: "checks" }),
    h("div", { class: "rows", id: "fields" }, d.fields.map(fieldRow)),
    h("button", { class: "add", onclick: () => { const r = fieldRow({ name: "", value: "", custom: true }); $("#fields").append(r); $(".lbl-in", r).focus(); } }, "+ Add field"),
    (d.doc_type === "invoice" || d.doc_type === "receipt" || d.line_items.length) ? h("div", {},
      h("div", { class: "sec" }, h("h3", {}, "Line items"), h("span", { class: "sum", id: "itemsSum" })),
      h("table", { class: "items-t" },
        h("colgroup", {}, h("col"), h("col", { class: "q" }), h("col", { class: "u" }), h("col", { class: "a" }), h("col", { style: "width:26px" })),
        h("thead", {}, h("tr", {}, h("th", {}, "Description"), h("th", { class: "n" }, "Qty"), h("th", { class: "n" }, "Price"), h("th", { class: "n" }, "Amount"), h("th"))),
        h("tbody", { id: "itemsBody" }, d.line_items.map(itemRow))),
      h("button", { class: "add", onclick: () => { $("#itemsBody").append(itemRow()); $("#itemsBody tr:last-child input").focus(); } }, "+ Add line")) : null);
  paint(d); itemsSum();
}

function paint(d) {
  // per-field state
  const byField = {};
  for (const i of d.issues) (byField[i.field] ||= []).push(i);
  for (const row of $$("#fields .row")) {
    const n = rowName(row), f = d.fields.find(x => x.name === n), iss = byField[n] || [];
    const val = $(".val", row).value.trim();
    const lvl = iss.some(i => i.level === "error") ? "error" : iss.length ? "warn" : "";
    row.classList.remove("error", "warn", "missing");
    if (lvl) row.classList.add(lvl);
    if (!val && f?.required) row.classList.add("missing");
    const mark = $(".mark", row); mark.className = "mark";
    if (f && val) { if (f.corrected) mark.classList.add("edited"); else if (f.confidence < 0.6 && !iss.length) mark.classList.add("low"); }
  }
  // checks list
  const box = $("#checks"); if (!box) return;
  if (!d.issues.length) { box.className = "checks good"; box.replaceChildren("✓ All checks passed"); }
  else {
    box.className = "checks";
    box.replaceChildren(...[...d.issues].sort((a, b) => (a.level === "error" ? 0 : 1) - (b.level === "error" ? 0 : 1)).map(i =>
      h("div", { class: "chk " + i.level, onclick: () => { const r = $$("#fields .row").find(r => rowName(r) === i.field); const el = r && $(".val", r); if (el) { el.focus(); el.select(); } } },
        h("i"), h("div", {}, BARE.has(i.field) ? null : h("b", {}, humanize(i.field) + " "), h("span", {}, i.message)))));
  }
  // footer
  const errs = d.issues.filter(i => i.level === "error").length, warns = d.issues.length - errs;
  const msg = h("div", { class: "msg" + (errs && !d.verified ? " err" : ""), id: "saveMsg" },
    d.verified ? "Verified" : errs ? `${errs} error${errs > 1 ? "s" : ""} to fix` : warns ? `${warns} warning${warns > 1 ? "s" : ""}` : "Looks good");
  const btn = d.verified
    ? h("button", { class: "btn verify verified", onclick: () => verify(false) }, "✓ Verified")
    : h("button", { class: "btn verify " + (errs ? "soft" : "primary"), onclick: () => verify(true) }, errs ? "Verify anyway" : "Verify", h("kbd", {}, /Mac/.test(navigator.platform) ? "⌘↵" : "Ctrl↵"));
  $("#foot").replaceChildren(msg, btn);
}

/* ---------- saving ---------- */
function collect() {
  const fields = $$("#fields .row").map(r => ({ field: rowName(r), value: $(".val", r).value })).filter(x => x.field);
  const body = $("#itemsBody");
  const line_items = body ? $$("tr", body).map(tr => { const [a, b, c, e] = $$("input", tr).map(i => i.value);
    return { description: a, quantity: b, unit_price: c, amount: e }; }) : undefined;
  return line_items ? { fields, line_items } : { fields };
}
function queueSave() {
  itemsSum(); clearTimeout(S.timer);
  const m = $("#saveMsg"); if (m && !cur()?.verified) { m.className = "msg saving"; m.textContent = "Saving…"; }
  S.timer = setTimeout(() => flush(), 350);
}
function merge(r) {
  const i = S.docs.findIndex(d => d.id === r.doc.id); if (i >= 0) S.docs[i] = r.doc;
  for (const x of r.all || []) { const d = S.docs.find(d => d.id === x.id); if (d && d.id !== r.doc.id) Object.assign(d, { status: x.status, verified: x.verified, issues: x.issues }); }
}
async function flush(extra = {}) {
  clearTimeout(S.timer);
  const d = cur(); if (!d || !$("#fields")) return;
  const my = ++S.seq, id = d.id;
  const payload = { ...collect(), ...extra };
  try {
    const r = await (await api("/api/doc/" + id, { method: "PUT", body: JSON.stringify(payload) })).json();
    merge(r); renderList();
    if (my === S.seq && S.cur === id) {
      const doc = r.doc;
      for (const row of $$("#fields .row")) {                      // adopt normalised values, but never fight the cursor
        const f = doc.fields.find(x => x.name === rowName(row)), el = $(".val", row);
        if (f && document.activeElement !== el && el.value !== f.value) el.value = f.value;
      }
      paint(doc);
    }
  } catch (e) { toast(e.message); }
}
async function verify(on) {
  const d = cur(); if (!d) return;
  await flush({ verified: on });
  if (on) {
    const open = S.docs.filter(isOpen), after = open.find(x => S.docs.indexOf(x) > S.docs.indexOf(cur())) || open[0];
    if (after) { await select(after.id); } else { renderDoc(); toast("All documents verified 🎉"); }
  } else renderDoc();
}
function copyJson() {
  const d = cur(); if (!d) return;
  const o = { filename: d.filename, document_type: d.doc_type,
    fields: Object.fromEntries(d.fields.filter(f => f.value !== "").map(f => [f.name, f.value])), line_items: d.line_items, issues: d.issues };
  navigator.clipboard.writeText(JSON.stringify(o, null, 2)).then(() => toast("Copied JSON"), () => toast("Couldn't access clipboard"));
}

/* ---------- uploading ---------- */
async function addFiles(files) {
  files = [...files]; if (!files.length) return;
  const jobs = files.map(f => ({ f, name: f.name, error: null }));
  S.pending.push(...jobs); render();
  let next = 0;
  const worker = async () => {
    while (next < jobs.length) {
      const job = jobs[next++];
      try {
        const q = `name=${encodeURIComponent(job.name)}&dayfirst=${S.dayfirst ? 1 : 0}`;
        const r = await (await api("/api/process?" + q, { method: "POST", body: job.f })).json();
        S.pending = S.pending.filter(p => p !== job);
        if (r.duplicate) toast(`“${job.name}” was already added`);
        else S.docs.push(r.doc);
        if (!S.cur) S.cur = r.doc.id;
        render();
      } catch (e) { job.error = e.message; renderList(); }
    }
  };
  await Promise.all([worker(), worker()]);
  if (!S.pending.length) { const all = await (await api("/api/docs")).json(); S.docs = all; render(); }   // refresh cross-doc checks
}

/* ---------- chrome ---------- */
function render() {
  const any = S.docs.length || S.pending.length;
  $("#empty").hidden = !!any; $("#main").hidden = !any;
  $("#clearBtn").hidden = !S.docs.length;
  $("#exportBtn").disabled = !S.docs.length;
  if (any) { renderList(); if (!$("#fields") || $("#form").dataset.id !== S.cur) { $("#form").dataset.id = S.cur || ""; renderDoc(); } }
}
function setDateBtn() { $("#datefmt").textContent = S.dayfirst ? "Dates DD/MM" : "Dates MM/DD"; }

function init() {
  setDateBtn();
  $("#datefmt").onclick = () => { S.dayfirst = !S.dayfirst; localStorage.setItem("dayfirst", S.dayfirst ? "1" : "0"); setDateBtn(); toast(S.dayfirst ? "Ambiguous dates read as day/month" : "Ambiguous dates read as month/day"); };
  const pick = () => $("#file").click();
  $("#addBtn").onclick = pick; $("#chooseBtn").onclick = pick;
  $("#file").onchange = e => { addFiles(e.target.files); e.target.value = ""; };
  $("#clearBtn").onclick = async () => { if (!confirm("Remove all documents?")) return; await api("/api/clear", { method: "POST" }); S.docs = []; S.cur = null; render(); };

  const pop = $("#exportPop");
  $("#exportBtn").onclick = e => { e.stopPropagation(); pop.hidden = !pop.hidden; };
  document.addEventListener("click", e => { if (!pop.contains(e.target)) pop.hidden = true; });
  $$("#exportPop a").forEach(a => a.onclick = async () => {
    await flush(); pop.hidden = true;
    const v = $("#verifiedOnly").checked;
    if (v && !S.docs.some(d => d.verified)) return toast("Nothing is verified yet");
    location.href = `/api/export?format=${a.dataset.fmt}${v ? "&verified=1" : ""}`;
  });

  let depth = 0; const veil = $("#veil");
  addEventListener("dragenter", e => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { depth++; veil.hidden = false; } });
  addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; veil.hidden = true; } });
  addEventListener("dragover", e => e.preventDefault());
  addEventListener("drop", e => { e.preventDefault(); depth = 0; veil.hidden = true; addFiles(e.dataTransfer.files); });

  addEventListener("keydown", e => {
    const d = cur();
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && d) { e.preventDefault(); verify(!d.verified); return; }
    if ($(".val:focus,.lbl-in:focus,#itemsBody input:focus,select:focus") || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "j" || e.key === "k" || e.key === "ArrowDown" || e.key === "ArrowUp") {
      const list = visible(), i = list.findIndex(x => x.id === S.cur); if (!list.length) return;
      e.preventDefault(); select(list[Math.max(0, Math.min(list.length - 1, i + (e.key === "j" || e.key === "ArrowDown" ? 1 : -1)))].id);
    }
  });
  addEventListener("beforeunload", () => { if (S.timer) flush(); });

  api("/api/docs").then(r => r.json()).then(docs => { S.docs = docs; S.cur = (docs.find(isOpen) || docs[0] || {}).id || null; render(); });
}
init();
})();
