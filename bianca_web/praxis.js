/* Praxis-Synchronisierung fuer eingebettete Bianca-Seiten.
   Sichtbar gewaehlt wird ausschliesslich im globalen Lisa/Bianca-Header. */
"use strict";

const PRAXIS_KEY = "pickadoc.praxis";

function praxisLesen() {
  try {
    const q = new URLSearchParams(location.search).get("tenant");
    if (q) {
      praxisSchreiben(q, { still: true });
      return q;
    }
    return localStorage.getItem(PRAXIS_KEY) || "";
  } catch {
    return "";
  }
}

function praxisSchreiben(id, opts) {
  const wert = String(id || "").trim();
  try { localStorage.setItem(PRAXIS_KEY, wert); } catch { /* */ }
  if (opts && opts.still) return;
  try {
    const u = new URL(location.href);
    if (wert) u.searchParams.set("tenant", wert);
    else u.searchParams.delete("tenant");
    history.replaceState(null, "", u);
  } catch { /* */ }
}

function praxisImFrame() {
  try { return window.self !== window.top; } catch { return true; }
}

function praxisKurz(t) {
  const id = String((t && t.id) || "");
  if (id === "meddent") return "Medical Center";
  if (id === "thaler") return "Thaler";
  if (id === "blessing") return "Blessing";
  const n = String((t && t.praxisName) || id);
  return n.length > 26 ? n.slice(0, 24) + "…" : n;
}

async function praxisTenants(url) {
  const r = await fetch(url || "api/tenants", { cache: "no-store" });
  if (!r.ok) return { tenants: [], default: "" };
  return r.json();
}

function praxisLeisteCss() {
  if (document.getElementById("praxis-leiste-css")) return;
  const s = document.createElement("style");
  s.id = "praxis-leiste-css";
  s.textContent = `
    :root { --praxis-leiste-h: calc(54px + env(safe-area-inset-top, 0px)); }
    #praxis-leiste {
      position: fixed; top: 0; left: 0; right: 0; z-index: 90;
      display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
      min-height: 48px;
      padding: 7px 14px;
      padding-top: calc(7px + env(safe-area-inset-top, 0px));
      background: #16141a; border-bottom: 1px solid #3a3238;
      color: #efe8ec;
      font: 13px/1.3 "Segoe UI", system-ui, sans-serif;
    }
    #praxis-leiste .praxis-label {
      font-size: 11px; letter-spacing: .04em; text-transform: uppercase;
      color: #a38f9c; white-space: nowrap;
    }
    #praxis-leiste select.praxis-sel {
      position: absolute; width: 1px; height: 1px; overflow: hidden;
      clip: rect(0,0,0,0);
    }
    #praxis-chips { display: flex; gap: 6px; flex-wrap: wrap; min-width: 0; }
    #praxis-chips .praxis-chip {
      appearance: none; cursor: pointer; font: inherit; font-weight: 650;
      padding: 5px 11px; border-radius: 999px;
      background: #211a20; color: #efe8ec; border: 1px solid #382c35;
    }
    #praxis-chips .praxis-chip.an {
      background: #2a1c26; border-color: #ba3d78; color: #f3d4e6;
    }
    body.hat-praxis-leiste { padding-top: var(--praxis-leiste-h); }
    body.hat-praxis-leiste .kopf,
    body.hat-praxis-leiste header {
      top: var(--praxis-leiste-h);
    }
    body.hat-praxis-leiste .tenant-wahl { display: none !important; }
  `;
  document.head.appendChild(s);
}

function praxisLeisteSichern() {
  praxisLeisteCss();
  let bar = document.getElementById("praxis-leiste");
  let sel = document.getElementById("tenant");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "praxis-leiste";
    const span = document.createElement("span");
    span.className = "praxis-label";
    span.textContent = "Praxis";
    if (!sel) {
      sel = document.createElement("select");
      sel.id = "tenant";
    }
    sel.classList.add("praxis-sel");
    const chips = document.createElement("div");
    chips.id = "praxis-chips";
    bar.appendChild(span);
    bar.appendChild(sel);
    bar.appendChild(chips);
    document.body.insertBefore(bar, document.body.firstChild);
    document.body.classList.add("hat-praxis-leiste");
  } else if (sel && !bar.contains(sel)) {
    sel.classList.add("praxis-sel");
    bar.appendChild(sel);
  }
  return document.getElementById("tenant");
}

function praxisChipsZeichnen(el, liste, wahl) {
  const box = document.getElementById("praxis-chips");
  if (!box) return;
  box.innerHTML = "";
  liste.forEach((t) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "praxis-chip" + (t.id === wahl ? " an" : "");
    b.textContent = praxisKurz(t);
    b.addEventListener("click", () => {
      if (el.value === t.id) return;
      el.value = t.id;
      el.dispatchEvent(new Event("change"));
    });
    box.appendChild(b);
  });
}

async function praxisSelectFuellen(el, opts) {
  if (!el) return "";
  const opt = opts || {};
  const data = await praxisTenants(opt.url);
  const liste = (data.tenants || []).filter((t) => t.id !== "demo" || opt.demo);
  const aktuell = praxisLesen();
  const ids = new Set(liste.map((t) => t.id));
  const wahl = ids.has(aktuell)
    ? aktuell
    : (ids.has(data.default) ? data.default : ((liste[0] && liste[0].id) || ""));
  el.innerHTML = liste.map((t) =>
    `<option value="${t.id}">${t.praxisName || t.id}</option>`
  ).join("");
  if (wahl) el.value = wahl;
  if (wahl && aktuell !== wahl) praxisSchreiben(wahl);
  if (!opt.nurSync) praxisChipsZeichnen(el, liste, el.value);
  const melden = () => {
    praxisSchreiben(el.value);
    if (!opt.nurSync) praxisChipsZeichnen(el, liste, el.value);
    if (typeof opt.onchange === "function") opt.onchange(el.value);
  };
  el.onchange = melden;
  window.addEventListener("storage", (ev) => {
    if (ev.key !== PRAXIS_KEY) return;
    const neu = ev.newValue || "";
    if (!neu || neu === el.value || !ids.has(neu)) return;
    el.value = neu;
    if (!opt.nurSync) praxisChipsZeichnen(el, liste, neu);
    if (typeof opt.onchange === "function") opt.onchange(neu);
  });
  return el.value;
}

async function praxisSeiteStart(opts) {
  const opt = opts || {};
  let sel = document.getElementById("tenant");
  if (!sel) {
    sel = document.createElement("select");
    sel.id = "tenant";
    document.body.appendChild(sel);
  }
  sel.hidden = true;
  return praxisSelectFuellen(sel, Object.assign({}, opt, { nurSync: true }));
}

window.addEventListener("message", (ev) => {
  if (ev.origin !== location.origin) return;
  const d = ev.data || {};
  if (d.type !== "pickadoc:tenant" || !d.tenant) return;
  const sel = document.getElementById("tenant");
  praxisSchreiben(d.tenant, { still: true });
  if (!sel || sel.value === d.tenant) return;
  const vorhanden = [...sel.options].some((o) => o.value === d.tenant);
  if (!vorhanden) return;
  sel.value = d.tenant;
  sel.dispatchEvent(new Event("change"));
});
