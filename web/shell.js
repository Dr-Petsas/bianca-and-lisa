/* Globale Navigation und Mandantenwahl fuer Bianca, Lisa und Teststudio. */
"use strict";

(function () {
  const TENANT_KEY = "pickadoc.praxis";
  const TAB_KEY = "pickadoc.haupttab";
  const $ = (id) => document.getElementById(id);
  const frames = {
    bianca: $("biancaFrame"),
    studio: $("studioFrame"),
  };
  const geladen = { bianca: false, studio: "" };
  let aktiverTab = "bianca";
  let studioSeite = "konfigurator";
  let lastPoller = null;

  const studioPfade = {
    konfigurator: "/bianca/studio/",
    ergebnisse: "/bianca/studio/ergebnisse/",
    "bianca-anrufe": "/bianca/anrufe",
    "lisa-anrufe": "/lisa-anrufe",
  };

  function tenantLesen() {
    const sel = $("tenant");
    if (sel && sel.value) return sel.value;
    try { return localStorage.getItem(TENANT_KEY) || ""; } catch { return ""; }
  }

  function tenantSenden(frame) {
    if (!frame || !frame.contentWindow) return;
    try {
      frame.contentWindow.postMessage({
        type: "pickadoc:tenant",
        tenant: tenantLesen(),
      }, location.origin);
    } catch { /* iframe noch nicht bereit */ }
  }

  function alleFramesSynchronisieren() {
    tenantSenden(frames.bianca);
    tenantSenden(frames.studio);
    window.dispatchEvent(new CustomEvent("pickadoc:tenant", {
      detail: { tenant: tenantLesen() },
    }));
  }

  function tenantSetzen(id, melden) {
    const wert = String(id || "").trim();
    if (!wert) return;
    const sel = $("tenant");
    if (sel && sel.value !== wert) sel.value = wert;
    try { localStorage.setItem(TENANT_KEY, wert); } catch { /* */ }
    if (melden !== false) alleFramesSynchronisieren();
  }

  async function tenantsLaden() {
    const sel = $("tenant");
    if (!sel) return "";
    const r = await fetch("/api/tenants", { cache: "no-store" });
    if (!r.ok) throw new Error("Mandanten konnten nicht geladen werden");
    const data = await r.json();
    const liste = (data.tenants || []).filter((t) => t.id !== "demo");
    let gespeichert = "";
    try { gespeichert = localStorage.getItem(TENANT_KEY) || ""; } catch { /* */ }
    const ids = new Set(liste.map((t) => t.id));
    const wahl = ids.has(gespeichert)
      ? gespeichert
      : (ids.has(data.default) ? data.default : ((liste[0] && liste[0].id) || ""));
    sel.innerHTML = liste.map((t) =>
      `<option value="${t.id}">${t.praxisName || t.id}</option>`
    ).join("");
    if (wahl) sel.value = wahl;
    tenantSetzen(wahl, false);
    sel.addEventListener("change", () => tenantSetzen(sel.value, true));
    return wahl;
  }

  function biancaLaden() {
    if (geladen.bianca) {
      tenantSenden(frames.bianca);
      return;
    }
    geladen.bianca = true;
    fetch("/bianca/health")
      .then((r) => {
        if (!r.ok) throw new Error("Bianca down");
        frames.bianca.src = "/bianca/?embedded=1&cb=global1";
      })
      .catch(() => {
        $("biancaHinweis").hidden = false;
      });
  }

  function studioLaden(seite) {
    studioSeite = studioPfade[seite] ? seite : "konfigurator";
    const pfad = studioPfade[studioSeite];
    document.querySelectorAll("#studioUnternavi [data-studio]").forEach((b) => {
      b.classList.toggle("active", b.dataset.studio === studioSeite);
    });
    if (geladen.studio !== pfad) {
      geladen.studio = pfad;
      frames.studio.src = `${pfad}?embedded=1&cb=global1`;
    } else {
      tenantSenden(frames.studio);
    }
  }

  function hashFuer(tab) {
    if (tab !== "studio") return "#" + tab;
    return studioSeite === "konfigurator" ? "#studio" : "#studio-" + studioSeite;
  }

  function zeige(tab, opts) {
    const o = opts || {};
    aktiverTab = ["bianca", "lisa", "studio"].includes(tab) ? tab : "bianca";
    $("tab-lisa").hidden = aktiverTab !== "lisa";
    $("tab-bianca").hidden = aktiverTab !== "bianca";
    $("tab-studio").hidden = aktiverTab !== "studio";
    $("studioUnternavi").hidden = aktiverTab !== "studio";
    document.body.classList.toggle("frame-aktiv", aktiverTab !== "lisa");
    document.body.classList.toggle("bianca-aktiv", aktiverTab === "bianca");
    document.querySelectorAll("#tabs [data-tab]").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === aktiverTab);
    });
    if (aktiverTab === "bianca") biancaLaden();
    if (aktiverTab === "studio") studioLaden(o.studio || studioSeite);
    try { localStorage.setItem(TAB_KEY, aktiverTab); } catch { /* */ }
    const ziel = hashFuer(aktiverTab);
    if (!o.vomHash && location.hash !== ziel) history.replaceState(null, "", ziel);
  }

  function ausHash() {
    const h = location.hash.replace(/^#/, "");
    if (h === "lisa" || h === "bianca") return { tab: h };
    if (h === "studio") return { tab: "studio", studio: "konfigurator" };
    if (h.startsWith("studio-")) {
      const s = h.slice("studio-".length);
      if (studioPfade[s]) return { tab: "studio", studio: s };
    }
    return null;
  }

  function lastPlanZeichnen(plan) {
    const box = $("lasttestVerteilung");
    if (!box) return;
    box.innerHTML = ((plan && plan.kunden) || []).map((k) =>
      `<div><span class="last-punkt" style="background:${k.farbe || "#8fa39a"}"></span>` +
      `<span>${k.kurz || k.id}</span><strong>${k.n || 0}</strong></div>`
    ).join("");
  }

  async function lastPlanLaden() {
    const n = Number($("lasttestN").value || 6);
    $("lasttestNWert").textContent = String(n);
    try {
      const r = await fetch(`/bianca/studio/api/lasttest/plan?n=${n}`, { cache: "no-store" });
      lastPlanZeichnen(await r.json());
    } catch {
      $("lasttestVerteilung").textContent = "Verteilung nicht abrufbar.";
    }
  }

  function lastStatusZeichnen(lt) {
    if (!lt) return;
    const box = $("lasttestStatus");
    const e = lt.ergebnis || {};
    if (lt.phase === "fertig") {
      box.innerHTML = `<strong>Fertig: ${e.gehalten || 0}/${lt.n || 0} gehalten</strong>` +
        `<span> · Fehler ${e.fehler || 0} · erster Ton P95 ${e.ersterTonP95 || 0}s</span>`;
      $("lasttestStart").disabled = false;
      if (lastPoller) clearInterval(lastPoller);
      lastPoller = null;
      return;
    }
    if (lt.phase === "fehler") {
      box.textContent = lt.fehler || "Belastungstest fehlgeschlagen";
      $("lasttestStart").disabled = false;
      if (lastPoller) clearInterval(lastPoller);
      lastPoller = null;
      return;
    }
    box.textContent = `Läuft: ${lt.fertig || 0}/${lt.n || 0} Gespräche abgeschlossen`;
  }

  async function lastPoll() {
    try {
      const r = await fetch("/bianca/studio/api/live", { cache: "no-store" });
      const d = await r.json();
      if (d.lasttest) lastStatusZeichnen(d.lasttest);
    } catch { /* nächster Tick */ }
  }

  async function lastStarten() {
    const n = Number($("lasttestN").value || 6);
    $("lasttestStart").disabled = true;
    $("lasttestStatus").textContent = "Startet …";
    try {
      const r = await fetch("/bianca/studio/api/lasttest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ n, zuege: 2 }),
      });
      const d = await r.json();
      if (!r.ok || !d.ok) throw new Error(d.fehler || "Start fehlgeschlagen");
      lastPlanZeichnen(d.plan);
      if (lastPoller) clearInterval(lastPoller);
      lastPoller = setInterval(lastPoll, 450);
      lastPoll();
    } catch (e) {
      $("lasttestStatus").textContent = String(e.message || e);
      $("lasttestStart").disabled = false;
    }
  }

  function eventsBinden() {
    $("tabs").addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-tab]");
      if (b) zeige(b.dataset.tab);
    });
    $("studioUnternavi").addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-studio]");
      if (!b) return;
      studioLaden(b.dataset.studio);
      history.replaceState(null, "", hashFuer("studio"));
    });
    frames.bianca.addEventListener("load", () => tenantSenden(frames.bianca));
    frames.studio.addEventListener("load", () => tenantSenden(frames.studio));
    window.addEventListener("hashchange", () => {
      const z = ausHash();
      if (z) zeige(z.tab, { studio: z.studio, vomHash: true });
    });
    $("lasttestGlobal").addEventListener("click", () => {
      $("lasttestModal").hidden = false;
      $("lasttestStatus").textContent = "";
      lastPlanLaden();
    });
    $("lasttestZu").addEventListener("click", () => {
      $("lasttestModal").hidden = true;
    });
    $("lasttestN").addEventListener("input", lastPlanLaden);
    $("lasttestStart").addEventListener("click", lastStarten);
  }

  async function boot() {
    eventsBinden();
    await tenantsLaden();
    const z = ausHash();
    let start = z || { tab: "bianca" };
    if (!z) {
      try {
        const alt = localStorage.getItem(TAB_KEY);
        if (alt === "lisa" || alt === "studio") start = { tab: alt };
      } catch { /* */ }
    }
    zeige(start.tab, { studio: start.studio });
    alleFramesSynchronisieren();
    return tenantLesen();
  }

  window.pickadocTenant = tenantLesen;
  window.pickadocShellReady = boot();
})();
