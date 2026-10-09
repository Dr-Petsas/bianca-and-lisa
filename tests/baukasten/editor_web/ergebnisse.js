/* Ergebnisseite: Laeufe -> Stories (gruen/rot) -> Bubble-Dialog mit Latenz,
   Waechter und Audio je Zug; ganzer Anruf abspielbar. */
"use strict";

const $ = (id) => document.getElementById(id);
let aktuellerLauf = "";
let spielListe = [];
let letzteStatistik = null;
let letzteLive = null;
const PRAXIS_FARBE = {
  meddent: "#4da3ff",
  thaler: "#37c978",
  blessing: "#e5a84b",
  ruether: "#d862c8",
  unbekannt: "#8b96a5",
};
const lautsprecher = new Audio();
lautsprecher.preload = "auto";
lautsprecher.playsInline = true;

function studioWurzel() {
  const p = location.pathname.replace(/\/+$/, "") || "";
  if (p.endsWith("/ergebnisse")) return p.slice(0, -"/ergebnisse".length) + "/";
  return p ? p + "/" : "/";
}

function tonUrl(rel) {
  if (!rel) return "";
  if (/^(https?:|blob:|data:)/i.test(rel)) return rel;
  return new URL(rel.replace(/^\//, ""), location.origin + studioWurzel()).href;
}

function spielen(rel) {
  const url = tonUrl(rel);
  if (!url) return Promise.resolve();
  return (async () => {
    let blob = null;
    for (let i = 0; i < 5; i++) {
      try {
        const r = await fetch(url, { cache: "no-store" });
        if (r.ok) {
          blob = await r.blob();
          if (blob && blob.size > 44) break;
        }
      } catch { /* */ }
      await new Promise((w) => setTimeout(w, 180));
    }
    if (!blob || blob.size < 44) {
      console.warn("studio-ton fehlt", url);
      return;
    }
    const obj = URL.createObjectURL(blob);
    try {
      try { lautsprecher.pause(); } catch { /* */ }
      lautsprecher.src = obj;
      await lautsprecher.play();
      await new Promise((fertig) => {
        const ende = () => {
          lautsprecher.removeEventListener("ended", ende);
          lautsprecher.removeEventListener("error", ende);
          lautsprecher.removeEventListener("pause", ende);
          lautsprecher.removeEventListener("emptied", ende);
          fertig();
        };
        lautsprecher.addEventListener("ended", ende);
        lautsprecher.addEventListener("error", ende);
        lautsprecher.addEventListener("pause", ende);
        lautsprecher.addEventListener("emptied", ende);
      });
    } catch (e) {
      console.warn("studio-ton play", url, e);
    } finally {
      try { URL.revokeObjectURL(obj); } catch { /* */ }
    }
  })();
}

function tenantQ() {
  let t = "";
  try { t = localStorage.getItem("pickadoc.praxis") || ""; } catch { /* */ }
  return t ? ("?tenant=" + encodeURIComponent(t)) : "";
}

function tenantSetzen(id) {
  const wert = String(id || "").trim();
  if (!wert) return;
  try { localStorage.setItem("pickadoc.praxis", wert); } catch { /* */ }
  aktuellerLauf = "";
  location.hash = "";
  $("stories").innerHTML = "";
  $("block-dialog").style.display = "none";
  datenLaden();
}

function esc(text) {
  return String(text == null ? "" : text).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function datumKurz(text) {
  const m = String(text || "").match(/^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/);
  if (!m) return "—";
  if (m[4]) return `${m[3]}.${m[2]}. ${m[4]}:${m[5]}`;
  return `${m[3]}.${m[2]}.`;
}

function chartKontext(id) {
  const canvas = $(id);
  const breite = Math.max(300, Math.round(canvas.getBoundingClientRect().width || 760));
  const hoehe = 230;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.round(breite * dpr);
  canvas.height = Math.round(hoehe * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, breite, hoehe);
  return { ctx, breite, hoehe };
}

function grundraster(ctx, breite, hoehe, maxY, suffix) {
  const rand = { l: 38, r: 12, t: 14, b: 28 };
  const innenH = hoehe - rand.t - rand.b;
  ctx.font = "11px Segoe UI, sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 4; i++) {
    const y = rand.t + innenH * i / 4;
    const wert = Math.round(maxY * (1 - i / 4));
    ctx.strokeStyle = "#2a3442";
    ctx.beginPath(); ctx.moveTo(rand.l, y); ctx.lineTo(breite - rand.r, y); ctx.stroke();
    ctx.fillStyle = "#8b96a5";
    ctx.fillText(wert + (suffix || ""), rand.l - 5, y);
  }
  return { ...rand, w: breite - rand.l - rand.r, h: innenH };
}

function xBeschriften(ctx, daten, box) {
  if (!daten.length) return;
  ctx.fillStyle = "#8b96a5";
  ctx.font = "10px Segoe UI, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const schritt = Math.max(1, Math.ceil(daten.length / 6));
  daten.forEach((d, i) => {
    if (i % schritt && i !== daten.length - 1) return;
    const x = box.l + box.w * (daten.length === 1 ? 0.5 : i / (daten.length - 1));
    ctx.fillText(datumKurz(d.datum), x, box.t + box.h + 7);
  });
}

function chartErfolg(daten) {
  const { ctx, breite, hoehe } = chartKontext("chart-erfolg");
  const box = grundraster(ctx, breite, hoehe, 100, "%");
  if (!daten.length) {
    ctx.fillStyle = "#8b96a5"; ctx.textAlign = "center";
    ctx.fillText("Noch keine Zeitreihe", breite / 2, hoehe / 2);
    return;
  }
  ctx.strokeStyle = "#37c978";
  ctx.lineWidth = 3;
  ctx.beginPath();
  daten.forEach((d, i) => {
    const x = box.l + box.w * (daten.length === 1 ? 0.5 : i / (daten.length - 1));
    const y = box.t + box.h * (1 - Number(d.erfolgsquote || 0) / 100);
    if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
  });
  ctx.stroke();
  daten.forEach((d, i) => {
    const x = box.l + box.w * (daten.length === 1 ? 0.5 : i / (daten.length - 1));
    const y = box.t + box.h * (1 - Number(d.erfolgsquote || 0) / 100);
    ctx.fillStyle = Number(d.erfolgsquote || 0) >= 80 ? "#37c978" : "#ff5f6b";
    ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
  });
  xBeschriften(ctx, daten, box);
}

function chartVolumen(daten) {
  const { ctx, breite, hoehe } = chartKontext("chart-volumen");
  const maxY = Math.max(1, ...daten.map((d) => Math.max(d.gespraeche || 0, d.turns || 0)));
  const box = grundraster(ctx, breite, hoehe, maxY, "");
  if (!daten.length) {
    ctx.fillStyle = "#8b96a5"; ctx.textAlign = "center";
    ctx.fillText("Noch keine Zeitreihe", breite / 2, hoehe / 2);
    return;
  }
  const gruppe = box.w / daten.length;
  daten.forEach((d, i) => {
    const mitte = box.l + gruppe * (i + 0.5);
    const bw = Math.max(3, Math.min(16, gruppe * 0.3));
    const h1 = box.h * Number(d.gespraeche || 0) / maxY;
    const h2 = box.h * Number(d.turns || 0) / maxY;
    ctx.fillStyle = "#d862c8";
    ctx.fillRect(mitte - bw - 1, box.t + box.h - h1, bw, h1);
    ctx.fillStyle = "#4da3ff";
    ctx.fillRect(mitte + 1, box.t + box.h - h2, bw, h2);
  });
  xBeschriften(ctx, daten, box);
  ctx.font = "11px Segoe UI, sans-serif"; ctx.textAlign = "left";
  ctx.fillStyle = "#d862c8"; ctx.fillText("■ Gespräche", box.l + 4, box.t + 7);
  ctx.fillStyle = "#4da3ff"; ctx.fillText("■ Züge", box.l + 90, box.t + 7);
}

function praxisFarbe(id) {
  return PRAXIS_FARBE[id] || "#8d76ef";
}

function isoMs(text) {
  const t = Date.parse(String(text || ""));
  return Number.isFinite(t) ? t : 0;
}

function uhrKurz(text) {
  const d = new Date(isoMs(text));
  if (!isoMs(text)) return "—";
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${dd}.${mm}. ${hh}:${mi}`;
}

const PRAXIS_REIHE = [
  { id: "meddent", name: "MedDent" },
  { id: "thaler", name: "Thaler" },
  { id: "blessing", name: "Blessing" },
  { id: "ruether", name: "Rüther" },
];

function bahnenFenster() {
  const von = isoMs(letzteLive && letzteLive.seit);
  const bis = Date.now();
  if (!von || bis <= von) return null;
  return { von, bis };
}

function xAufZeit(box, fen, t) {
  const ms = isoMs(t);
  const breit = box.w;
  if (!fen || fen.bis <= fen.von) return box.l;
  const anteil = Math.min(1, Math.max(0, (ms - fen.von) / (fen.bis - fen.von)));
  return box.l + anteil * breit;
}

function chartLast(aus) {
  const { ctx, breite, hoehe } = chartKontext("chart-last");
  const verlauf = (aus && aus.verlauf) || [];
  const fen = bahnenFenster();
  const maxY = Math.max(1, ...verlauf.map((p) => Number(p.n || 0)), Number((aus && aus.spitze && aus.spitze.n) || 1));
  const box = grundraster(ctx, breite, hoehe, maxY, "");
  if (!verlauf.length) {
    ctx.fillStyle = "#8b96a5"; ctx.textAlign = "center";
    ctx.fillText("Noch keine gleichzeitigen Anrufe", breite / 2, hoehe / 2);
    return;
  }
  const von = fen ? fen.von : isoMs(verlauf[0].t);
  const bis = fen ? fen.bis : isoMs(verlauf[verlauf.length - 1].t);
  const achse = { von, bis: Math.max(bis, von + 1) };
  const punkte = [{ t: new Date(von).toISOString(), n: 0 }].concat(verlauf);
  ctx.strokeStyle = "#4da3ff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  punkte.forEach((p, i) => {
    const x = xAufZeit(box, achse, p.t);
    const y = box.t + box.h * (1 - Number(p.n || 0) / maxY);
    if (!i) ctx.moveTo(x, box.t + box.h);
    ctx.lineTo(x, y);
  });
  ctx.lineTo(box.l + box.w, box.t + box.h);
  ctx.stroke();
  ctx.fillStyle = "#8b96a5";
  ctx.font = "10px Segoe UI, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText(uhrKurz(new Date(von).toISOString()), box.l, box.t + box.h + 7);
  ctx.fillText(uhrKurz(new Date(bis).toISOString()), box.l + box.w, box.t + box.h + 7);
}

function chartDrift(aus) {
  const { ctx, breite, hoehe } = chartKontext("chart-drift");
  const daten = ((aus && aus.latenz && aus.latenz.nachLast) || []);
  const maxY = Math.max(1, ...daten.map((d) => Math.max(Number(d.mittelS || 0), Number(d.p90S || 0))));
  const box = grundraster(ctx, breite, hoehe, Math.ceil(maxY), "s");
  if (!daten.length) {
    ctx.fillStyle = "#8b96a5"; ctx.textAlign = "center";
    ctx.fillText("Noch keine Zug-Latenzen", breite / 2, hoehe / 2);
    return;
  }
  const gruppe = box.w / daten.length;
  daten.forEach((d, i) => {
    const mitte = box.l + gruppe * (i + 0.5);
    const bw = Math.max(4, Math.min(18, gruppe * 0.28));
    const h1 = box.h * Number(d.mittelS || 0) / maxY;
    const h2 = box.h * Number(d.p90S || 0) / maxY;
    ctx.fillStyle = "#4da3ff";
    ctx.fillRect(mitte - bw - 1, box.t + box.h - h1, bw, h1);
    ctx.fillStyle = "#e5a84b";
    ctx.fillRect(mitte + 1, box.t + box.h - h2, bw, h2);
    ctx.fillStyle = "#8b96a5";
    ctx.font = "10px Segoe UI, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(String(d.gleichzeitig) + "×", mitte, box.t + box.h + 7);
  });
  ctx.font = "11px Segoe UI, sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
  ctx.fillStyle = "#4da3ff"; ctx.fillText("■ Mittel", box.l + 4, box.t + 7);
  ctx.fillStyle = "#e5a84b"; ctx.fillText("■ p90", box.l + 80, box.t + 7);
}

function bahnenReihen(aus) {
  const extra = ((aus && aus.praxen) || []).filter((p) => !PRAXIS_REIHE.some((f) => f.id === p.id));
  const filter = letzteLive && letzteLive.tenant;
  if (filter) {
    const fest = PRAXIS_REIHE.find((f) => f.id === filter);
    return [fest || { id: filter, name: filter }].concat(extra.filter((p) => p.id === filter));
  }
  return PRAXIS_REIHE.concat(extra);
}

function bahnenLegen(intervalle) {
  const nach = {};
  (intervalle || []).forEach((iv) => {
    const id = iv.tenant || "unbekannt";
    (nach[id] || (nach[id] = [])).push(iv);
  });
  const aus = {};
  Object.keys(nach).forEach((id) => {
    const sortiert = nach[id].slice().sort((a, b) => isoMs(a.von) - isoMs(b.von));
    const freiBis = [];
    const balken = [];
    sortiert.forEach((iv) => {
      const start = isoMs(iv.von);
      const ende = Math.max(start + 1000, isoMs(iv.bis));
      let lane = freiBis.findIndex((bis) => bis <= start);
      if (lane < 0) {
        lane = freiBis.length;
        freiBis.push(ende);
      } else {
        freiBis[lane] = ende;
      }
      balken.push({ iv, lane });
    });
    aus[id] = { n: Math.max(1, freiBis.length), balken };
  });
  return aus;
}

function chartBahnen(aus) {
  const canvas = $("chart-bahnen");
  const intervalle = (aus && aus.intervalle) || [];
  const gelegt = bahnenLegen(intervalle);
  const reihen = bahnenReihen(aus).map((p) => ({
    ...p,
    bahnen: Math.max(1, (gelegt[p.id] && gelegt[p.id].n) || 1),
  }));
  const bahnH = 16;
  const hoehe = Math.max(120, 34 + reihen.reduce((s, p) => s + p.bahnen * bahnH + 10, 0));
  const breite = Math.max(300, Math.round(canvas.getBoundingClientRect().width || 760));
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.round(breite * dpr);
  canvas.height = Math.round(hoehe * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, breite, hoehe);
  const rand = { l: 78, r: 12, t: 10, b: 22 };
  const fen = bahnenFenster();
  const datenVon = Math.min(...intervalle.map((i) => isoMs(i.von)).filter(Boolean));
  const von = fen ? fen.von : (Number.isFinite(datenVon) ? datenVon : Date.now() - 3600000);
  const bis = Math.max(fen ? fen.bis : Date.now(), von + 60000);
  const achse = { von, bis };
  const innenW = breite - rand.l - rand.r;
  let y = rand.t;
  reihen.forEach((p, i) => {
    const zeileH = p.bahnen * bahnH + 10;
    ctx.fillStyle = i % 2 ? "#141a22" : "#12171e";
    ctx.fillRect(rand.l, y, innenW, zeileH);
    ctx.fillStyle = "#8b96a5";
    ctx.font = "11px Segoe UI, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(p.name || p.id, rand.l - 6, y + zeileH / 2);
    const balken = (gelegt[p.id] && gelegt[p.id].balken) || [];
    balken.forEach((b) => {
      const x0 = xAufZeit({ l: rand.l, w: innenW }, achse, b.iv.von);
      const x1 = xAufZeit({ l: rand.l, w: innenW }, achse, b.iv.bis);
      ctx.fillStyle = praxisFarbe(b.iv.tenant);
      ctx.fillRect(x0, y + 5 + b.lane * bahnH, Math.max(3, x1 - x0), bahnH - 4);
    });
    y += zeileH;
  });
  ctx.fillStyle = "#8b96a5";
  ctx.font = "10px Segoe UI, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText(uhrKurz(new Date(von).toISOString()), rand.l, hoehe - rand.b + 4);
  ctx.fillText("jetzt", breite - rand.r, hoehe - rand.b + 4);
}

function kpiKarten(g) {
  const anliegenQuote = g.anliegenQuote == null
    ? ["—", ""]
    : [`${Number(g.anliegenQuote).toFixed(1)} %`, Number(g.anliegenQuote) >= 70 ? "ok" : "bad"];
  return [
    ["Gespräche", g.gespraeche || 0, ""],
    ["Anliegen erkannt", g.anliegenErkannt || 0, ""],
    ["Anliegen erfolgreich", g.anliegenErledigt || 0, "ok"],
    ["Nicht erfolgreich", g.anliegenFail || 0, (g.anliegenFail || 0) ? "bad" : "ok"],
    ["davon Bianca-Fehler", g.anliegenBiancaFehler || 0, (g.anliegenBiancaFehler || 0) ? "bad" : "ok"],
    ["davon kein passender Termin", g.anliegenKeinTermin || 0, ""],
    ["davon Anrufer aufgelegt", g.anliegenAufgelegt || 0, ""],
    ["Anliegen-Quote", anliegenQuote[0], anliegenQuote[1]],
    ["CFs ok", g.cfOk || 0, "ok"],
    ["CFs kein Termin", g.cfLeer || 0, ""],
    ["CFs fail", g.cfFail || 0, (g.cfFail || 0) ? "bad" : "ok"],
    ["Gleichzeitig max", g.gleichzeitigMax || 0, ""],
    ["Latenzdrift", `${Number(g.latenzDeltaS || 0) >= 0 ? "+" : ""}${Number(g.latenzDeltaS || 0).toFixed(2)} s`, Number(g.latenzDeltaS || 0) > 0.4 ? "bad" : "ok"],
  ];
}

function kpisZeichnen(zielId, g) {
  const el = $(zielId);
  if (!el) return;
  el.innerHTML = kpiKarten(g || {}).map(([name, wert, klasse]) =>
    `<div class="stat-kpi"><span class="klein">${esc(name)}</span><span class="wert ${klasse}">${esc(wert)}</span></div>`
  ).join("");
}

function liveKpis(d) {
  kpisZeichnen("live-kpis", d.gesamt || {});
  const last = d.auslastung || {};
  const spitze = last.spitze || {};
  const namen = (spitze.praxen || []).map((p) => p.name || p.id).join(", ");
  const um = d.umstellung || {};
  const ab = d.seit ? ` Zählung ab ${uhrKurz(d.seit)}.` : "";
  $("live-hinweis").textContent = (d.tenant
    ? `Gefiltert auf ${d.tenant}. `
    : "Alle Praxen. ") +
    "Diese Karten gelten seit 20:00 Uhr und werden um 20:00 wieder auf null gesetzt." + ab;
  const block = $("vergleich-block");
  const vorher = d.vorher;
  if (block) {
    block.hidden = !vorher;
    if (vorher && $("vorher-kpis")) {
      const pg = vorher.gesamt || {};
      $("vorher-kpis").innerHTML = kpiKarten(pg).map(([name, wert, klasse]) =>
        `<div class="stat-kpi"><span class="klein">${esc(name)}</span><span class="wert ${klasse}">${esc(wert)}</span></div>`
      ).join("");
      if ($("vergleich-hinweis")) {
        $("vergleich-hinweis").textContent =
          `Gesicherter Stand vor der Umstellung${um.umgestelltAt ? " · " + uhrKurz(um.umgestelltAt) : ""}. ` +
          `Morgen um dieselbe Uhrzeit legen wir beide Zahlen nebeneinander.`;
      }
    }
  }
  $("last-spitze").textContent = spitze.n
    ? `Spitze: ${spitze.n} gleichzeitige Anrufe${spitze.zeit ? " · " + uhrKurz(spitze.zeit) : ""}${namen ? " · " + namen : ""}. ` +
      (last.alleGleichzeitigN ? `${last.alleGleichzeitigN} Zeitfenster, in denen alle gesehenen Biancas gleichzeitig liefen. ` : "Kein Fenster, in dem alle Biancas gleichzeitig liefen. ") +
      `Latenz allein ${Number((last.latenz || {}).alleinS || 0).toFixed(2)} s, bei Überlappung ${Number((last.latenz || {}).gleichzeitigS || 0).toFixed(2)} s.`
    : "Noch keine überlappenden Anrufe.";
}

function gespraechLink(g, extra) {
  const marke = extra ? ` <span class="klein">${esc(extra)}</span>` : "";
  if (!g || !g.sid) {
    return `<span class="problem-gespraech tot">${esc((g && g.tenant) || "Gespräch")}${marke}</span>`;
  }
  return `<a class="problem-gespraech" href="${esc(anrufeUrl(g.sid))}" target="_blank" rel="noopener"` +
    ` title="Gespräch öffnen">${esc(g.tenant || "Anruf")} <code>${esc(uidKurz(g.sid))}</code>${marke}</a>`;
}

function gespraechGruppe(titel, liste, extraVon) {
  if (!liste || !liste.length) return "";
  return `<div class="klein">${esc(titel)}</div><div class="problem-gespraeche">` +
    liste.map((g) => gespraechLink(g, extraVon ? extraVon(g) : "")).join("") +
    `</div>`;
}

const MISSERFOLG = [
  ["bianca_fehler", "Bianca-Fehler", "Bianca"],
  ["kein_termin", "Kein passender Termin", "kein Termin"],
  ["aufgelegt", "Anrufer aufgelegt", "aufgelegt"],
];

function misserfolgKurz(z) {
  const gr = z.gruende || {};
  if (z.id === "reservierungs_sms") {
    return Object.entries(gr).filter(([, n]) => n)
      .map(([g, n]) => `${n} ${g}`).join(" · ");
  }
  return MISSERFOLG.filter(([k]) => gr[k])
    .map(([k, , kurz]) => `${gr[k]} ${kurz}`).join(" · ");
}

function liveAnliegen(zeilen, zielId) {
  const el = $(zielId || "live-anliegen");
  if (!el) return;
  let gruppe = "";
  el.innerHTML = (zeilen || []).map((z) => {
    let kopf = "";
    if (z.gruppe && z.gruppe !== gruppe) {
      gruppe = z.gruppe;
      kopf = `<tr><td colspan="5"><strong>${esc(gruppe)}</strong></td></tr>`;
    }
    const alle = z.gespraeche || [];
    const erledigt = alle.filter((g) => g.stand === "erledigt");
    const offen = alle.filter((g) => g.stand === "offen");
    const reservierung = z.id === "reservierungs_sms";
    let innen = gespraechGruppe("Erfolgreich", erledigt, reservierung ? (g) => g.grund || "" : null);
    if (reservierung) {
      innen += gespraechGruppe("Nicht erfolgreich", offen, (g) => g.grund || "");
    } else {
      MISSERFOLG.forEach(([k, titel]) => {
        innen += gespraechGruppe(`Nicht erfolgreich — ${titel}`, offen.filter((g) => g.grund === k));
      });
    }
    const name = innen
      ? `<details class="problem-akkordeon"><summary>${esc(z.titel)}</summary>${innen}</details>`
      : esc(z.titel);
    const quote = z.quote == null ? "—" : `${z.quote} %`;
    const quoteKlasse = z.quote == null ? "" : (Number(z.quote) >= 70 ? "ok" : "bad");
    const kurz = misserfolgKurz(z);
    const extra = reservierung && z.nameEingetragen
      ? `<div class="klein">Name im Anruf eingetragen: ${esc(z.nameEingetragen)}</div>` : "";
    return `${kopf}<tr>
      <td>${name}${extra}</td>
      <td><span class="ok">${esc(z.erkannt)}</span></td>
      <td><span class="ok">${esc(z.erledigt)}</span></td>
      <td>${z.offen ? `<span class="bad">${esc(z.offen)}</span>` : `<span class="ok">0</span>`}${kurz ? `<div class="klein">${esc(kurz)}</div>` : ""}</td>
      <td><span class="${quoteKlasse}">${esc(quote)}</span></td>
    </tr>`;
  }).join("") || '<tr><td colspan="5" class="klein">Keine erkannten Anliegen.</td></tr>';
}

function strategienZeichnen(liste) {
  const el = $("live-strategie");
  if (!el) return;
  const quelleText = {
    portal: "Portal",
    ablage: "Anliegen-Seite",
    standard: "noch nicht veröffentlicht",
  };
  el.innerHTML = (liste || []).map((p) => {
    const monate = p.suchFensterMonate
      ? `${p.suchFensterMonate} Monate`
      : `${p.suchFensterTage || "—"} Tage`;
    const zeilen = (p.anliegen || []).map((a) =>
      `<div class="klein"><strong>${esc(a.titel)}:</strong> ${esc(a.text)}</div>`).join("");
    return `<div class="stat-chart" style="margin-top:10px">
      <strong>${esc(p.titel)}</strong>
      <div class="klein">Voraus buchbar: ${esc(monate)} · Quelle: ${esc(quelleText[p.quelle] || p.quelle)}</div>
      ${zeilen}
    </div>`;
  }).join("") || '<p class="klein">Keine Praxis geladen.</p>';
}

function liveCfs(zeilen, zielId) {
  const el = $(zielId || "live-cfs");
  if (!el) return;
  el.innerHTML = (zeilen || []).map((z) => {
    const gruende = (z.gruende || []).map((g) =>
      `<div>${esc(g.grund)} <span class="klein">×${esc(g.anzahl)}</span></div>`).join("");
    const innen = gespraechGruppe("Geklappt", z.oks || []) +
      gespraechGruppe("Kein Termin", z.hinweise || [], (g) => g.grund || "") +
      gespraechGruppe("Fail", z.fails || [], (g) => g.grund || "");
    const zelle = innen
      ? `<details class="problem-akkordeon"><summary>Gespräche</summary>
          ${gruende ? `<div class="fail-gruende">${gruende}</div>` : ""}
          ${innen}</details>`
      : "—";
    const quoteKlasse = Number(z.quote) >= 100 ? "ok" : (Number(z.fail) > 0 ? "bad" : "");
    return `<tr>
      <td><code>${esc(z.cf)}</code></td>
      <td><span class="ok">${esc(z.laeufe)}</span></td>
      <td><span class="ok">${esc(z.ok)}</span></td>
      <td>${z.leer ? esc(z.leer) : `<span class="ok">0</span>`}</td>
      <td>${z.fail ? `<span class="bad">${esc(z.fail)}</span>` : `<span class="ok">0</span>`}</td>
      <td><span class="${quoteKlasse}">${esc(z.quote)} %</span></td>
      <td>${esc(z.msMittel)}</td>
      <td>${zelle}</td>
    </tr>`;
  }).join("") || '<tr><td colspan="8" class="klein">Keine Cloud-Function-Läufe in den Mitschnitten.</td></tr>';
}

function chartFehler(tage) {
  const canvas = $("chart-fehler");
  if (!canvas) return;
  const reihe = (tage && tage.reihe) || [];
  const { ctx, breite, hoehe } = chartKontext("chart-fehler");
  const box = grundraster(ctx, breite, hoehe, 100, "%");
  const praxen = [];
  const gesehen = new Set();
  reihe.forEach((tag) => {
    (tag.praxen || []).forEach((p) => {
      if (gesehen.has(p.id)) return;
      gesehen.add(p.id);
      praxen.push(p);
    });
  });
  const legende = $("fehler-legende");
  if (legende) {
    legende.innerHTML = praxen.map((p) =>
      `<span><i style="background:${praxisFarbe(p.id)}"></i>${esc(p.name)}</span>`
    ).join("");
  }
  if (reihe.length < 2) {
    ctx.fillStyle = "#8b96a5";
    ctx.textAlign = "center";
    ctx.fillText("Noch keine zwei Tage", breite / 2, hoehe / 2);
    return;
  }
  const xVon = (i) => box.l + box.w * (i / (reihe.length - 1));
  const punkt = (tag, id) => {
    const eintrag = (tag.praxen || []).find((x) => x.id === id);
    if (!eintrag || !Number(eintrag.erkannt || 0) || eintrag.quote == null) return null;
    return Math.max(0, Math.min(100, Number(eintrag.quote)));
  };
  praxen.forEach((p) => {
    const farbe = praxisFarbe(p.id);
    ctx.strokeStyle = farbe;
    ctx.fillStyle = farbe;
    ctx.lineWidth = 2;
    let stift = false;
    ctx.beginPath();
    reihe.forEach((tag, i) => {
      const quote = punkt(tag, p.id);
      if (quote == null) {
        if (stift) ctx.stroke();
        ctx.beginPath();
        stift = false;
        return;
      }
      const x = xVon(i);
      const y = box.t + box.h * (1 - quote / 100);
      if (stift) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
      stift = true;
    });
    if (stift) ctx.stroke();
    reihe.forEach((tag, i) => {
      const quote = punkt(tag, p.id);
      if (quote == null) return;
      const x = xVon(i);
      const y = box.t + box.h * (1 - quote / 100);
      ctx.beginPath();
      ctx.arc(x, y, tag.offen ? 5 : 3.5, 0, Math.PI * 2);
      if (tag.offen) {
        ctx.strokeStyle = farbe;
        ctx.lineWidth = 2;
        ctx.stroke();
      } else {
        ctx.fillStyle = farbe;
        ctx.fill();
      }
    });
  });
  xBeschriften(ctx, reihe.map((tag) => ({ datum: tag.tag })), box);
}

function summeZeichnen(d) {
  const summe = d.summe || {};
  kpisZeichnen("gesamt-kpis", summe.gesamt || {});
  liveAnliegen(summe.anliegen || [], "gesamt-anliegen");
  liveCfs(summe.cfs || [], "gesamt-cfs");
  const hinweis = $("gesamt-hinweis");
  if (!hinweis) return;
  const g = summe.gesamt || {};
  const quote = g.anliegenQuote == null ? "—" : `${Number(g.anliegenQuote).toFixed(1)} %`;
  hinweis.textContent =
    `Summe über die gezeichneten Tage: ${g.gespraeche || 0} Gespräche, ` +
    `Anliegen-Quote ${quote}. ` +
    "Um 20:00 Uhr kommt der Tag als Punkt dazu. Diese Summe wird dabei nicht auf null gesetzt.";
}

function liveZeichnen(d) {
  letzteLive = d;
  const gesamtSichtbar = $("sicht-gesamt") && !$("sicht-gesamt").hidden;
  if (gesamtSichtbar) chartFehler(d.tage || {});
  liveKpis(d);
  liveAnliegen(d.anliegen || []);
  strategienZeichnen(d.strategien || []);
  liveCfs(d.cfs || []);
  summeZeichnen(d);
  chartLast(d.auslastung || {});
  chartDrift(d.auslastung || {});
  chartBahnen(d.auslastung || {});
}

async function liveLaden() {
  const r = await fetch("api/ergebnisse" + tenantQ(), { cache: "no-store" });
  if (!r.ok) throw new Error("Ergebnisse " + r.status);
  liveZeichnen(await r.json());
}

/** Anrufuebersicht-Adresse eine Ebene ueber dem Studio: /studio/ -> /anrufe
    (hinter Lisas Durchreiche /bianca/studio/ -> /bianca/anrufe). Die Anruf-UID
    steht im Fragment — die Uebersicht waehlt das Gespraech damit vor. */
function anrufeUrl(sid) {
  const eltern = studioWurzel().replace(/[^/]+\/$/, "") || "/";
  const ziel = new URL("anrufe", location.origin + eltern);
  if (sid) ziel.hash = String(sid);
  return ziel.href;
}

/** Anruf-UID kurz: die ersten acht Hex-Stellen reichen zum Wiedererkennen. */
function uidKurz(sid) {
  const h = String(sid || "").replace(/-/g, "");
  return h ? h.slice(0, 8) : "";
}

/** Ein Problem mit den betroffenen Gespraechen darunter (Akkordeon).
    Jedes Gespraech fuehrt in die Anrufuebersicht; fehlt die UID (alte
    Berichte, Belastungslauf), bleibt der Eintrag als Text stehen statt
    einen toten Link anzubieten. */
function problemZelle(p) {
  const liste = (p.gespraeche || []).map((g) => {
    const marke = `${esc(g.art || "")} · ${esc(datumKurz(g.zeit))}`;
    const name = esc(g.storyId || g.laufId || "Gespräch");
    if (!g.sid) return `<span class="problem-gespraech tot">${name} <span class="klein">${marke}</span></span>`;
    return `<a class="problem-gespraech" href="${esc(anrufeUrl(g.sid))}" target="_blank" rel="noopener"` +
      ` title="in der Anrufübersicht öffnen">${name} <code>${esc(uidKurz(g.sid))}</code>` +
      ` <span class="klein">${marke}</span></a>`;
  }).join("");
  if (!liste) return esc(p.problem);
  return `<details class="problem-akkordeon"><summary>${esc(p.problem)}</summary>` +
    `<div class="problem-gespraeche">${liste}</div></details>`;
}

function statistikZeichnen(d) {
  letzteStatistik = d;
  const g = d.gesamt || {};
  const kpis = [
    ["Gespräche", g.gespraeche || 0, ""],
    ["Gesprächszüge", g.turns || 0, ""],
    ["Erfolgreich", g.erfolgreich || 0, "ok"],
    ["Fehlgeschlagen", g.fehlgeschlagen || 0, (g.fehlgeschlagen || 0) ? "bad" : "ok"],
    ["Erfolgsquote", `${Number(g.erfolgsquote || 0).toFixed(1)} %`, Number(g.erfolgsquote || 0) >= 80 ? "ok" : "bad"],
    ["Antwortzeit Ø", `${Number(g.latenzS || 0).toFixed(2)} s`, Number(g.latenzS || 0) <= 4 ? "ok" : "bad"],
  ];
  $("stat-kpis").innerHTML = kpis.map(([name, wert, klasse]) =>
    `<div class="stat-kpi"><span class="klein">${esc(name)}</span><span class="wert ${klasse}">${esc(wert)}</span></div>`
  ).join("");
  const trend = d.trend || {};
  $("stat-trend").className = "trend " + esc(trend.richtung || "neutral");
  $("stat-trend").textContent = trend.text || "";
  $("stat-warnungen").innerHTML = (d.warnungen || []).map((w) =>
    `<div class="warnung ${esc(w.stufe)}">${esc(w.text)}</div>`
  ).join("");
  $("stat-probleme").innerHTML = (d.probleme || []).map((p) =>
    `<tr><td>${problemZelle(p)}</td><td>${esc(p.anzahl)}</td><td>${esc(datumKurz(p.zuletzt))}</td><td>${esc(p.empfehlung)}</td></tr>`
  ).join("") || '<tr><td colspan="4" class="klein">Keine wiederkehrenden Probleme.</td></tr>';
  $("stat-analysen").innerHTML = (d.analysen || []).map((a) => `
    <div class="analyse" data-lauf="${esc(a.laufId)}" data-story="${esc(a.storyId)}" data-art="${esc(a.art)}">
      <div class="analyse-kopf"><strong>${esc(a.storyId)}</strong><span class="klein">${esc(a.art)} · ${esc(datumKurz(a.zeit))} · ${esc(a.turns)} Züge</span></div>
      <div class="analyse-problem">${esc((a.probleme || []).join(" · "))}</div>
      <div class="analyse-empfehlung">${esc(a.empfehlung)}</div>
      ${a.sid ? `<a class="problem-gespraech" href="${esc(anrufeUrl(a.sid))}" target="_blank" rel="noopener"
        title="in der Anrufübersicht öffnen">Anrufübersicht <code>${esc(uidKurz(a.sid))}</code></a>` : ""}
    </div>`).join("") || '<span class="klein">Keine Gespräche mit Verbesserungsbedarf.</span>';
  document.querySelectorAll(".analyse[data-art='Studio']").forEach((el) => {
    el.style.cursor = "pointer";
    el.addEventListener("click", (ev) => {
      // Der Link in die Anrufuebersicht gewinnt — sonst oeffnete der Klick
      // zusaetzlich den Dialog auf dieser Seite.
      if (ev.target.closest("a")) return;
      laufOeffnen(el.dataset.lauf).then(() => storyOeffnen(el.dataset.lauf, el.dataset.story));
    });
  });
  chartErfolg(d.zeitreihe || []);
  chartVolumen(d.zeitreihe || []);
}

async function statistikLaden() {
  const r = await fetch("api/statistik" + tenantQ(), { cache: "no-store" });
  if (!r.ok) throw new Error("Statistik " + r.status);
  statistikZeichnen(await r.json());
}

async function datenLaden() {
  $("status").textContent = "lädt …";
  try {
    await Promise.all([laeufeLaden(), statistikLaden(), liveLaden()]);
    $("status").textContent = "";
  } catch (e) {
    $("status").textContent = String(e && e.message ? e.message : e);
  }
}

async function laeufeLaden() {
  const d = await (await fetch("api/laeufe" + tenantQ())).json();
  const box = $("laeufe");
  box.innerHTML = "";
  (d.laeufe || []).forEach((l) => {
    const div = document.createElement("div");
    div.className = "laufkarte";
    div.innerHTML = `<strong>${l.laufId}</strong>
      <span class="klein lauf-zeit">${l.gestartet || ""}</span>
      <span class="lauf-score">
        <span class="gruen">${l.gruen}</span> / <span class="${l.gruen === l.gesamt ? "gruen" : "rot"}">${l.gesamt}</span>
      </span>`;
    div.addEventListener("click", () => laufOeffnen(l.laufId));
    box.appendChild(div);
  });
  if (!(d.laeufe || []).length) box.innerHTML = '<span class="klein">noch keine Läufe</span>';
}

async function laufOeffnen(laufId) {
  aktuellerLauf = laufId;
  location.hash = laufId;
  const d = await (await fetch(`api/lauf/${laufId}`)).json();
  $("lauf-id").textContent = laufId;
  const box = $("stories");
  box.innerHTML = "";
  (d.stories || []).forEach((s) => {
    const div = document.createElement("div");
    div.className = "laufkarte storykarte" + (s.ok ? "" : " rot");
    const checks = (s.checks || []).map((c) =>
      `<span class="check ${c.ok ? "ok" : "rot"}"><span class="punkt"></span>${c.name}</span>`).join("");
    div.innerHTML = `<div><strong>${s.id}</strong><div>${checks}</div>
      ${s.fehler ? `<div class="klein" style="color:var(--rot)">${s.fehler}</div>` : ""}</div>
      <span class="klein lauf-score">max ${s.latenzMaxS || "?"}s</span>`;
    div.addEventListener("click", () => storyOeffnen(laufId, s.id));
    box.appendChild(div);
  });
  $("block-stories").style.display = "";
  $("block-dialog").style.display = "none";
}

function bubbleBauen(z, basis) {
  const div = document.createElement("div");
  if (z.warte) {
    div.className = "bubble warte";
    div.textContent = "… Bianca wartet (Halbsatz-Wache) …";
    return div;
  }
  div.className = "bubble " + (z.wer === "bianca" ? "bianca" : "anrufer");
  div.textContent = z.text || "";
  const meta = document.createElement("div");
  meta.className = "meta";
  if (z.wer === "bianca" && z.latenzS) {
    meta.insertAdjacentHTML("beforeend",
      `<span class="tag lat">Antwort ${z.latenzS}s${z.ersterTonS && z.ersterTonS !== z.latenzS ? ` · erster Ton ${z.ersterTonS}s` : ""}</span>`);
  }
  if (z.wer === "bianca" && z.timings && z.timings.stt) {
    meta.insertAdjacentHTML("beforeend", `<span class="tag">stt ${z.timings.stt}s</span>`);
  }
  (z.waechter || []).forEach((w) => {
    meta.insertAdjacentHTML("beforeend",
      `<span class="tag waechter" title="${(w.d || "").replace(/"/g, "&quot;")}">${w.w}</span>`);
  });
  if (z.frage) meta.insertAdjacentHTML("beforeend", `<span class="tag">frage=${z.frage}</span>`);
  if (z.baustein) meta.insertAdjacentHTML("beforeend", `<span class="tag">${z.baustein}</span>`);
  if (z.audioPipeline) {
    const audioTag = document.createElement("span");
    audioTag.className = "tag audio-pipeline";
    audioTag.textContent = "🎙 WAV → Bianca-STT";
    meta.appendChild(audioTag);
  }
  if (z.stt && z.stt.winner) {
    const win = String(z.stt.winner);
    const sttTag = document.createElement("span");
    sttTag.className = "tag stt-gewinner " + (win === "qwen" ? "qwen" : "parakeet");
    sttTag.textContent = `STT-Gewinner: ${win === "qwen" ? "Qwen" : win === "parakeet" ? "Parakeet" : win}`;
    const p = (z.stt.parakeet && z.stt.parakeet.text) || "";
    const q = (z.stt.qwen && z.stt.qwen.text) || "";
    sttTag.title = `Parakeet: ${p || "—"}\nQwen: ${q || (z.stt.qwen && z.stt.qwen.status) || "—"}`;
    meta.appendChild(sttTag);
    if (z.stt.qwen && z.stt.qwen.status) {
      const qwenTag = document.createElement("span");
      qwenTag.className = "tag stt-status";
      qwenTag.textContent = `Qwen: ${String(z.stt.qwen.status).replaceAll("_", " ")}`;
      // W-QWEN-SICHER: Namensfrage/Diktat/erwartete Antwort — Qwen durfte
      // diesen Zug nicht live uebernehmen (gleiche Anzeige wie in /anrufe).
      const qTipp = [];
      if (q) qTipp.push(q);
      if (z.stt.qwen.sperre) qTipp.push(`live gesperrt: ${z.stt.qwen.sperre}`);
      if (qTipp.length) qwenTag.title = qTipp.join("\n");
      meta.appendChild(qwenTag);
    }
    // W-QWEN-KORREKTOR: das Zweit-Ohr hat diesen Zug vor dem Hirn berichtigt.
    const k = z.stt.korrektur;
    if (k && typeof k === "object") {
      const kTag = document.createElement("span");
      kTag.className = "tag stt-gewinner qwen";
      kTag.textContent = k.vorzug ? `Qwen-Korrektur (${k.grund || "vorzug"})` : "Qwen-Wörterbuch";
      const teile = [];
      if (k.textVorher && k.text) teile.push(`${k.textVorher} → ${k.text}`);
      if (k.woerterbuch && k.woerterbuch.length) teile.push(k.woerterbuch.join(", "));
      if (k.vorzug && k.qwenVorher) teile.push(`voriger Zug richtig: ${k.qwenVorher} (gehört: ${k.parakeetVorher || ""})`);
      kTag.title = teile.join("\n");
      meta.appendChild(kTag);
    }
  }
  if (z.gesprochen && z.gesprochen !== z.text) {
    meta.insertAdjacentHTML("beforeend", `<span class="tag gesprochen">gesprochen: ${z.gesprochen}</span>`);
  }
  if (z.gehoert && z.gehoert !== z.text) {
    meta.insertAdjacentHTML("beforeend", `<span class="tag gehoert">gehört: ${z.gehoert}</span>`);
  }
  if (z.book && z.book.booked) {
    meta.insertAdjacentHTML("beforeend",
      `<span class="tag" style="color:var(--gruen)">GEBUCHT ${String(z.book.slotIso || "").slice(0, 16)}</span>`);
  }
  if (z.audio) {
    const url = `${basis}/${String(z.audio).split("/").pop()}`;
    const knopf = document.createElement("button");
    knopf.textContent = "▶";
    knopf.addEventListener("click", () => {
      stoppen();
      spielen(url);
    });
    meta.appendChild(knopf);
    div.dataset.audio = url;
  }
  if (meta.children.length) div.appendChild(meta);
  return div;
}

function stoppen() {
  try { lautsprecher.pause(); } catch { /* */ }
  spielListe = [];
}

function allesAbspielen() {
  stoppen();
  spielListe = [...$("dialog").children]
    .map((b) => b.dataset.audio).filter(Boolean);
  const weiter = () => {
    const url = spielListe.shift();
    if (!url) return;
    spielen(url).then(weiter);
  };
  weiter();
}

async function storyOeffnen(laufId, storyId) {
  const b = await (await fetch(`api/bericht/${laufId}/${storyId}`)).json();
  $("story-id").textContent = storyId;
  const basis = `api/ton/${laufId}/${storyId}`;
  const erg = b.ergebnis || {};
  $("story-checks").innerHTML = (erg.checks || []).map((c) =>
    `<span class="check ${c.ok ? "ok" : "rot"}"><span class="punkt"></span>${c.name}` +
    `${!c.ok && (c.soll || c.ist) ? ` <span class="klein">(soll ${c.soll || "?"}, ist ${c.ist || "—"})</span>` : ""}</span>`).join("") +
    `<div class="klein" style="margin-top:4px">Latenz max ${erg.latenzMaxS || "?"}s · mittel ${erg.latenzMittelS || "?"}s · Wächter: ${(erg.waechter || []).join(", ") || "keine"}</div>` +
    (b.fehler ? `<div class="fehlerbox">${b.fehler}</div>` : "");
  const dialog = $("dialog");
  dialog.innerHTML = "";
  (b.zuege || []).forEach((z) => dialog.appendChild(bubbleBauen(z, basis)));
  $("block-dialog").style.display = "";
  $("block-dialog").scrollIntoView({ behavior: "smooth" });
}

function sichtWechseln(welche) {
  ["heute", "gesamt", "archiv"].forEach((name) => {
    const sicht = $("sicht-" + name);
    const tab = $("tab-" + name);
    if (sicht) sicht.hidden = name !== welche;
    if (tab) tab.classList.toggle("an", name === welche);
  });
  if (!letzteLive) return;
  if (welche === "gesamt") chartFehler(letzteLive.tage || {});
  if (welche === "archiv") {
    chartLast(letzteLive.auslastung || {});
    chartDrift(letzteLive.auslastung || {});
    chartBahnen(letzteLive.auslastung || {});
    if (letzteStatistik) {
      chartErfolg(letzteStatistik.zeitreihe || []);
      chartVolumen(letzteStatistik.zeitreihe || []);
    }
  }
}

const tabHeute = $("tab-heute");
const tabGesamt = $("tab-gesamt");
const tabArchiv = $("tab-archiv");
if (tabHeute) tabHeute.addEventListener("click", () => sichtWechseln("heute"));
if (tabGesamt) tabGesamt.addEventListener("click", () => sichtWechseln("gesamt"));
if (tabArchiv) tabArchiv.addEventListener("click", () => sichtWechseln("archiv"));

$("knopf-alles").addEventListener("click", allesAbspielen);
$("knopf-stopp").addEventListener("click", stoppen);
window.addEventListener("message", (ev) => {
  if (ev.origin !== location.origin) return;
  const d = ev.data || {};
  if (d.type === "pickadoc:tenant" && d.tenant) tenantSetzen(d.tenant);
});
window.addEventListener("storage", (ev) => {
  if (ev.key === "pickadoc.praxis" && ev.newValue) tenantSetzen(ev.newValue);
});

window.addEventListener("resize", () => {
  if (letzteStatistik) {
    chartErfolg(letzteStatistik.zeitreihe || []);
    chartVolumen(letzteStatistik.zeitreihe || []);
  }
  if (letzteLive) {
    if ($("sicht-gesamt") && !$("sicht-gesamt").hidden) chartFehler(letzteLive.tage || {});
    chartLast(letzteLive.auslastung || {});
    chartDrift(letzteLive.auslastung || {});
    chartBahnen(letzteLive.auslastung || {});
  }
});

datenLaden().then(() => {
  const h = location.hash.replace("#", "");
  if (h) laufOeffnen(h);
});
