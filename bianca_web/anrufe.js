/* Anrufliste (W-MITSCHNITT 30.08.2026): Unterhaltungen aus .data/anrufe —
   Liste links, Gespräch rechts mit Abspiel-Knöpfen je Zug, Timings-Chips
   (stt/llm/tts/total) und allen Zeiten. Reine Anzeige, kein Anruf-Pfad.
   Relative Pfade ("api/…"), damit die Seite auch hinter Lisas
   /bianca/-Durchreiche funktioniert. */

const $ = (id) => document.getElementById(id);
const spieler = $("spieler");
const ART_KEY = "pickadoc.anrufe.art";
const DATUM_KEY = "pickadoc.anrufe.tag";
let anrufe = [];
let aktivId = "";
let laufKnopf = null;
let kette = [];
let artFilter = "alle";
let datumFilter = "";
let tenantAliase = {};

function artLesen() {
  try {
    const v = localStorage.getItem(ART_KEY);
    if (v === "test" || v === "live" || v === "alle") return v;
  } catch { /* */ }
  return "alle";
}

function artSchreiben(v) {
  artFilter = v;
  try { localStorage.setItem(ART_KEY, v); } catch { /* */ }
}

function heuteTag() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Kalendertag in der gleichen lokalen Zone wie die angezeigte Uhrzeit. */
function anrufTag(a) {
  try {
    const d = new Date(a && a.startedAt);
    if (isNaN(d.getTime())) return "";
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  } catch { return ""; }
}

function tagSprechbar(isoTag) {
  const t = String(isoTag || "");
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : t;
}

function datumLesen() {
  try {
    const v = localStorage.getItem(DATUM_KEY);
    if (v === "") return "";
    if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return v;
  } catch { /* */ }
  return "";
}

function datumSchreiben(v) {
  const tag = v === "" ? "" : (/^\d{4}-\d{2}-\d{2}$/.test(v) ? v : heuteTag());
  datumFilter = tag;
  try { localStorage.setItem(DATUM_KEY, tag); } catch { /* */ }
}

function imDatum(a) {
  if (!datumFilter) return true;
  return anrufTag(a) === datumFilter;
}

function istTest(a) {
  if (!a) return false;
  if (a.testAnruf) return true;
  if (a.phoneCallId) return false;
  return true;
}

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

function anruferName(a) {
  const name = String(a.patientName || a.testName || "").trim();
  if (istTest(a)) return name ? `Test · ${name}` : "Testanruf";
  return name || "Unbekannter Anrufer";
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

/** W-QWEN-KORREKTOR (13.09.2026): Chef — „in den anrufen muss ich sehen
    welches ... parakeet oder qwen transkribiert hat". Je Anrufer-Zug steht
    im Manifest `stt` (Gewinner, beide Texte, spaetes Qwen, Korrektur). */
const OHR_NAME = {
  parakeet: "Parakeet STT",
  qwen: "Qwen STT",
  whisper_oder_parakeet: "Whisper/Parakeet STT",
  elevenlabs: "ElevenLabs STT",
};

function ohrChips(st) {
  if (!st || typeof st !== "object") return [];
  const aus = [];
  const winner = String(st.winner || "");
  if (winner) {
    const cls = winner === "parakeet" ? "ohr-parakeet" : winner === "qwen" ? "ohr-qwen" : "ohr-sonst";
    const c = chip(OHR_NAME[winner] || `${winner} STT`);
    c.className = `chip ${cls}`;
    const q = st.qwen || {};
    const tipp = [];
    if (q.status) tipp.push(`Qwen: ${q.status}`);
    if (q.reason) tipp.push(q.reason);
    // W-QWEN-SICHER: Namensfrage/Diktat/erwartete Antwort — Qwen durfte
    // diesen Zug nicht live uebernehmen.
    if (q.sperre) tipp.push(`Qwen live gesperrt: ${q.sperre}`);
    if (st.parakeet && st.parakeet.suspicious) tipp.push("Parakeet-Text auffällig");
    if (tipp.length) c.title = tipp.join(" · ");
    aus.push(c);
  }
  const spaet = st.qwen && st.qwen.spaet;
  if (spaet && spaet.qwen) {
    const gleich = normText(spaet.qwen) === normText((st.parakeet || {}).text || "");
    const c = chip(gleich ? "Qwen (spät) gleich" : "Qwen (spät) anders");
    c.className = `chip ohr-spaet`;
    c.title = `Qwen nach ${spaet.s != null ? Math.round(Number(spaet.s) * 1000) + " ms" : "?"}: „${spaet.qwen}“`
      + (spaet.auth ? "" : " (nicht autoritativ)")
      + (spaet.gelernt && spaet.gelernt.length ? ` · gelernt: ${spaet.gelernt.join(", ")}` : "")
      + (spaet.gesperrt ? ` · kein Lernen/Vorzug (${spaet.gesperrt})` : "");
    aus.push(c);
  } else if (winner === "parakeet" && st.qwen && st.qwen.status
             && st.qwen.status !== "aus" && st.qwen.status !== "abgelehnt"
             && st.qwen.status !== "parallel_zu_spaet" && !st.qwen.text) {
    // Qwen war konfiguriert, hat aber nichts geliefert (belegt/pausiert).
    const c = chip("Qwen fehlt");
    c.className = "chip ohr-warn";
    c.title = `Qwen-Status: ${st.qwen.status}`;
    aus.push(c);
  }
  const k = st.korrektur;
  if (k && typeof k === "object") {
    const c = chip(k.vorzug ? `Qwen-Korrektur (${k.grund || "vorzug"})` : "Qwen-Wörterbuch");
    c.className = "chip ohr-korrektur";
    const teile = [];
    if (k.textVorher && k.text) teile.push(`„${k.textVorher}“ → „${k.text}“`);
    if (k.woerterbuch && k.woerterbuch.length) teile.push(k.woerterbuch.join(", "));
    if (k.vorzug && k.qwenVorher) teile.push(`voriger Zug richtig: „${k.qwenVorher}“ (gehört: „${k.parakeetVorher || ""}“)`);
    if (k.verlauf) teile.push("LLM-Verlauf umgeschrieben");
    c.title = teile.join(" · ");
    aus.push(c);
  }
  return aus;
}

function normText(s) {
  return String(s || "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

/** Zweitzeile unter dem Anrufer-Satz, wenn Qwen etwas ANDERES gehoert hat
    oder eine Korrektur angewandt wurde — der Vergleich muss lesbar sein,
    nicht nur als Tooltip. */
function ohrDetail(st) {
  if (!st || typeof st !== "object") return null;
  const p = (st.parakeet || {}).text || "";
  const qLive = (st.qwen || {}).text || "";
  const spaet = st.qwen && st.qwen.spaet;
  const qSpaet = spaet && spaet.qwen ? spaet.qwen : "";
  const k = st.korrektur;
  const zeilen = [];
  if (st.winner === "qwen" && p && normText(p) !== normText(qLive)) {
    zeilen.push(`Parakeet hörte: <span class="alt">${escapeHtml(p)}</span> · <b>Qwen gewann</b>`);
  }
  if (qSpaet && p && normText(qSpaet) !== normText(p)) {
    zeilen.push(`Parakeet (live): <span class="alt">${escapeHtml(p)}</span><br>Qwen (spät${spaet.auth ? "" : ", nicht autoritativ"}): <b>${escapeHtml(qSpaet)}</b>`);
  }
  if (k && k.textVorher && k.text && normText(k.textVorher) !== normText(k.text)) {
    zeilen.push(`Korrigiert vor dem Hirn: <span class="alt">${escapeHtml(k.textVorher)}</span> → <b>${escapeHtml(k.text)}</b>`);
  } else if (k && k.vorzug && k.qwenVorher) {
    zeilen.push(`Vorzug für den vorigen Zug: <span class="alt">${escapeHtml(k.parakeetVorher || "")}</span> → <b>${escapeHtml(k.qwenVorher)}</b>${k.verlauf ? " (Verlauf umgeschrieben)" : ""}`);
  }
  if (!zeilen.length) return null;
  const d = document.createElement("div");
  d.className = "ohr-detail";
  d.innerHTML = zeilen.join("<br>");
  return d;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// --------------------------------------------------------------------------- //
// DIALOG_CONTROLLER: Schattenlauf des neuen Kerns je Zug (nur Anzeige).
// Die Felder kommen additiv aus tools/kern_replay.py und beruehren den
// Anruf-Pfad NICHT. Fehlen sie, wird nichts gezeigt.
// --------------------------------------------------------------------------- //
const _KERN_FRAGE = {
  besuchsgrund: "Besuchsgrund", wunschzeit: "Wunschzeit", behandler: "Behandler",
  nachname: "Nachname", vorname: "Vorname", versicherung: "Versicherung",
  terminwahl: "Terminwahl", telefon: "Telefonnummer",
};

function kernBeschreibung(d) {
  if (!d || typeof d !== "object") return "";
  if (d.frage_id) return "fragt " + (_KERN_FRAGE[d.frage_id] || d.frage_id);
  if (d.tool) return "Werkzeug " + d.tool;
  if (d.hangup) return "legt auf" + (d.grund ? " (" + d.grund + ")" : "");
  if (d.akt) {
    const a = String(d.akt).toLowerCase();
    if (a.includes("ruecklese") || a.includes("rücklese")) return "liest zur Kontrolle zurück";
    if (a.includes("bestaet") || a.includes("bestät")) return "bestätigt";
    if (a.includes("abschluss") || a.includes("terminal")) return "schließt ab";
    return d.akt;
  }
  if (d.naechste) return String(d.naechste);
  return "";
}

function kernReplayZeile(z) {
  const kr = z && z.kernReplay;
  const ls = z && z.liveSignal;
  if (!kr && !ls) return null;
  const box = document.createElement("div");
  box.className = "kern-zeile";
  const teile = [];
  if (kr && kr.in) {
    let s = "<b>Neuer Kern:</b> " + escapeHtml(kernBeschreibung(kr.in));
    for (const nw of kr.nach_werkzeug || []) {
      s += " → " + escapeHtml(kernBeschreibung(nw)) +
        (nw.outcome ? ` <span class="alt">[${escapeHtml(nw.outcome)}${nw.synth ? ", synth" : ""}]</span>` : "");
    }
    teile.push(s);
  }
  if (kr && kr.divergenz) {
    teile.push(
      `<span class="kern-div">↯ abweichend:</span> Live fragte „${escapeHtml(kr.divergenz.live)}“, ` +
      `Kern „${escapeHtml(kr.divergenz.kern)}“`
    );
  }
  if (ls && ls.i1) {
    teile.push(`<span class="kern-warn">⚠ Live fragt bereits erfasstes Feld</span> (${escapeHtml(ls.i1.frage)})`);
  }
  if (ls && ls.schleife) {
    teile.push(`<span class="kern-warn">⚠ Live-Schleife</span> (${escapeHtml(ls.schleife.frage)} ${ls.schleife.n}×)`);
  }
  if (!teile.length) return null;
  box.innerHTML = teile.join("<br>");
  return box;
}

function kernSummaryBox(a) {
  const s = a && a.kernReplaySummary;
  if (!s) return null;
  const d = document.createElement("div");
  d.className = "zeiten kern-summary";
  d.style.marginTop = "8px";
  const probleme = (Number(s.i1) || 0) + (Number(s.schleifen) || 0);
  d.innerHTML =
    `<b>Schattenlauf neuer Dialogkern</b> · Anliegen erkannt: <b>${escapeHtml(s.intent || "?")}</b>` +
    ` (${escapeHtml(s.intent_quelle || "?")}) · ${s.anrufer_zuege || 0} Anrufer-Züge<br>` +
    `Live-Probleme: <b>${probleme}</b> (Frage zu erfasstem Feld: ${s.i1 || 0}, Schleifen: ${s.schleifen || 0})` +
    ` · Abweichungen Frageführung: <b>${s.divergenzen || 0}</b>` +
    ` · Kern läuft bis Abschluss: <b>${s.kern_terminal ? "ja" : "nein"}</b>`;
  return d;
}

// DIALOG_CONTROLLER: linke Spalte = echtes Gespraech (Live), inkl. Audio,
// STT-Details, Werkzeuge und farbige Live-Warnsignale (I1 / Schleife).
function fuelleLinks(cell, z, sid) {
  const { rein, raus } = zugAudios(sid, z);
  if (z.textIn) {
    const b = bubble("user", z.textIn);
    const m = document.createElement("div");
    m.className = "b-meta";
    m.appendChild(chip(`${mmss(z.offsetMs)}`));
    if (rein.length) m.appendChild(playKnopf(rein, "Anrufer"));
    for (const c of sttChips(z.timings)) m.appendChild(c);
    for (const c of ohrChips(z.stt)) m.appendChild(c);
    b.appendChild(m);
    cell.appendChild(b);
    const det = ohrDetail(z.stt);
    if (det) cell.appendChild(det);
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
    cell.appendChild(b);
  }
  const ls = z.liveSignal;
  if (ls && ls.i1) {
    const w = document.createElement("div");
    w.className = "vmark warn";
    w.textContent = `\u26A0 fragt bereits erfasstes Feld (${ls.i1.frage})`;
    cell.appendChild(w);
  }
  if (ls && ls.schleife) {
    const w = document.createElement("div");
    w.className = "vmark warn";
    w.textContent = `\u26A0 Schleife: „${ls.schleife.frage}“ ${ls.schleife.n}\u00D7`;
    cell.appendChild(w);
  }
  if (z.book && (z.book.ok || z.book.booked)) {
    cell.appendChild(bubble("sys", `Buchung: ${z.book.spoken || z.book.slotIso || "ok"}`));
  }
  for (const t of z.tools || []) cell.appendChild(toolKarte(t));
  if (z.art === "hangup") {
    cell.appendChild(bubble("sys", `Aufgelegt${z.note ? " — Notiz: " + z.note : ""}`));
  }
}

// DIALOG_CONTROLLER: rechte Spalte = Kopie des Gespraechs + Entscheidung des
// neuen Kerns an derselben Stelle. Der entscheidende Unterschied (Divergenz)
// wird farblich markiert.
function fuelleRechts(cell, z) {
  const kr = z.kernReplay;
  if (z.textIn) {
    const b = bubble("user", z.textIn);
    b.classList.add("kopie");
    cell.appendChild(b);
  }
  if (kr && kr.in) {
    const b = document.createElement("div");
    b.className = "kern-bubble";
    let s = kernBeschreibung(kr.in);
    for (const nw of kr.nach_werkzeug || []) {
      s += " \u2192 " + kernBeschreibung(nw) +
        (nw.outcome ? ` [${nw.outcome}${nw.synth ? ", synth" : ""}]` : "");
    }
    b.textContent = "Kern: " + s;
    if (kr.divergenz) {
      b.classList.add("diff");
      cell.appendChild(b);
      const d = document.createElement("div");
      d.className = "vmark diff-note";
      d.textContent = `\u21AF Live fragte „${kr.divergenz.live}“ — Kern „${kr.divergenz.kern}“`;
      cell.appendChild(d);
    } else {
      b.classList.add("gleich");
      cell.appendChild(b);
    }
  } else if (z.text) {
    const b = document.createElement("div");
    b.className = "kern-bubble muted";
    b.textContent = "(keine Kern-Entscheidung an dieser Stelle)";
    cell.appendChild(b);
  }
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

  // W-SUCHFENSTER (14.09.2026): hat die Slot-Suche ueber mehrere Plattform-
  // Seiten geblaettert (20 Zeiten je Aufruf), steht hier der Weg — Request/
  // Response oben sind die der ERSTEN Seite.
  if (Array.isArray(d.seiten) && d.seiten.length > 1) {
    const abs = document.createElement("div");
    abs.className = "tool-abs";
    const lab = document.createElement("b");
    lab.textContent = `Suchfenster: ${d.seiten.length} Seiten`;
    abs.appendChild(lab);
    const v = document.createElement("div");
    v.textContent = d.seiten
      .map((p) => `${p.startDate || "heute"} (${p.n != null ? p.n : "?"})`)
      .join(" → ");
    abs.appendChild(v);
    body.appendChild(abs);
  }

  // W-BUCHUNG-BEWEIS (15.09.2026): welcher Weg die frische Buchung im
  // Kalender bewiesen hat — die Namensliste oder (bei Dubletten) die Akte
  // ueber die patientId. Bei "akte" steht dabei, woran die Namensliste
  // gescheitert ist.
  if (d.verification && typeof d.verification === "object") {
    const ver = d.verification;
    const abs = document.createElement("div");
    abs.className = "tool-abs";
    const lab = document.createElement("b");
    lab.textContent = "Rücklese (read-after-write)";
    abs.appendChild(lab);
    const v = document.createElement("div");
    const teile = [];
    if (ver.ok) {
      teile.push(`bestätigt über ${ver.beweis === "akte" ? "die Akte (patientId)" : "die Namensliste"}`);
      if (ver.namenslisteFehler) teile.push(`Namensliste: ${ver.namenslisteFehler}`);
      if (ver.idCorrected) teile.push("Termin-ID korrigiert");
    } else {
      teile.push(`nicht bestätigt — ${ver.error || "unbekannt"}`);
    }
    if (ver.appointmentId) teile.push(`Termin ${ver.appointmentId}`);
    v.textContent = teile.join(" · ");
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
  const art = istTest(a) ? "Testanruf" : "Praxis-Live";
  zeiten.innerHTML =
    `<b>${anruferName(a)}</b> — ${art} · ${a.zuege ? a.zuege.length : 0} Züge<br>` +
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
  if (a.warteschleife && a.warteschleife.n) {
    const w = document.createElement("div");
    w.className = "zeiten";
    w.style.marginTop = "8px";
    const texte = (a.warteschleife.texte || []).map((t) => `„${t}“`).join(" · ");
    w.textContent = a.warteschleife.aufgelegt
      ? `Warteschleife der Praxis-Telefonanlage: ${a.warteschleife.n} Ansagen gehört, kein Anrufer mehr in der Leitung — Bianca hat aufgelegt. ${texte}`
      : `Ansage der Praxis-Telefonanlage gehört (${a.warteschleife.n}x, nicht als Anrufer gewertet). ${texte}`;
    wurzel.appendChild(w);
  }
  const kernBox = kernSummaryBox(a);
  if (kernBox) wurzel.appendChild(kernBox);

  // Zwei Spalten: links das echte Gespraech, rechts die Kopie mit den
  // Entscheidungen des neuen Kerns; der entscheidende Unterschied farbig.
  const hatKern = (a.zuege || []).some((z) => z.kernReplay || z.liveSignal);
  const verg = document.createElement("div");
  verg.className = "vergleich";
  const hL = document.createElement("div");
  hL.className = "vkopf";
  hL.textContent = "Echtes Gespräch (Live)";
  const hR = document.createElement("div");
  hR.className = "vkopf";
  hR.textContent = hatKern ? "Neuer Dialogkern (Schatten)" : "Neuer Dialogkern (kein Replay vorhanden)";
  verg.appendChild(hL);
  verg.appendChild(hR);
  for (const z of a.zuege || []) {
    const li = document.createElement("div");
    li.className = "vzelle live";
    const re = document.createElement("div");
    re.className = "vzelle kern";
    fuelleLinks(li, z, sid);
    fuelleRechts(re, z);
    if (z.kernReplay && z.kernReplay.divergenz) re.classList.add("diff");
    const ls = z.liveSignal;
    if (ls && (ls.i1 || ls.schleife)) li.classList.add("warn");
    verg.appendChild(li);
    verg.appendChild(re);
  }
  // Ältere Mitschnitte: Tools nur am Manifest-Kopf, nicht je Zug.
  const hatZugTools = (a.zuege || []).some((z) => (z.tools || []).length);
  if (!hatZugTools) {
    for (const t of a.tools || []) {
      const li = document.createElement("div");
      li.className = "vzelle live";
      li.appendChild(toolKarte(t));
      verg.appendChild(li);
      verg.appendChild(document.createElement("div"));
    }
  }
  if (!(a.zuege || []).length && !(a.tools || []).length) {
    const li = document.createElement("div");
    li.className = "vzelle live";
    li.appendChild(bubble("sys", "keine Züge aufgezeichnet"));
    verg.appendChild(li);
    verg.appendChild(document.createElement("div"));
  }
  wurzel.appendChild(verg);
}

/** Anruf-UID aus dem Fragment (#<uid>) — der Link der Ergebnisseite.
    Nur echte uuid4-Hex zaehlt, damit kein fremdes Fragment einen Ladeversuch
    auf einen erfundenen Mitschnitt ausloest. */
function sidAusAdresse() {
  const roh = decodeURIComponent(String(location.hash || "").replace(/^#/, "")).trim();
  const h = roh.replace(/-/g, "").toLowerCase();
  return /^[0-9a-f]{32}$/.test(h) ? h : "";
}

async function oeffne(sid) {
  aktivId = sid;
  // Adresse mitschreiben: die Seite ist damit teilbar und der Rueckweg aus
  // der Ergebnisseite landet wieder auf demselben Gespraech.
  if (sidAusAdresse() !== String(sid || "").replace(/-/g, "").toLowerCase()) {
    try { history.replaceState(null, "", `#${sid}`); } catch { /* */ }
  }
  maleListe();
  stoppTon();
  try {
    const r = await fetch(`api/anrufe/${sid}`);
    const d = await r.json();
    if (d && d.ok) {
      const tag = anrufTag(d.anruf);
      if (datumFilter && tag && datumFilter !== tag) {
        datumSchreiben(tag);
        maleListe();
      }
      maleDetail(d.anruf);
    }
  } catch {
    $("detail").innerHTML = '<div class="leer">Anruf ließ sich nicht laden</div>';
  }
}

function sichtbare() {
  return anrufe.filter((a) => {
    if (!imDatum(a)) return false;
    if (artFilter === "test") return istTest(a);
    if (artFilter === "live") return !istTest(a);
    return true;
  });
}

function tagEingabeSync() {
  const el = $("tag-filter");
  if (!el) return;
  el.max = heuteTag();
  const soll = datumFilter || "";
  if (el.value !== soll) el.value = soll;
}

function filterZeichnen() {
  const imTag = anrufe.filter(imDatum);
  const nAlle = imTag.length;
  const nTest = imTag.filter(istTest).length;
  const nLive = nAlle - nTest;
  if ($("n-alle")) $("n-alle").textContent = nAlle ? `(${nAlle})` : "";
  if ($("n-test")) $("n-test").textContent = nTest ? `(${nTest})` : "";
  if ($("n-live")) $("n-live").textContent = nLive ? `(${nLive})` : "";
  document.querySelectorAll("#art-filter [data-art]").forEach((b) => {
    b.classList.toggle("an", b.getAttribute("data-art") === artFilter);
  });
  const heute = heuteTag();
  if ($("tag-heute")) $("tag-heute").classList.toggle("an", datumFilter === heute);
  if ($("tag-alle")) $("tag-alle").classList.toggle("an", !datumFilter);
  tagEingabeSync();
}

function leerText() {
  const wo = datumFilter ? ` am ${tagSprechbar(datumFilter)}` : "";
  if (artFilter === "test") return `keine Testanrufe${wo || " in dieser Praxis"}`;
  if (artFilter === "live") return `keine Praxis-Live-Anrufe${wo || " in dieser Praxis"}`;
  if (wo) return `keine Mitschnitte${wo}`;
  return "noch keine Mitschnitte — einfach bei Bianca anrufen";
}

function maleListe() {
  filterZeichnen();
  const wurzel = $("liste");
  wurzel.innerHTML = "";
  const liste = sichtbare();
  if (!liste.length) {
    wurzel.innerHTML = `<div class="leer">${leerText()}</div>`;
    return;
  }
  for (const a of liste) {
    const test = istTest(a);
    const e = document.createElement("div");
    e.className = "eintrag" + (a.id === aktivId ? " aktiv" : "") + (test ? " test" : "");
    const [text, farbe] = ergebnis(a);
    const kopf = document.createElement("div");
    kopf.className = "e-kopf";
    const name = document.createElement("span");
    name.className = test ? "name-test" : "";
    name.textContent = anruferName(a);
    const marken = document.createElement("span");
    marken.className = "e-marken";
    const artMarke = document.createElement("span");
    artMarke.className = "marke " + (test ? "test" : "live");
    artMarke.textContent = test ? "Test" : "Live";
    marken.appendChild(artMarke);
    const marke = document.createElement("span");
    marke.className = `marke ${farbe}`;
    marke.textContent = text;
    marken.appendChild(marke);
    if (a.warteschleife && a.warteschleife.n) {
      // W-WARTESCHLEIFE: die Praxis-Anlage hat den Anrufer zurueckgeholt —
      // Bianca hoerte Ansagen statt eines Menschen (und legte ggf. auf).
      const ws = document.createElement("span");
      ws.className = "marke grau";
      ws.title = (a.warteschleife.texte || []).join(" | ");
      ws.textContent = a.warteschleife.aufgelegt
        ? `Warteschleife (${a.warteschleife.n} Ansagen, aufgelegt)`
        : `Warteschleife (${a.warteschleife.n})`;
      marken.appendChild(ws);
    }
    kopf.appendChild(name);
    kopf.appendChild(marken);
    const meta = document.createElement("div");
    meta.className = "e-meta";
    meta.textContent = `${zeit(a.startedAt)} · ${a.dauerMs != null ? mmss(a.dauerMs) + " min" : "offen"} · ${a.zuege} Züge`;
    e.appendChild(kopf);
    e.appendChild(meta);
    e.onclick = () => oeffne(a.id);
    wurzel.appendChild(e);
  }
  // Verlinktes Gespraech ins Bild holen: bei 100+ Mitschnitten liegt der
  // markierte Eintrag sonst weit unterhalb des sichtbaren Bereichs.
  const markiert = wurzel.querySelector(".eintrag.aktiv");
  if (markiert) {
    try { markiert.scrollIntoView({ block: "nearest" }); } catch { /* */ }
  }
}

async function ladeListe() {
  try {
    const t = (typeof praxisLesen === "function" && praxisLesen()) || "";
    if (!Object.keys(tenantAliase).length) {
      try {
        const td = await (await fetch("api/tenants", { cache: "no-store" })).json();
        (td.tenants || []).forEach((x) => {
          tenantAliase[x.id] = [
            x.id, x.clientId, x.locationId, ...(x.aliases || []),
          ].filter(Boolean);
        });
      } catch { /* lokale ID bleibt nutzbar */ }
    }
    const erlaubt = new Set(tenantAliase[t] || [t]);
    const qs = t ? ("?tenant=" + encodeURIComponent(t)) : "";
    const r = await fetch("api/anrufe" + qs);
    const d = await r.json();
    anrufe = ((d && d.anrufe) || []).filter((a) => {
      if (!t) return true;
      const tid = a.tenantId || "";
      return erlaubt.has(tid);
    });
  } catch {
    anrufe = [];
  }
  maleListe();
}

function filterBinden() {
  document.querySelectorAll("#art-filter [data-art]").forEach((b) => {
    b.addEventListener("click", () => {
      artSchreiben(b.getAttribute("data-art") || "alle");
      maleListe();
    });
  });
  const tag = $("tag-filter");
  if (tag) {
    tag.addEventListener("change", () => {
      datumSchreiben(tag.value || "");
      maleListe();
    });
  }
  if ($("tag-heute")) {
    $("tag-heute").addEventListener("click", () => {
      datumSchreiben(heuteTag());
      maleListe();
    });
  }
  if ($("tag-alle")) {
    $("tag-alle").addEventListener("click", () => {
      datumSchreiben("");
      maleListe();
    });
  }
}

/** Verlinktes Gespraech oeffnen (Ergebnisseite -> Anrufuebersicht). Der
    Art-Filter geht dafuer auf "alle": ein Testanruf war sonst ausgeblendet
    und der Eintrag fehlte in der Liste, obwohl der Mitschnitt existiert.
    Der Datumsfilter springt auf den Tag des Gespraechs, sonst waere ein
    aelterer Link hinter "Heute" unsichtbar. */
function adresseFolgen() {
  const sid = sidAusAdresse();
  if (!sid || sid === aktivId) return;
  if (artFilter !== "alle") { artSchreiben("alle"); }
  const a = anrufe.find((x) => String(x.id || "").replace(/-/g, "").toLowerCase() === sid);
  if (a) {
    const tag = anrufTag(a);
    if (tag && datumFilter !== tag) datumSchreiben(tag);
  } else if (datumFilter) {
    datumSchreiben("");
  }
  oeffne(sid);
}

$("neuLaden").onclick = () => { ladeListe(); if (aktivId) oeffne(aktivId); };
artFilter = artLesen();
datumFilter = datumLesen();
filterBinden();
window.addEventListener("hashchange", adresseFolgen);
if (typeof praxisSeiteStart === "function") {
  praxisSeiteStart({ onchange: () => ladeListe() }).then(ladeListe).then(adresseFolgen);
} else {
  ladeListe().then(adresseFolgen);
}
