/* Anrufliste (W-MITSCHNITT 30.08.2026): Unterhaltungen aus .data/anrufe —
   Liste links, Gespräch rechts mit Abspiel-Knöpfen je Zug, Timings-Chips
   (stt/llm/tts/total) und allen Zeiten. Reine Anzeige, kein Anruf-Pfad.
   Relative Pfade ("api/…"), damit die Seite auch hinter Lisas
   /bianca/-Durchreiche funktioniert. */

const $ = (id) => document.getElementById(id);
const spieler = $("spieler");
let anrufe = [];
let aktivId = "";
let laufKnopf = null;
let kette = [];

function zeit(iso) {
  try {
    return new Date(iso).toLocaleString("de-DE", {
      day: "2-digit", month: "2-digit", year: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch { return iso || ""; }
}

function mmss(ms) {
  if (ms == null || isNaN(ms)) return "";
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function ergebnis(a) {
  if (a.lastBook && a.lastBook.ok) return ["Termin gebucht", "gruen"];
  if (a.lastMove && a.lastMove.ok) return ["Termin verschoben", "gruen"];
  if (a.lastCancel && a.lastCancel.ok) return ["Termin abgesagt", "gruen"];
  if (a.praxisNotiz) return ["Notiz an die Praxis", "gelb"];
  if (a.offen) return ["läuft / offen", "gelb"];
  return ["ohne Buchung", "grau"];
}

function stoppTon() {
  try { spieler.pause(); } catch { /* */ }
  spieler.onended = null;
  kette = [];
  if (laufKnopf) { laufKnopf.classList.remove("laeuft"); laufKnopf = null; }
}

function spieleKette(urls, knopf) {
  if (laufKnopf === knopf) { stoppTon(); return; }
  stoppTon();
  kette = urls.slice();
  laufKnopf = knopf;
  knopf.classList.add("laeuft");
  const weiter = () => {
    const url = kette.shift();
    if (!url) { stoppTon(); return; }
    spieler.src = url;
    spieler.onended = weiter;
    spieler.play().catch(() => stoppTon());
  };
  weiter();
}

function audioUrl(sid, datei) {
  return `api/anrufe/${sid}/audio/${datei}`;
}

function zugAudios(sid, z) {
  const rein = (z.audioIn || []).map((e) => audioUrl(sid, e.datei));
  const raus = (z.audioOut || []).filter((e) => e.datei).map((e) => audioUrl(sid, e.datei));
  return { rein, raus };
}

function playKnopf(urls, label) {
  const b = document.createElement("button");
  b.className = "play";
  b.type = "button";
  b.textContent = `\u25B6 ${label}`;
  b.onclick = () => spieleKette(urls, b);
  return b;
}

function chip(text) {
  const c = document.createElement("span");
  c.className = "chip";
  c.textContent = text;
  return c;
}

function timingChips(t) {
  const aus = [];
  for (const k of ["stt", "llm", "tts", "total"]) {
    if (t && t[k] != null) aus.push(chip(`${k} ${Number(t[k]).toFixed(2)}s`));
  }
  return aus;
}

function bubble(wer, text) {
  const d = document.createElement("div");
  d.className = `bubble ${wer}`;
  d.textContent = text;
  return d;
}

function maleDetail(a) {
  const sid = a.id;
  const wurzel = $("detail");
  wurzel.innerHTML = "";
  const kopf = document.createElement("div");
  kopf.className = "detail-kopf";
  const zeiten = document.createElement("div");
  zeiten.className = "zeiten";
  const dauer = a.dauerMs != null ? mmss(a.dauerMs) + " min" : "läuft / offen";
  zeiten.innerHTML =
    `<b>${a.patientName || "Unbekannter Anrufer"}</b> — ${a.zuege ? a.zuege.length : 0} Züge<br>` +
    `Beginn: <b>${zeit(a.startedAt)}</b> · Ende: <b>${a.endedAt ? zeit(a.endedAt) : "—"}</b> · Dauer: <b>${dauer}</b>`;
  kopf.appendChild(zeiten);

  const knoepfe = document.createElement("div");
  knoepfe.style.cssText = "display:flex; gap:8px; flex-wrap:wrap;";
  const alle = [];
  for (const z of a.zuege || []) {
    const { rein, raus } = zugAudios(sid, z);
    alle.push(...rein, ...raus);
  }
  if (alle.length) {
    const b = document.createElement("button");
    b.className = "knopf";
    b.type = "button";
    b.textContent = "\u25B6 Anruf abspielen";
    b.onclick = () => spieleKette(alle, b);
    knoepfe.appendChild(b);
  }
  const del = document.createElement("button");
  del.className = "knopf rot";
  del.type = "button";
  del.textContent = "Löschen";
  del.onclick = async () => {
    if (!confirm("Diesen Mitschnitt endgültig löschen?")) return;
    stoppTon();
    try { await fetch(`api/anrufe/${sid}/loeschen`, { method: "POST" }); } catch { /* */ }
    aktivId = "";
    ladeListe();
    wurzel.innerHTML = '<div class="leer">gelöscht</div>';
  };
  knoepfe.appendChild(del);
  kopf.appendChild(knoepfe);
  wurzel.appendChild(kopf);

  if (a.praxisNotiz) {
    const n = document.createElement("div");
    n.className = "zeiten";
    n.style.marginTop = "8px";
    n.innerHTML = `Praxis-Notiz: <b>${a.praxisNotiz}</b>`;
    wurzel.appendChild(n);
  }

  const fluss = document.createElement("div");
  fluss.className = "zuege";
  for (const z of a.zuege || []) {
    const { rein, raus } = zugAudios(sid, z);
    if (z.textIn) {
      const b = bubble("user", z.textIn);
      const m = document.createElement("div");
      m.className = "b-meta";
      m.appendChild(chip(`${mmss(z.offsetMs)}`));
      if (rein.length) m.appendChild(playKnopf(rein, "Anrufer"));
      b.appendChild(m);
      fluss.appendChild(b);
    }
    if (z.text) {
      const b = bubble("ki", z.text);
      const m = document.createElement("div");
      m.className = "b-meta";
      m.appendChild(chip(`${mmss(z.offsetMs)}`));
      if (z.art && z.art !== "turn" && z.art !== "listen") m.appendChild(chip(z.art));
      for (const c of timingChips(z.timings)) m.appendChild(c);
      if (raus.length) m.appendChild(playKnopf(raus, "Bianca"));
      b.appendChild(m);
      fluss.appendChild(b);
    }
    if (z.book && (z.book.ok || z.book.booked)) {
      fluss.appendChild(bubble("sys", `Buchung: ${z.book.spoken || z.book.slotIso || "ok"}`));
    }
    if (z.art === "hangup") {
      fluss.appendChild(bubble("sys", `Aufgelegt${z.note ? " — Notiz: " + z.note : ""}`));
    }
  }
  if (!(a.zuege || []).length) {
    fluss.appendChild(bubble("sys", "keine Züge aufgezeichnet"));
  }
  wurzel.appendChild(fluss);
}

async function oeffne(sid) {
  aktivId = sid;
  maleListe();
  stoppTon();
  try {
    const r = await fetch(`api/anrufe/${sid}`);
    const d = await r.json();
    if (d && d.ok) maleDetail(d.anruf);
  } catch {
    $("detail").innerHTML = '<div class="leer">Anruf ließ sich nicht laden</div>';
  }
}

function maleListe() {
  const wurzel = $("liste");
  wurzel.innerHTML = "";
  if (!anrufe.length) {
    wurzel.innerHTML = '<div class="leer">noch keine Mitschnitte — einfach bei Bianca anrufen</div>';
    return;
  }
  for (const a of anrufe) {
    const e = document.createElement("div");
    e.className = "eintrag" + (a.id === aktivId ? " aktiv" : "");
    const [text, farbe] = ergebnis(a);
    const kopf = document.createElement("div");
    kopf.className = "e-kopf";
    const name = document.createElement("span");
    name.textContent = a.patientName || "Unbekannter Anrufer";
    const marke = document.createElement("span");
    marke.className = `marke ${farbe}`;
    marke.textContent = text;
    kopf.appendChild(name);
    kopf.appendChild(marke);
    const meta = document.createElement("div");
    meta.className = "e-meta";
    meta.textContent = `${zeit(a.startedAt)} · ${a.dauerMs != null ? mmss(a.dauerMs) + " min" : "offen"} · ${a.zuege} Züge`;
    e.appendChild(kopf);
    e.appendChild(meta);
    e.onclick = () => oeffne(a.id);
    wurzel.appendChild(e);
  }
}

async function ladeListe() {
  try {
    const r = await fetch("api/anrufe");
    const d = await r.json();
    anrufe = (d && d.anrufe) || [];
  } catch {
    anrufe = [];
  }
  maleListe();
}

$("neuLaden").onclick = () => { ladeListe(); if (aktivId) oeffne(aktivId); };
ladeListe();
