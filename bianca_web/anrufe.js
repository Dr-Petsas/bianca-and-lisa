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

/** Anruf-UID lesbar: uuid4.hex (32) mit Bindestrichen; kurze Alt-IDs unverändert. */
function uidForm(roh) {
  const h = String(roh || "").replace(/-/g, "").toLowerCase();
  if (/^[0-9a-f]{32}$/.test(h)) {
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  }
  return String(roh || "");
}

/** Zwischenablage: clipboard-API braucht HTTPS/localhost; über Tailscale-HTTP
    fällt der execCommand-Pfad ein (sonst schweigt der Knopf still). */
async function inZwischenablage(text) {
  const t = String(text || "");
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(t);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = t;
  ta.setAttribute("readonly", "");
  ta.style.cssText = "position:fixed;left:-9999px;top:0";
  document.body.appendChild(ta);
  ta.select();
  ta.setSelectionRange(0, t.length);
  let ok = false;
  try { ok = document.execCommand("copy"); } finally { document.body.removeChild(ta); }
  if (!ok) throw new Error("copy");
}

function kopierKnopf(text, label) {
  const b = document.createElement("button");
  b.className = "kopie";
  b.type = "button";
  b.textContent = label || "kopieren";
  b.title = "in Zwischenablage";
  b.onclick = async (ev) => {
    ev.stopPropagation();
    try {
      await inZwischenablage(text);
      b.textContent = "kopiert";
      setTimeout(() => { b.textContent = label || "kopieren"; }, 1200);
    } catch {
      b.textContent = "fehlgeschlagen";
      setTimeout(() => { b.textContent = label || "kopieren"; }, 1500);
    }
  };
  return b;
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

function msChip(label, s) {
  return chip(`${label} ${Math.round(Number(s) * 1000)} ms`);
}

function sttChips(t) {
  if (t && t.stt != null) return [msChip("stt", t.stt)];
  return [];
}

function kiTimingChips(t) {
  if (!t) return [];
  const aus = [];
  if (t.llm != null) aus.push(msChip("llm", t.llm));
  if (t.ttsCache) {
    aus.push(chip("tts cache"));
  } else if (t.tts != null) {
    aus.push(msChip("tts", t.tts));
  }
  if (t.total != null) aus.push(msChip("total", t.total));
  return aus;
}

function bubble(wer, text) {
  const d = document.createElement("div");
  d.className = `bubble ${wer}`;
  d.textContent = text;
  return d;
}

function jsonText(v) {
  try { return JSON.stringify(v, null, 2); } catch { return String(v ?? ""); }
}

function toolKarte(t) {
  const d = t.dispatch || {};
  const name = d.route || t.cf || t.name || "tool";
  const ok = t.ok !== false && (d.httpStatus == null || d.httpStatus === 200);
  const ms = d.ms != null ? d.ms : t.ms;
  const card = document.createElement("details");
  card.className = "tool-card";
  const sum = document.createElement("summary");
  const n = document.createElement("span");
  n.className = "tool-name";
  n.textContent = name;
  sum.appendChild(n);
  const marke = document.createElement("span");
  marke.className = `marke ${ok ? "gruen" : "gelb"}`;
  marke.textContent = ok ? "Succeeded" : "Failed";
  sum.appendChild(marke);
  if (ms != null) sum.appendChild(chip(ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`));
  if (t.name && t.name !== name) sum.appendChild(chip(t.name));
  card.appendChild(sum);

  const body = document.createElement("div");
  body.className = "tool-body";

  if (d.url) {
    const abs = document.createElement("div");
    abs.className = "tool-abs";
    const lab = document.createElement("b");
    lab.textContent = "Requested URL";
    abs.appendChild(lab);
    const url = document.createElement("div");
    url.className = "tool-url";
    url.textContent = `${d.method || "POST"} ${d.url}`;
    abs.appendChild(url);
    body.appendChild(abs);
  }

  const req = d.request != null ? d.request : t.args;
  if (req != null) {
    const abs = document.createElement("div");
    abs.className = "tool-abs";
    const kopf = document.createElement("div");
    kopf.className = "tool-kopf";
    const lab = document.createElement("b");
    lab.textContent = d.request != null ? "Request Body" : "Parameters";
    kopf.appendChild(lab);
    kopf.appendChild(kopierKnopf(jsonText(req), "Copy"));
    abs.appendChild(kopf);
    const pre = document.createElement("pre");
    pre.className = "tool-json";
    pre.textContent = jsonText(req);
    abs.appendChild(pre);
    body.appendChild(abs);
  }

  if (t.args && d.request != null) {
    const abs = document.createElement("div");
    abs.className = "tool-abs";
    const lab = document.createElement("b");
    lab.textContent = "Parameters extracted by LLM";
    abs.appendChild(lab);
    const pre = document.createElement("pre");
    pre.className = "tool-json";
    pre.textContent = jsonText(t.args);
    abs.appendChild(pre);
    body.appendChild(abs);
  }

  if (ms != null) {
    const abs = document.createElement("div");
    abs.className = "tool-abs";
    const lab = document.createElement("b");
    lab.textContent = "Tool execution time";
    abs.appendChild(lab);
    const v = document.createElement("div");
    v.textContent = ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
    abs.appendChild(v);
    body.appendChild(abs);
  }

  if (d.response != null) {
    const abs = document.createElement("div");
    abs.className = "tool-abs";
    const kopf = document.createElement("div");
    kopf.className = "tool-kopf";
    const lab = document.createElement("b");
    lab.textContent = "Response";
    kopf.appendChild(lab);
    kopf.appendChild(kopierKnopf(jsonText(d.response), "Copy"));
    abs.appendChild(kopf);
    const pre = document.createElement("pre");
    pre.className = "tool-json";
    pre.textContent = jsonText(d.response);
    abs.appendChild(pre);
    body.appendChild(abs);
  }

  const ups = d.updates || [];
  if (ups.length) {
    const abs = document.createElement("div");
    abs.className = "tool-abs";
    const lab = document.createElement("b");
    lab.textContent = "Dynamic Variable Updates";
    abs.appendChild(lab);
    const liste = document.createElement("div");
    liste.className = "tool-upd";
    for (const u of ups) {
      const z = document.createElement("div");
      z.className = "tool-upd-zeile";
      const key = document.createElement("b");
      key.style.color = "var(--text)";
      key.textContent = u.key || "?";
      z.appendChild(key);
      z.appendChild(document.createTextNode(" "));
      const von = document.createElement("span");
      von.className = "von";
      von.textContent = u.from === "" || u.from == null ? "EMPTY STRING" : jsonText(u.from);
      z.appendChild(von);
      z.appendChild(document.createTextNode(" → "));
      const nach = document.createElement("span");
      nach.className = "nach";
      let toText = jsonText(u.to);
      if (u.key === "free_time_slots" && Array.isArray(u.to) && u.total && u.total > u.to.length) {
        toText = `[${u.to.length} shown / ${u.total} total] ` + toText;
      }
      nach.textContent = toText;
      z.appendChild(nach);
      liste.appendChild(z);
    }
    abs.appendChild(liste);
    body.appendChild(abs);
  }

  if (!body.children.length) {
    const abs = document.createElement("div");
    abs.className = "tool-abs";
    abs.textContent = t.spoken || (ok ? "ok" : "fehlgeschlagen");
    body.appendChild(abs);
  }
  card.appendChild(body);
  return card;
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
  const uidZeile = document.createElement("div");
  uidZeile.className = "uid-zeile";
  const uidLabel = document.createElement("span");
  uidLabel.textContent = "UID ";
  const uidCode = document.createElement("code");
  uidCode.className = "uid";
  uidCode.textContent = uidForm(sid);
  uidZeile.appendChild(uidLabel);
  uidZeile.appendChild(uidCode);
  uidZeile.appendChild(kopierKnopf(sid, "kopieren"));
  if (a.phoneCallId) {
    const sep = document.createElement("span");
    sep.className = "uid-sep";
    sep.textContent = " · Portal ";
    const pc = document.createElement("code");
    pc.className = "uid";
    pc.textContent = a.phoneCallId;
    uidZeile.appendChild(sep);
    uidZeile.appendChild(pc);
    uidZeile.appendChild(kopierKnopf(a.phoneCallId, "kopieren"));
  }
  zeiten.appendChild(uidZeile);
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
    // Download: Server fügt alle Züge zu EINEM WAV (api/anrufe/<sid>/download).
    const dl = document.createElement("a");
    dl.className = "knopf";
    dl.href = `api/anrufe/${sid}/download`;
    dl.setAttribute("download", "");
    dl.textContent = "\u2B07 Audio herunterladen";
    knoepfe.appendChild(dl);
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
      for (const c of sttChips(z.timings)) m.appendChild(c);
      b.appendChild(m);
      fluss.appendChild(b);
    }
    if (z.text) {
      const b = bubble("ki", z.text);
      const m = document.createElement("div");
      m.className = "b-meta";
      m.appendChild(chip(`${mmss(z.offsetMs)}`));
      if (z.art && z.art !== "turn" && z.art !== "listen") m.appendChild(chip(z.art));
      for (const c of kiTimingChips(z.timings)) m.appendChild(c);
      if (raus.length) m.appendChild(playKnopf(raus, "Bianca"));
      b.appendChild(m);
      fluss.appendChild(b);
    }
    if (z.book && (z.book.ok || z.book.booked)) {
      fluss.appendChild(bubble("sys", `Buchung: ${z.book.spoken || z.book.slotIso || "ok"}`));
    }
    for (const t of z.tools || []) {
      fluss.appendChild(toolKarte(t));
    }
    if (z.art === "hangup") {
      fluss.appendChild(bubble("sys", `Aufgelegt${z.note ? " — Notiz: " + z.note : ""}`));
    }
  }
  // Ältere Mitschnitte: Tools nur am Manifest-Kopf, nicht je Zug.
  const hatZugTools = (a.zuege || []).some((z) => (z.tools || []).length);
  if (!hatZugTools) {
    for (const t of a.tools || []) fluss.appendChild(toolKarte(t));
  }
  if (!(a.zuege || []).length && !(a.tools || []).length) {
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
