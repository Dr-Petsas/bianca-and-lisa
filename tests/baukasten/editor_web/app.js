/* Editor des Baukasten-Teststudios: Chips -> Story -> Lauf am Bianca-Dienst.
   Mithoeren pollt NUR diesen Server (8097) — die Bianca-Latenz bleibt unberuehrt. */
"use strict";

let KATALOG = null;
const wahl = {
  stimme: "", nachname: "", anliegen: "termin", grund: "", behandler: null,
  versicherung: "", tag: "Mittwoch", slotAnnahme: 0, slotRichtung: "",
  abschweifer: new Set(), extras: new Set(), einzelwoerter: new Set(),
};
let storyNr = 1;
let poller = null;
const gespielt = new Set();  // Audio-URLs, die das Mithoeren schon abgespielt hat
let spielKette = Promise.resolve();
const lautsprecher = new Audio();
lautsprecher.preload = "auto";
lautsprecher.playsInline = true;
let ohrOffen = false;

const $ = (id) => document.getElementById(id);

// 44-Byte-Stille: entsperrt HTMLAudio im Klick-Zug — AudioContext allein
// reicht nicht, spaeteres play() aus dem Poller waere sonst Autoplay-blockiert.
const STILLE_WAV = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=";

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

function ohrOeffnen() {
  if (ohrOffen) return Promise.resolve();
  lautsprecher.src = STILLE_WAV;
  return lautsprecher.play().then(() => {
    lautsprecher.pause();
    ohrOffen = true;
  }).catch(() => { /* Autoplay weiter dicht — naechster Klick versucht erneut */ });
}

function tonHinweis(text) {
  const el = $("ton-hinweis");
  if (el) el.textContent = text || "";
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
      } catch { /* Datei evtl. noch nicht geschrieben */ }
      await new Promise((w) => setTimeout(w, 180));
    }
    if (!blob || blob.size < 44) {
      tonHinweis("Audio fehlt — Play nochmal tippen.");
      return;
    }
    const obj = URL.createObjectURL(blob);
    try {
      try { lautsprecher.pause(); } catch { /* */ }
      lautsprecher.src = obj;
      await lautsprecher.play();
      tonHinweis("");
      await new Promise((fertig) => {
        const ende = () => {
          lautsprecher.removeEventListener("ended", ende);
          lautsprecher.removeEventListener("error", ende);
          fertig();
        };
        lautsprecher.addEventListener("ended", ende);
        lautsprecher.addEventListener("error", ende);
      });
    } catch (e) {
      ohrOffen = false;
      tonHinweis("Mithören startet nach einem Klick ins Fenster.");
      console.warn("studio-ton", url, e);
    } finally {
      try { URL.revokeObjectURL(obj); } catch { /* */ }
    }
  })();
}

function mithoerenAn() {
  const a = $("mithoeren-popup");
  const b = $("mithoeren");
  if (a && a.checked) return true;
  if (b && b.checked) return true;
  return false;
}

function mithoerenSetzen(an) {
  if ($("mithoeren")) $("mithoeren").checked = an;
  if ($("mithoeren-popup")) $("mithoeren-popup").checked = an;
}

function popupAuf() {
  $("anruf-popup").hidden = false;
  mithoerenSetzen(true);
}

function popupZu() {
  $("anruf-popup").hidden = true;
}

function chip(text, an, klick, wert) {
  const el = document.createElement("button");
  el.className = "chip" + (an ? " an" : "");
  el.textContent = text;
  el.dataset.wert = wert === undefined ? text : wert;
  el.addEventListener("click", () => klick(el));
  return el;
}

function einzelwahl(containerId, werte, feld, anzeigen) {
  const box = $(containerId);
  if (!box) return;
  box.innerHTML = "";
  werte.forEach((w, i) => {
    const wert = typeof w === "object" ? w.wert : w;
    const text = anzeigen ? anzeigen(w, i) : String(w);
    box.appendChild(chip(text, wahl[feld] === wert, (el) => {
      wahl[feld] = el.classList.contains("an") ? "" : wert;
      [...box.children].forEach((c) => c.classList.toggle("an", c === el && wahl[feld] !== ""));
    }, wert));
  });
}

function mehrfachwahl(containerId, werte, menge, anzeigen) {
  const box = $(containerId);
  if (!box) return;
  box.innerHTML = "";
  werte.forEach((w) => {
    const wert = typeof w === "object" ? (w.wert || w.id) : w;
    const text = anzeigen ? anzeigen(w) : (typeof w === "object" ? (w.text || wert) : String(w));
    box.appendChild(chip(text, menge.has(wert), (el) => {
      if (menge.has(wert)) { menge.delete(wert); el.classList.remove("an"); }
      else { menge.add(wert); el.classList.add("an"); }
    }, wert));
  });
}

const PRAXIS_KEY = "pickadoc.praxis";
let TENANTS = [];

function praxisKurz(t) {
  const id = String((t && t.id) || "");
  if (id === "meddent") return "Medical Center";
  if (id === "thaler") return "Thaler";
  if (id === "blessing") return "Blessing";
  return String((t && t.praxisName) || id);
}

function praxisId() {
  try {
    const stored = localStorage.getItem(PRAXIS_KEY) || "";
    if (stored) return stored;
    const q = new URLSearchParams(location.search).get("tenant");
    if (q) return q;
  } catch { /* */ }
  const sel = $("tenant");
  return (sel && sel.value) || "";
}

function praxisSetzen(id) {
  const wert = String(id || "").trim();
  try { localStorage.setItem(PRAXIS_KEY, wert); } catch { /* */ }
  const sel = $("tenant");
  if (sel) sel.value = wert;
  const box = $("chips-praxis");
  if (!box) return;
  [...box.children].forEach((c) => c.classList.toggle("an", c.dataset.wert === wert));
}

function praxisChipsZeichnen() {
  const box = $("chips-praxis");
  if (!box) return;
  box.innerHTML = "";
  const aktuell = praxisId();
  TENANTS.forEach((t) => {
    box.appendChild(chip(praxisKurz(t), t.id === aktuell, () => {
      praxisSetzen(t.id);
      katalogLaden(t.id);
    }, t.id));
  });
}

function chipsBauen() {
  einzelwahl("chips-stimme", KATALOG.stimmen, "stimme",
    (s) => `${KATALOG.vornamen[s] || s} (${s})`);
  einzelwahl("chips-nachname", KATALOG.nachnamen, "nachname");
  einzelwahl("chips-anliegen", KATALOG.anliegen, "anliegen");
  einzelwahl("chips-grund", Object.keys(KATALOG.gruende), "grund",
    (g) => KATALOG.gruende[g] === g ? g : `${g} → ${KATALOG.gruende[g]}`);
  einzelwahl("chips-behandler", [...KATALOG.behandler, "egal"], "behandler");
  einzelwahl("chips-versicherung", ["privat", "gesetzlich"], "versicherung");
  einzelwahl("chips-tag", KATALOG.tage.map((t) => ({ wert: t.tag, anzeige: t.anzeige })),
    "tag", (t) => t.anzeige);
  wahl.tag = "Mittwoch";
  [...$("chips-tag").children].forEach((c) => c.classList.toggle("an", c.dataset.wert === "Mittwoch"));
  einzelwahl("chips-slot",
    [{ wert: "1" }, { wert: "2" }, { wert: "3" }, { wert: "frueher" }, { wert: "spaeter" }],
    "slotwahl_dummy",
    (o) => ({ 1: "nimmt 1. Angebot", 2: "nimmt 2. Angebot", 3: "nimmt 3. Angebot",
              frueher: "will früher", spaeter: "will später" }[o.wert]));
  // Slot-Chips: 1/2/3 setzt slotAnnahme, frueher/spaeter setzt die Richtung.
  [...$("chips-slot").children].forEach((c) => {
    c.addEventListener("click", () => {
      const w = c.dataset.wert;
      if (["1", "2", "3"].includes(w)) {
        wahl.slotAnnahme = wahl.slotAnnahme === Number(w) ? 0 : Number(w);
      } else {
        wahl.slotRichtung = wahl.slotRichtung === w ? "" : w;
      }
      [...$("chips-slot").children].forEach((x) => {
        const xw = x.dataset.wert;
        x.classList.toggle("an",
          (["1", "2", "3"].includes(xw) && Number(xw) === wahl.slotAnnahme) ||
          (["frueher", "spaeter"].includes(xw) && xw === wahl.slotRichtung));
      });
    }, { capture: true });
  });
  mehrfachwahl("chips-abschweifer", KATALOG.abschweifer, wahl.abschweifer);
  mehrfachwahl("chips-extras", [
    { wert: "halbsatz", text: "Halbsatz" },
    { wert: "zwischenfragePreis", text: "Zwischenfrage Preis" },
    { wert: "readbackFehler", text: "Readback-Fehler" },
    { wert: "pzr", text: "PZR mitbuchen" },
  ], wahl.extras);
  mehrfachwahl("chips-einzelwort", KATALOG.einzelwoerter || [], wahl.einzelwoerter);
}

function eigen(id) {
  const el = $(id);
  return el ? String(el.value || "").trim() : "";
}

function storyBauen() {
  const s = { nr: storyNr };
  if (wahl.stimme) s.stimme = wahl.stimme;
  if (wahl.stimme) s.vorname = KATALOG.vornamen[wahl.stimme];
  if (wahl.nachname) s.nachname = wahl.nachname;
  const vorFrei = eigen("eigen-vorname");
  const nachFrei = eigen("eigen-nachname");
  if (vorFrei) s.vorname = vorFrei;
  if (nachFrei) s.nachname = nachFrei;
  if (wahl.anliegen) s.anliegen = wahl.anliegen;
  const eroeff = eigen("eigen-eroeffnung");
  if (eroeff) s.eroeffnungText = eroeff;
  if (wahl.grund) s.grund = wahl.grund;
  const grundFrei = eigen("eigen-grund");
  if (grundFrei) {
    s.grundText = grundFrei;
    if (!s.grund) s.grund = "frei";
  }
  if (wahl.behandler !== null && wahl.behandler !== "") {
    s.behandler = wahl.behandler === "egal" ? "" : wahl.behandler;
  }
  const arztFrei = eigen("eigen-behandler");
  if (arztFrei) s.behandler = arztFrei;
  if (wahl.versicherung) s.versicherung = wahl.versicherung;
  const versFrei = eigen("eigen-versicherung");
  if (versFrei) s.versicherungText = versFrei;
  const wunschFrei = eigen("eigen-wunsch");
  if (wunschFrei) s.wunschText = wunschFrei;
  if (wahl.slotAnnahme) s.slotAnnahme = wahl.slotAnnahme;
  if (wahl.slotRichtung) s.slotRichtung = wahl.slotRichtung;
  const slotFrei = eigen("eigen-slot");
  if (slotFrei) s.slotText = slotFrei;
  if (wahl.abschweifer.size) {
    const anker = KATALOG.anker;
    s.abschweifer = [...wahl.abschweifer].map((t, i) => [anker[i % anker.length], t]);
  } else {
    s.abschweifer = [];
  }
  const abFrei = eigen("eigen-abschweifer");
  if (abFrei) s.abschweiferText = abFrei;
  s.halbsatz = wahl.extras.has("halbsatz");
  s.zwischenfragePreis = wahl.extras.has("zwischenfragePreis");
  s.readbackFehler = wahl.extras.has("readbackFehler");
  s.pzr = wahl.extras.has("pzr");
  const woerter = [...wahl.einzelwoerter];
  const freiWort = eigen("eigen-einzelwort");
  if (freiWort) {
    freiWort.split(/[,;\n]+/).forEach((w) => {
      const t = w.trim();
      if (t && !woerter.includes(t)) woerter.push(t);
    });
  }
  const anzahl = Math.max(0, Math.min(8, Number(($("ew-n") && $("ew-n").value) || 0) || 0));
  if (!woerter.length && anzahl > 0) {
    const pool = KATALOG.einzelwoerter || [];
    for (let i = 0; i < pool.length && woerter.length < anzahl; i++) {
      const w = pool[i];
      if (w && !woerter.includes(w)) woerter.push(w);
    }
  }
  if (woerter.length) s.einzelwoerter = woerter;
  if (anzahl > 0) s.einzelwortAnzahl = anzahl;
  else if (woerter.length) s.einzelwortAnzahl = woerter.length;
  return s;
}

function leitungLesen() {
  const n = (id, fb) => {
    const el = $(id);
    const v = el ? Number(el.value) : fb;
    return Number.isFinite(v) ? v : fb;
  };
  return {
    hz: n("lt-hz", 8000),
    rauschen: n("lt-rauschen", 28),
    artefakte: n("lt-artefakte", 12),
    dropouts: n("lt-dropouts", 6),
    pegel: n("lt-pegel", 75),
    g711: !$("lt-g711") || $("lt-g711").checked,
  };
}

function einzelwortAnzahlZeichnen() {
  const sl = $("ew-n");
  if ($("ew-n-w") && sl) $("ew-n-w").textContent = sl.value;
}

function einzelwortAnzahlSetzen(n) {
  const sl = $("ew-n");
  if (!sl) return;
  sl.value = String(Math.max(0, Math.min(8, Number(n) || 0)));
  einzelwortAnzahlZeichnen();
}

function leitungZeichnen() {
  const hz = $("lt-hz");
  if ($("lt-hz-w") && hz) $("lt-hz-w").textContent = hz.value + " Hz";
  ["rauschen", "artefakte", "dropouts", "pegel"].forEach((k) => {
    const sl = $("lt-" + k);
    const out = $("lt-" + k + "-w");
    if (sl && out) out.textContent = sl.value + " %";
  });
}

const MON_TABS = ["alle", "meddent", "thaler", "blessing"];
let monTab = 0;
let monTransN = 0;
let monStand = null;

function lastN() {
  return Number(($("last-n") && $("last-n").value) || 6);
}

function lastSplitZeichnen(plan) {
  const box = $("last-split");
  if (!box) return;
  const kunden = (plan && plan.kunden) || [];
  box.innerHTML = kunden.map((k) => `
    <div class="last-kunde">
      <span class="name"><span class="punkt" style="background:${k.farbe}"></span>${k.kurz}</span>
      <span class="zahl">${k.n} Anrufe</span>
    </div>`).join("");
}

async function lastPlanAktualisieren() {
  const n = lastN();
  if ($("last-n-w")) $("last-n-w").textContent = String(n);
  try {
    const d = await (await fetch("api/lasttest/plan?n=" + n)).json();
    lastSplitZeichnen(d);
  } catch {
    lastSplitZeichnen({
      kunden: [
        { id: "meddent", kurz: "Medical Center", farbe: "#4da3ff", n: Math.ceil(n / 3) },
        { id: "thaler", kurz: "Thaler", farbe: "#37c978", n: Math.floor((n + 1) / 3) },
        { id: "blessing", kurz: "Blessing", farbe: "#d862c8", n: Math.floor(n / 3) },
      ],
    });
  }
}

function lastSetupAuf() {
  $("last-setup").hidden = false;
  lastPlanAktualisieren();
}

function lastSetupZu() {
  $("last-setup").hidden = true;
}

function monAuf() {
  $("mon-popup").hidden = false;
}

function monZu() {
  $("mon-popup").hidden = true;
}

function monFilter(items, key) {
  const tab = MON_TABS[monTab] || "alle";
  if (tab === "alle") return items || [];
  return (items || []).filter((x) => x[key || "tenant"] === tab);
}

function monKpiKlasse(pct) {
  if (pct > 80) return "bad";
  if (pct > 25) return "warn";
  return "ok";
}

function monTabsZeichnen(plan) {
  const box = $("mon-tabs");
  if (!box) return;
  const kunden = (plan && plan.kunden) || [];
  const teile = [{ id: "alle", kurz: "Alle", n: (plan && plan.n) || 0 }];
  kunden.forEach((k) => teile.push(k));
  box.innerHTML = teile.map((k, i) => {
    const aktiv = (MON_TABS[monTab] || "alle") === (k.id || "alle") ? " an" : "";
    return `<button class="mon-tab${aktiv}" type="button" data-tab="${k.id || "alle"}">${k.kurz}${k.n != null ? ` · ${k.n}` : ""}</button>`;
  }).join("");
  box.querySelectorAll(".mon-tab").forEach((b) => {
    b.addEventListener("click", () => {
      const id = b.getAttribute("data-tab");
      const idx = MON_TABS.indexOf(id);
      monTab = idx < 0 ? 0 : idx;
      monTransN = 0;
      if ($("mon-trans")) $("mon-trans").innerHTML = "";
      if (monStand) lasttestZeichnen(monStand);
    });
  });
}

function canvasFit(cv) {
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 320;
  const h = cv.clientHeight || 160;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
    cv.width = Math.round(w * dpr);
    cv.height = Math.round(h * dpr);
  }
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

function monLatenzZeichnen(punkte, norm) {
  const cv = $("mon-latenz");
  if (!cv) return;
  const { ctx, w, h } = canvasFit(cv);
  ctx.clearRect(0, 0, w, h);
  const pad = { l: 36, r: 10, t: 10, b: 22 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const series = monFilter(punkte).filter((p) => p.metrik !== "start");
  const maxT = Math.max(8, ...series.map((p) => Number(p.tS) || 0));
  const maxY = Math.max(3, ...(series.map((p) => Number(p.wert) || 0)), Number((norm && norm.antwortS) || 2));
  const xOf = (t) => pad.l + (t / maxT) * innerW;
  const yOf = (v) => pad.t + innerH - (v / maxY) * innerH;
  ctx.strokeStyle = "#2a3442";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad.l, pad.t);
  ctx.lineTo(pad.l, pad.t + innerH);
  ctx.lineTo(pad.l + innerW, pad.t + innerH);
  ctx.stroke();
  const nTon = Number((norm && norm.ersterTonS) || 0.8);
  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = "#37c978";
  ctx.beginPath();
  ctx.moveTo(pad.l, yOf(nTon));
  ctx.lineTo(pad.l + innerW, yOf(nTon));
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#8b96a5";
  ctx.font = "10px Segoe UI, sans-serif";
  ctx.fillText("Norm " + nTon.toFixed(1) + "s", pad.l + 4, yOf(nTon) - 4);
  const sort = series.slice().sort((a, b) => a.tS - b.tS);
  if (sort.length) {
    ctx.beginPath();
    sort.forEach((p, i) => {
      const x = xOf(Number(p.tS) || 0);
      const y = yOf(Number(p.wert) || 0);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "#4da3ff";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.lineTo(xOf(sort[sort.length - 1].tS), yOf(nTon));
    ctx.lineTo(xOf(sort[0].tS), yOf(nTon));
    ctx.closePath();
    ctx.fillStyle = "rgba(255, 95, 107, 0.16)";
    ctx.fill();
    sort.forEach((p) => {
      ctx.beginPath();
      ctx.arc(xOf(p.tS), yOf(p.wert), 3, 0, Math.PI * 2);
      ctx.fillStyle = p.offsetPct > 25 ? "#ff5f6b" : "#4da3ff";
      ctx.fill();
    });
  }
  ctx.fillStyle = "#8b96a5";
  ctx.fillText("Gesprächszeit (s)", pad.l, h - 6);
}

function monDropZeichnen(blasen) {
  const cv = $("mon-drop");
  if (!cv) return;
  const { ctx, w, h } = canvasFit(cv);
  ctx.clearRect(0, 0, w, h);
  const pad = { l: 36, r: 12, t: 12, b: 22 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const items = monFilter(blasen);
  const maxT = Math.max(8, ...items.map((b) => Number(b.tS) || 0));
  const maxD = Math.max(2, ...items.map((b) => Number(b.dauerS) || 0));
  const xOf = (t) => pad.l + (t / maxT) * innerW;
  const yOf = (v) => pad.t + innerH - (v / maxD) * innerH;
  ctx.strokeStyle = "#2a3442";
  ctx.beginPath();
  ctx.moveTo(pad.l, pad.t);
  ctx.lineTo(pad.l, pad.t + innerH);
  ctx.lineTo(pad.l + innerW, pad.t + innerH);
  ctx.stroke();
  items.forEach((b) => {
    const r = 6 + Math.min(28, Number(b.dauerS) * 7);
    ctx.beginPath();
    ctx.arc(xOf(b.tS), yOf(b.dauerS), r, 0, Math.PI * 2);
    ctx.fillStyle = (b.farbe || "#ff5f6b") + "99";
    ctx.fill();
    ctx.strokeStyle = b.farbe || "#ff5f6b";
    ctx.stroke();
  });
  ctx.fillStyle = "#8b96a5";
  ctx.font = "10px Segoe UI, sans-serif";
  ctx.fillText("Gesprächszeit (s)", pad.l, h - 6);
  ctx.save();
  ctx.translate(12, pad.t + innerH);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("Dropout (s)", 0, 0);
  ctx.restore();
}

function monTransZeichnen(zeilen) {
  const box = $("mon-trans");
  if (!box) return;
  const list = monFilter(zeilen);
  if (list.length < monTransN) {
    box.innerHTML = "";
    monTransN = 0;
  }
  for (let i = monTransN; i < list.length; i++) {
    const z = list[i];
    const div = document.createElement("div");
    div.className = "mon-zeile " + (z.wer || "system");
    const t = Number(z.tS || 0).toFixed(1);
    div.innerHTML = `<div class="meta">${t}s<br>#${z.nr || "?"} ${z.kurz || ""}</div>
      <div class="txt">${String(z.text || "").replace(/</g, "&lt;")}</div>`;
    box.appendChild(div);
  }
  if (list.length > monTransN) {
    box.lastElementChild?.scrollIntoView({ block: "end" });
  }
  monTransN = list.length;
}

function lasttestZeichnen(lt) {
  if (!lt) return;
  monStand = lt;
  if ($("mon-popup").hidden) return;
  const n = lt.n || 0;
  const fertig = lt.fertig || 0;
  const k = lt.kpis || {};
  const e = lt.ergebnis || {};
  const gehalten = e.gehalten != null ? e.gehalten : fertig;
  const off = k.offsetPct || 0;
  $("mon-status").textContent = lt.phase === "fertig"
    ? `fertig · ${gehalten}/${n} gehalten · Offset ${off > 0 ? "+" : ""}${off} %`
    : `läuft · ${fertig}/${n} Sessions · Offset ${off > 0 ? "+" : ""}${off} %`;
  $("mon-kpis").innerHTML = [
    ["Sessions", `${fertig}/${n}`],
    ["Offset", `${off > 0 ? "+" : ""}${off} %`, monKpiKlasse(off)],
    ["Erster Ton p50", `${(k.ersterTonP50 || 0).toFixed(2)}s`],
    ["Antwort p95", `${(k.antwortP95 || 0).toFixed(2)}s`],
    ["Dropouts", String(k.dropouts || 0), (k.dropouts || 0) ? "bad" : "ok"],
  ].map(([lbl, val, kl]) =>
    `<div class="mon-kpi"><div class="lbl">${lbl}</div><div class="val ${kl || ""}">${val}</div></div>`
  ).join("");
  monTabsZeichnen(lt.plan);
  monLatenzZeichnen(lt.latenz || (e.latenz || []), lt.norm || e.norm);
  monDropZeichnen(lt.blasen || e.blasen || []);
  const trans = (lt.transkript && lt.transkript.length)
    ? lt.transkript
    : (e.transkript || []);
  monTransZeichnen(trans);
}

async function lasttestStarten() {
  $("fehler").textContent = "";
  lastSetupZu();
  monTab = 0;
  monTransN = 0;
  if ($("mon-trans")) $("mon-trans").innerHTML = "";
  monAuf();
  $("mon-status").textContent = "startet …";
  const r = await fetch("api/lasttest", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ n: lastN(), zuege: 2 }),
  });
  const d = await r.json();
  if (!d.ok) {
    $("fehler").textContent = d.fehler || "Belastungstest fehlgeschlagen";
    return;
  }
  pollerStarten();
}

function automatik() {
  const zuf = (arr) => arr[Math.floor(Math.random() * arr.length)];
  wahl.stimme = zuf(KATALOG.stimmen);
  wahl.nachname = zuf(KATALOG.nachnamen);
  wahl.anliegen = "termin";
  wahl.grund = zuf(Object.keys(KATALOG.gruende));
  wahl.behandler = zuf([...KATALOG.behandler, "egal"]);
  wahl.versicherung = zuf(["privat", "gesetzlich"]);
  wahl.slotAnnahme = zuf([1, 2, 2, 3]);
  wahl.slotRichtung = zuf(["frueher", "spaeter"]);
  wahl.abschweifer = new Set(Math.random() < 0.6 ? [zuf(KATALOG.abschweifer)] : []);
  wahl.extras = new Set(Math.random() < 0.2 ? ["halbsatz"] : []);
  if (Math.random() < 0.5) wahl.extras.add("pzr");
  const pool = KATALOG.einzelwoerter || [];
  wahl.einzelwoerter = new Set();
  const n = 2 + Math.floor(Math.random() * 2);
  if (pool.length) {
    for (let i = 0; i < n; i++) wahl.einzelwoerter.add(zuf(pool));
  }
  einzelwortAnzahlSetzen(n);
  chipsBauen();
}

async function laufStarten(anzahl) {
  $("fehler").textContent = "";
  await ohrOeffnen();
  mithoerenSetzen(true);
  popupAuf();
  $("live-dialog").innerHTML = "";
  $("live-story").textContent = "startet …";
  const body = {
    anzahl, ab: storyNr, tag: wahl.tag || "Mittwoch",
    mithoeren: true,
    tenant: praxisId(),
    leitung: leitungLesen(),
  };
  if (anzahl === 1) body.story = storyBauen();
  const r = await fetch("api/lauf", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  if (!d.ok) { $("fehler").textContent = d.fehler || "Start fehlgeschlagen"; return; }
  storyNr += anzahl;
  gespielt.clear();
  spielKette = Promise.resolve();
  pollerStarten();
}

function bubbleBauen(z) {
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
  (z.waechter || []).forEach((w) => {
    meta.insertAdjacentHTML("beforeend",
      `<span class="tag waechter" title="${(w.d || "").replace(/"/g, "&quot;")}">${w.w}</span>`);
  });
  if (z.frage) meta.insertAdjacentHTML("beforeend", `<span class="tag">frage=${z.frage}</span>`);
  if (z.baustein) meta.insertAdjacentHTML("beforeend", `<span class="tag">${z.baustein}</span>`);
  if (z.gehoert && z.gehoert !== z.text) {
    meta.insertAdjacentHTML("beforeend", `<span class="tag gehoert">gehört: ${z.gehoert}</span>`);
  }
  if (z.book && z.book.booked) meta.insertAdjacentHTML("beforeend", `<span class="tag" style="color:var(--gruen)">GEBUCHT ${String(z.book.slotIso || "").slice(0, 16)}</span>`);
  if (z.audioUrl || z.audio) {
    const knopf = document.createElement("button");
    knopf.textContent = "▶";
    knopf.addEventListener("click", () => {
      ohrOeffnen();
      spielen(z.audioUrl || z.audio);
    });
    meta.appendChild(knopf);
  }
  if (meta.children.length) div.appendChild(meta);
  return div;
}

function mithoerenSpielen(z) {
  const rel = z.audioUrl || z.audio;
  if (!mithoerenAn() || !rel || gespielt.has(rel)) return;
  gespielt.add(rel);
  spielKette = spielKette.then(() => spielen(rel));
}

async function pollen() {
  let d;
  try {
    const r = await fetch("api/live");
    d = await r.json();
  } catch { return; }
  const idx = d.storyIdx || 0;
  if (d.lasttest && d.laeuft) {
    $("status").textContent = `Lasttest ${d.lasttest.fertig || 0}/${d.lasttest.n || 0} · ${d.laufId}`;
  } else {
    $("status").textContent = d.laeuft
      ? `Lauf ${d.laufId}: Story ${idx}/${d.storiesGesamt} ${d.story || ""}`
      : (d.laufId ? `Lauf ${d.laufId} fertig — ${(d.fertig || []).filter((x) => x.ok).length}/${(d.fertig || []).length} grün` : "bereit");
  }
  $("lauf-hinweis").innerHTML = (d.laufId && !d.lasttest)
    ? `<a href="ergebnisse#${d.laufId}" style="color:var(--akzent)">Ergebnisse des Laufs ansehen</a>` : "";
  if (d.fehler) $("fehler").textContent = d.fehler;
  $("knopf-start").disabled = d.laeuft;
  $("knopf-batch").disabled = d.laeuft;
  if ($("knopf-lasttest")) $("knopf-lasttest").disabled = d.laeuft && !d.lasttest;
  if (d.lasttest) lasttestZeichnen(d.lasttest);

  if (d.warm && d.warm.n) {
    const t = String(d.warm.text || "");
    $("live-story").textContent = `Audio ${d.warm.i}/${d.warm.n}: ${t}`;
  } else if (d.story) {
    $("live-story").textContent = d.story;
  }
  const dialog = $("live-dialog");
  if (d.zuege && d.zuege.length) {
    // Nur fehlende Bubbles anhaengen (kein Flackern beim Poll).
    while (dialog.children.length > d.zuege.length) dialog.removeChild(dialog.lastChild);
    for (let i = dialog.children.length; i < d.zuege.length; i++) {
      dialog.appendChild(bubbleBauen(d.zuege[i]));
      mithoerenSpielen(d.zuege[i]);
    }
    dialog.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "end" });
  } else if (!d.laeuft) {
    // Lauf fertig: Poller schlafen legen.
    clearInterval(poller);
    poller = null;
  }
}

function pollerStarten() {
  if (poller) return;
  pollen();
  poller = setInterval(pollen, 350);
}

async function katalogLaden(tenant) {
  const q = tenant ? ("?tenant=" + encodeURIComponent(tenant)) : "";
  const r = await fetch("api/katalog" + q);
  if (!r.ok) throw new Error("Katalog " + r.status);
  KATALOG = await r.json();
  if ($("demo-satz")) $("demo-satz").textContent = KATALOG.demoSatz || "";
  const bekannt = new Set(KATALOG.einzelwoerter || []);
  wahl.einzelwoerter = new Set([...wahl.einzelwoerter].filter((w) => bekannt.has(w)));
  if (wahl.grund && !(wahl.grund in (KATALOG.gruende || {}))) wahl.grund = "";
  if (wahl.behandler && wahl.behandler !== "egal"
      && !(KATALOG.behandler || []).includes(wahl.behandler)) wahl.behandler = null;
  chipsBauen();
}

async function demoSpielen() {
  $("fehler").textContent = "";
  await ohrOeffnen();
  const r = await fetch("api/leitung-probe", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(leitungLesen()),
  });
  if (!r.ok) {
    let msg = "Demosatz fehlgeschlagen";
    try { const d = await r.json(); if (d.fehler) msg = d.fehler; } catch { /* */ }
    $("fehler").textContent = msg;
    return;
  }
  const blob = await r.blob();
  const obj = URL.createObjectURL(blob);
  try {
    lautsprecher.src = obj;
    await lautsprecher.play();
  } catch (e) {
    $("fehler").textContent = "Wiedergabe blockiert — einmal ins Fenster tippen.";
    console.warn("studio-demo", e);
  }
}

async function boot() {
  try {
    const data = await (await fetch("api/tenants")).json();
    TENANTS = (data.tenants || []).filter((t) => t.id !== "demo");
    const sel = $("tenant");
    if (sel) {
      sel.innerHTML = TENANTS.map((t) =>
        `<option value="${t.id}">${t.praxisName || t.id}</option>`).join("");
    }
    let id = praxisId();
    if (!TENANTS.some((t) => t.id === id)) {
      id = data.default || (TENANTS[0] && TENANTS[0].id) || "";
    }
    if (id) praxisSetzen(id);
    praxisChipsZeichnen();
    await katalogLaden(id);
  } catch (e) {
    if ($("fehler")) $("fehler").textContent = "Katalog nicht erreichbar.";
    console.warn("studio-boot", e);
  }
  const tenantWechsel = async (id) => {
    const wert = String(id || "").trim();
    const sel = $("tenant");
    if (!wert || !TENANTS.some((t) => t.id === wert) ||
        (sel && sel.value === wert)) return;
    praxisSetzen(wert);
    try {
      await katalogLaden(wert);
      if ($("fehler")) $("fehler").textContent = "";
    } catch {
      if ($("fehler")) $("fehler").textContent = "Katalog dieser Praxis nicht erreichbar.";
    }
  };
  window.addEventListener("message", (ev) => {
    if (ev.origin !== location.origin) return;
    const d = ev.data || {};
    if (d.type === "pickadoc:tenant") tenantWechsel(d.tenant);
  });
  window.addEventListener("storage", (ev) => {
    if (ev.key === PRAXIS_KEY && ev.newValue) tenantWechsel(ev.newValue);
  });
  leitungZeichnen();
  einzelwortAnzahlZeichnen();
  ["lt-hz", "lt-rauschen", "lt-artefakte", "lt-dropouts", "lt-pegel"].forEach((id) => {
    if ($(id)) $(id).addEventListener("input", leitungZeichnen);
  });
  if ($("ew-n")) $("ew-n").addEventListener("input", einzelwortAnzahlZeichnen);
  if ($("last-n")) $("last-n").addEventListener("input", lastPlanAktualisieren);
  $("knopf-automatik").addEventListener("click", automatik);
  $("knopf-demo").addEventListener("click", demoSpielen);
  $("knopf-start").addEventListener("click", () => laufStarten(1));
  $("knopf-batch").addEventListener("click", () => laufStarten(10));
  if ($("knopf-lasttest")) $("knopf-lasttest").addEventListener("click", () => {
    if (monStand && (monStand.phase === "lauf" || monStand.phase === "fertig" || monStand.phase === "start")) {
      monAuf();
      lasttestZeichnen(monStand);
      return;
    }
    lastSetupAuf();
  });
  if ($("last-setup-zu")) $("last-setup-zu").addEventListener("click", lastSetupZu);
  if ($("last-go")) $("last-go").addEventListener("click", lasttestStarten);
  if ($("mon-zu")) $("mon-zu").addEventListener("click", monZu);
  if ($("mon-prev")) $("mon-prev").addEventListener("click", () => {
    monTab = (monTab + MON_TABS.length - 1) % MON_TABS.length;
    monTransN = 0;
    if ($("mon-trans")) $("mon-trans").innerHTML = "";
    if (monStand) lasttestZeichnen(monStand);
  });
  if ($("mon-next")) $("mon-next").addEventListener("click", () => {
    monTab = (monTab + 1) % MON_TABS.length;
    monTransN = 0;
    if ($("mon-trans")) $("mon-trans").innerHTML = "";
    if (monStand) lasttestZeichnen(monStand);
  });
  $("anruf-zu").addEventListener("click", popupZu);
  $("mithoeren").addEventListener("change", () => mithoerenSetzen($("mithoeren").checked));
  $("mithoeren-popup").addEventListener("change", () => {
    mithoerenSetzen($("mithoeren-popup").checked);
    if ($("mithoeren-popup").checked) ohrOeffnen();
  });
  $("anruf-popup").addEventListener("pointerdown", () => { ohrOeffnen(); });
  pollen();
}

boot();
