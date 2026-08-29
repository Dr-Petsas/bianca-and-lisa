const $ = (id) => document.getElementById(id);

// Alle Server-Pfade RELATIV aufloesen: die Seite laeuft direkt (Port 8096,
// Basis "/") UND hinter Lisas Durchreiche (Basis "/bianca/"). Absolute
// Pfade wie "/api/audio/..." aus Server-Antworten werden hier umgebogen.
function apiUrl(p) {
  return p && p.startsWith("/") ? p.slice(1) : p;
}
let sessionId = "";
let callOn = false;
let micStream = null;
let rec = null;
// Browser-Live-Transkription ist bei Bianca RAUS (Chef 28.08.2026): sie
// lieferte kaputte Transkripte und machte die Züge lahm. Bianca hört nur
// noch über Aufnahme + Server-STT. liveOhr bleibt als immer-null-Feld,
// damit bargeOderCap strukturgleich mit Lisas Dock bleibt (hatOhr = false
// => bewährter Mikro-Pegel-Pfad für Barge-in).
const liveOhr = null;
let kiSpricht = false;
let zugBusy = false;
let hoerNr = 0;
// Stille-Wächter (Chef 27.08.2026): ~4 s Funkstille => Bianca stupst selbst
// an — mit Stand (Auftrag, was schon da ist, was fehlt) statt stumm zu
// warten. Max. 2 Stupse in Folge; echtes Gehörtes setzt den Zähler zurück.
const STILLE_MS = 4000;
let stilleStupse = 0;

function bubble(role, text) {
  if (!text) return;
  const el = document.createElement("div");
  el.className = `bubble ${role}`;
  el.textContent = text;
  $("live").appendChild(el);
  $("live").scrollTop = $("live").scrollHeight;
}

function maleProtokoll(call, writeLive) {
  const z = (call && call.zuege) || [];
  for (const ein of z) {
    if (!ein || ein.art === "hangup") continue;
    if (ein.textIn) bubble("user", ein.textIn);
    if (ein.text) bubble("ki", ein.text);
    if (ein.book) zeigeBuch(ein.book, writeLive);
  }
}

function meld(text, schlecht) {
  $("status").textContent = text || "";
  $("status").className = "status" + (schlecht ? " bad" : "");
  const t = $("toast");
  if (!t) return;
  if (!text) { t.hidden = true; t.textContent = ""; return; }
  t.hidden = false;
  t.textContent = text;
}

function phase(art, text) {
  $("call").classList.remove("ki", "du", "warte");
  if (art) $("call").classList.add(art);
  $("phase").textContent = text;
}

async function unlockAudio() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return;
  if (!unlockAudio.ctx) unlockAudio.ctx = new AC();
  if (unlockAudio.ctx.state === "suspended") await unlockAudio.ctx.resume();
}

function lautsprecher() {
  const a = $("speaker");
  a.setAttribute("playsinline", "");
  a.setAttribute("webkit-playsinline", "");
  a.playsInline = true;
  return a;
}

function stopVoice() {
  const a = lautsprecher();
  try { a.pause(); } catch { /* */ }
  try { a.removeAttribute("src"); a.load(); } catch { /* */ }
  try { if (playUrl._src) playUrl._src.stop(); } catch { /* */ }
  playUrl._src = null;
  // Falls die Wiedergabe gerade im Verdachts-Stopp hing: Kontext wieder
  // freigeben, sonst bleibt die NÄCHSTE Antwort stumm.
  try {
    if (unlockAudio.ctx && unlockAudio.ctx.state === "suspended") unlockAudio.ctx.resume();
  } catch { /* */ }
  kiSpricht = false;
}

// Mikro-Pegelwächter: erkennt echtes Reinsprechen auch OHNE Spracherkennung
// (iOS/Safari) — die Echo-Unterdrückung filtert Biancas eigene Stimme heraus.
let micWache = null;
function micWacheStarten() {
  if (!micStream || !unlockAudio.ctx) return;
  try {
    const src = unlockAudio.ctx.createMediaStreamSource(micStream);
    const an = unlockAudio.ctx.createAnalyser();
    an.fftSize = 512;
    src.connect(an);
    const buf = new Uint8Array(an.fftSize);
    micWache = {
      rms() {
        an.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        return Math.sqrt(sum / buf.length);
      },
      stop() { try { src.disconnect(); } catch { /* */ } },
    };
  } catch { micWache = null; }
}

function bargeOderCap(dauerMs) {
  // Nebengeräusch-Schutz (Chef 27.08.): Pegel allein bricht NICHT mehr ab.
  // Bei Pegel-Verdacht wird nur PAUSIERT; kommen binnen ~1,4 s echte Wörter
  // (Live-STT), ist es ein Einwurf => Stopp. Sonst spricht sie an derselben
  // Stelle weiter. Nur Geräte OHNE Live-STT (iOS) stoppen weiter direkt —
  // dafür deutlich konservativer (~400 ms anhaltender Pegel).
  return new Promise((done) => {
    let start = performance.now();
    let laut = 0;
    let pauseSeit = 0;
    const hatOhr = () => !!(liveOhr && liveOhr.ok);
    const pausieren = () => {
      try { if (unlockAudio.ctx && playUrl._src) unlockAudio.ctx.suspend(); } catch { /* */ }
      try { const a = lautsprecher(); if (a.src && !a.paused) a.pause(); } catch { /* */ }
    };
    const weiter = () => {
      try { if (unlockAudio.ctx && unlockAudio.ctx.state === "suspended") unlockAudio.ctx.resume(); } catch { /* */ }
      try { const a = lautsprecher(); if (a.src && a.paused) a.play(); } catch { /* */ }
    };
    const tick = () => {
      if (!kiSpricht || !callOn) { if (pauseSeit) weiter(); return done("stop"); }
      const jetzt = performance.now();
      if (!pauseSeit && jetzt - start > dauerMs) return done("cap");
      if (hatOhr() && liveOhr.text().length >= 2) {
        stopVoice();
        return done("barge");
      }
      if (pauseSeit) {
        if (jetzt - pauseSeit > 1400) {
          start += jetzt - pauseSeit; // Pausenzeit zählt nicht aufs Zeitlimit
          pauseSeit = 0;
          laut = 0;
          weiter();
        }
      } else if (micWache && jetzt - start > 350) {
        laut = micWache.rms() > (hatOhr() ? 0.06 : 0.09) ? laut + 1 : 0;
        if (hatOhr() && laut >= 4) {
          pauseSeit = jetzt; // nur anhalten — Abbruch erst bei echten Wörtern
          pausieren();
        } else if (!hatOhr() && laut >= 8) {
          stopVoice();
          return done("barge");
        }
      }
      setTimeout(tick, 50);
    };
    tick();
  });
}

async function playUrl(url) {
  if (!url || !callOn) return;
  url = apiUrl(url);
  await unlockAudio();
  kiSpricht = true;
  const ctx = unlockAudio.ctx;
  const wav = /\.wav(\?|$)/i.test(url);
  // Audio-Chunk-Streaming (Phase 2, 29.08.2026): /api/audio-stream/ liefert
  // einen WACHSENDEN WAV — decodeAudioData bräuchte die ganze Datei und
  // würde bis zum Synthese-Ende warten. Das <audio>-Element unten spielt
  // progressiv, der erste Ton kommt nach der Container-TTFA.
  const streamend = url.includes("/api/audio-stream/");
  if (ctx && !streamend) {
    try {
      if (ctx.state === "suspended") await ctx.resume();
      const raw = await fetch(url).then((r) => r.arrayBuffer());
      const decoded = await ctx.decodeAudioData(raw.slice(0));
      const src = ctx.createBufferSource();
      const g = ctx.createGain();
      // WAV wird serverseitig auf einheitlichen Spitzenpegel normalisiert —
      // Zusatz-Gain würde wieder übersteuern ("Kompressor"-Pumpen 27.08.2026).
      // Demo-Clara-Parität (Chef 27.08.2026): KEIN Browser-Gain — WAVs kommen
      // serverseitig auf Demo-Pegel, der Jingle (MP3) ist fertig gemastert.
      g.gain.value = 1.0;
      src.buffer = decoded;
      src.connect(g).connect(ctx.destination);
      playUrl._src = src;
      const ended = new Promise((done) => { src.onended = () => done("end"); });
      src.start();
      await Promise.race([ended, bargeOderCap((decoded.duration || 12) * 1000 + 200)]);
      try { src.stop(); } catch { /* */ }
      playUrl._src = null;
      kiSpricht = false;
      return;
    } catch {
      playUrl._src = null;
    }
  }
  const a = lautsprecher();
  try { a.pause(); } catch { /* */ }
  a.volume = 1;
  a.src = url;
  const ended = new Promise((done) => {
    const fertig = () => { a.onended = null; a.onerror = null; done("end"); };
    a.onended = fertig;
    a.onerror = fertig;
  });
  try {
    await a.play();
  } catch {
    kiSpricht = false;
    return;
  }
  const d = a.duration;
  // Stream-WAV meldet keine Dauer (Infinity) — Deckel weiter fassen, sonst
  // schneidet der Cap lange Angebots-Sätze nach 12 s ab.
  const limit = (d && isFinite(d) && d > 0) ? d * 1000 + 200 : (streamend ? 30000 : 12000);
  await Promise.race([ended, bargeOderCap(limit)]);
  kiSpricht = false;
}

async function leseZug(r, onFiller) {
  const out = { sessionId: "", textIn: "", text: "", audioUrl: "", book: null, writeLive: false, timings: {}, empty: false, error: "" };
  if (!r.ok && !r.body) {
    throw new Error("Antwort fehlgeschlagen");
  }
  const ctype = (r.headers.get("content-type") || "").toLowerCase();
  if (ctype.includes("json") && !ctype.includes("ndjson")) {
    Object.assign(out, await r.json());
    return out;
  }
  const reader = r.body && r.body.getReader ? r.body.getReader() : null;
  if (!reader) {
    Object.assign(out, await r.json());
    return out;
  }
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      let ev;
      try { ev = JSON.parse(line); } catch { continue; }
      if (ev.type === "session") out.sessionId = ev.sessionId || "";
      if (ev.type === "empty") {
        out.empty = true;
        out.error = ev.error || "";
      }
      if (ev.type === "transcript" && ev.textIn) out.textIn = ev.textIn;
      if (ev.type === "filler" && ev.audioUrl && onFiller) {
        // Überbrückungssatz SOFORT abspielen — die echte Antwort kommt gleich nach.
        try { onFiller(ev.audioUrl); } catch { /* */ }
      }
      if (ev.type === "reply") {
        out.text = ev.text || "";
        out.book = ev.book;
        out.writeLive = ev.writeLive;
        out.error = ev.error || "";
        if (ev.audioUrl) out.audioUrl = ev.audioUrl;
        if (ev.timings) out.timings = ev.timings;
        if (ev.textIn && !out.textIn) out.textIn = ev.textIn;
        if (ev.sessionId) out.sessionId = ev.sessionId;
        if (ev.empty) out.empty = true;
      }
      if (ev.type === "audio") {
        out.audioUrl = ev.audioUrl || "";
        out.timings = ev.timings || {};
      }
    }
  }
  return out;
}

function mimeType() {
  const opts = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return opts.find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
}

function recordUntilSilence(stream) {
  return new Promise((resolve) => {
    const mime = mimeType();
    const recLocal = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    rec = recLocal;
    const chunks = [];
    recLocal.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    recLocal.onstop = () => {
      rec = null;
      resolve(new Blob(chunks, { type: recLocal.mimeType || mime || "audio/webm" }));
    };
    const AC = window.AudioContext || window.webkitAudioContext;
    const ctx = unlockAudio.ctx || new AC();
    const src = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    src.connect(analyser);
    const buf = new Uint8Array(analyser.fftSize);
    let heard = false;
    let quiet = 0;
    let last = performance.now();
    const t0 = last;
    recLocal.start(250);
    const tick = () => {
      if (!callOn || recLocal.state !== "recording") {
        if (recLocal.state === "recording") recLocal.stop();
        try { src.disconnect(); } catch { /* */ }
        return;
      }
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) {
        const v = (buf[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / buf.length);
      const now = performance.now();
      const dt = now - last;
      last = now;
      if (rms > 0.02) { heard = true; quiet = 0; }
      else if (heard) quiet += dt;
      // 500 ms Ruhe statt 300: nicht in Denkpausen hineinreden (27.08.2026).
      // Ohne jedes Geräusch nach STILLE_MS abbrechen: der Stille-Wächter
      // stupst dann an, statt weitere Sekunden stumm zu warten.
      if ((heard && quiet > 500 && now - t0 > 450) || (!heard && now - t0 > STILLE_MS) || now - t0 > 8000) {
        recLocal.stop();
        try { src.disconnect(); } catch { /* */ }
        return;
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

async function stilleStups(nr) {
  // Nach ~4 s Stille: Server baut den Stups deterministisch (Stand + offene
  // Frage bzw. Talk-Thema). false = kein Stups (Budget leer/Fehler) —
  // dann läuft das normale "Nichts gehört"-Verhalten.
  if (!callOn || nr !== hoerNr || zugBusy || stilleStupse >= 2) return false;
  stilleStupse += 1;
  try {
    const r = await fetch("api/stille", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId }),
    });
    const d = await r.json();
    if (!callOn || nr !== hoerNr) return true;
    if (d.empty || !d.audioUrl) return false;
    if (d.text) bubble("ki", d.text);
    phase("ki", "Bianca spricht …");
    await playUrl(d.audioUrl);
    return true;
  } catch { return false; }
}

async function sendeZug({ text, blob, nr }) {
  if (!callOn || nr !== hoerNr || zugBusy) return;
  zugBusy = true;
  const hatLive = (text || "").split(/\s+/).filter(Boolean).length >= 1 && (text || "").length >= 2;
  phase("warte", hatLive ? "Bianca antwortet …" : "Bianca hört zu …");
  let fillerLauf = null;
  const spielFiller = (url) => {
    if (!callOn || nr !== hoerNr) return;
    phase("ki", "Bianca spricht …");
    // Mehrere Häppchen (Füller, dann Vorab-Satz aus dem LLM-Stream) laufen
    // als Kette nacheinander — nichts überlappt, nichts geht verloren.
    fillerLauf = fillerLauf
      ? fillerLauf.then(() => playUrl(url)).catch(() => {})
      : playUrl(url).catch(() => {});
  };
  try {
    let data;
    if (hatLive) {
      const r = await fetch("api/turn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId, text }),
      });
      data = await leseZug(r, spielFiller);
    } else {
      const fd = new FormData();
      fd.append("sessionId", sessionId);
      fd.append("audio", blob, blob.type.includes("mp4") ? "turn.m4a" : "turn.webm");
      const r = await fetch("api/listen", { method: "POST", body: fd });
      data = await leseZug(r, spielFiller);
    }
    if (fillerLauf) { try { await fillerLauf; } catch { /* */ } }
    if (!callOn || nr !== hoerNr) { zugBusy = false; return; }
    if (data.empty || (!data.textIn && !hatLive && !data.text)) {
      phase("du", "Nichts gehört — bitte nochmal");
      zugBusy = false;
      if (callOn && nr === hoerNr) setTimeout(hoeren, 250);
      return;
    }
    stilleStupse = 0; // echter Zug gehört und beantwortet — Stupse von vorn
    if (data.textIn) bubble("user", data.textIn);
    if (data.text) bubble("ki", data.text);
    if (data.book) zeigeBuch(data.book, data.writeLive);
    const t = data.timings || {};
    if (t.total != null) phase("ki", `Bianca spricht · ${t.total}s`);
    await playUrl(data.audioUrl);
    zugBusy = false;
    if (callOn && nr === hoerNr) hoeren();
  } catch (e) {
    $("status").textContent = String(e.message || e);
    zugBusy = false;
    if (callOn && nr === hoerNr) setTimeout(hoeren, 600);
  }
}

async function hoeren() {
  const nr = hoerNr;
  if (!callOn || !micStream || !sessionId || zugBusy) return;
  phase("du", "Sie sind dran — einfach reden");
  let blob;
  try {
    blob = await recordUntilSilence(micStream);
  } catch (e) {
    $("status").textContent = String(e.message || e);
    if (callOn && nr === hoerNr) setTimeout(hoeren, 400);
    return;
  }
  if (!callOn || nr !== hoerNr) return;
  if (!blob || blob.size < 1200) {
    // Stille-Wächter: nichts gehört — erst anstupsen.
    if (await stilleStups(nr)) {
      if (callOn && nr === hoerNr) hoeren();
      return;
    }
    phase("du", "Nichts gehört — bitte nochmal");
    if (callOn) setTimeout(hoeren, 250);
    return;
  }
  await sendeZug({ text: "", blob, nr });
}

function auflegen() {
  const sid = sessionId;
  callOn = false;
  hoerNr += 1;
  zugBusy = false;
  if (sid) {
    fetch("api/hangup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: sid }),
    }).then((r) => r.json()).then((d) => {
      zeigeLetzten(d.call);
      zeigeStand(d.call);
    }).catch(() => {});
  }
  stopVoice();
  if (micWache) { try { micWache.stop(); } catch { /* */ } micWache = null; }
  try { const a = lautsprecher(); a.removeAttribute("src"); a.load(); } catch { /* */ }
  if (rec && rec.state === "recording") try { rec.stop(); } catch { /* */ }
  if (micStream) {
    for (const t of micStream.getTracks()) t.stop();
    micStream = null;
  }
  $("call").classList.remove("open", "ki", "du", "warte");
  document.body.classList.remove("incall");
  $("start").disabled = false;
  $("start").textContent = "Bei Bianca anrufen";
}

async function boot() {
  // Technik-Zeile ist aus der Oberfläche raus (Chef 27.08.2026) —
  // nur bei totem Dienst erscheint eine Warnung.
  try {
    const h = await (await fetch("health")).json();
    zeigeLetzten(h.lastCall);
    zeigeStand(h.lastCall);
    const ti = $("ttsInfo");
    if (ti) {
      const teile = [];
      if (h.ttsEngine) teile.push("Stimme: " + h.ttsEngine);
      if (h.stt) teile.push("Ohr: " + h.stt);
      ti.textContent = teile.join(" · ");
    }
    if (!(h.llm && h.llm.ok)) meld("Sprachmodell offline — Bianca kann nicht antworten.", true);
  } catch {
    meld("Biancas Dienst antwortet nicht.", true);
  }
  const t = await (await fetch("api/tenants")).json();
  $("tenant").innerHTML = (t.tenants || []).map((x) =>
    `<option value="${x.id}" ${x.id === t.default ? "selected" : ""}>${x.praxisName}</option>`
  ).join("");
}

function starteAnruf() {
  meld("");
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    meld("Dieser Browser gibt das Mikrofon nicht frei. Chrome oder Safari.", true);
    return;
  }
  // Sofort im selben Tipp — kein await davor, sonst kommt keine Mikro-Frage.
  const micBitte = navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  weiterNachMic(micBitte);
}

async function weiterNachMic(micBitte) {
  try {
    micStream = await micBitte;
  } catch (e) {
    meld("Mikrofon wurde nicht erlaubt. Nochmal anrufen und im Dialog zustimmen.", true);
    return;
  }
  await unlockAudio();
  micWacheStarten();
  $("start").disabled = true;
  $("start").textContent = "Es klingelt …";
  $("live").innerHTML = "";
  $("call").classList.add("open");
  document.body.classList.add("incall");
  callOn = true;
  hoerNr += 1;
  zugBusy = false;
  stilleStupse = 0;
  phase("warte", "verbindet …");
  try {
    const r = await fetch("api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant: $("tenant").value }),
    });
    if (!r.ok) {
      let msg = "start fehlgeschlagen";
      try {
        const err = await r.json();
        if (typeof err.detail === "string") msg = err.detail;
      } catch { /* */ }
      throw new Error(msg);
    }
    const data = await leseZug(r);
    sessionId = data.sessionId || sessionId;
    if (!sessionId) throw new Error("keine Sitzung");
    if (data.text) bubble("ki", data.text);
    const t = data.timings || {};
    phase("ki", "Bianca spricht" + (t.total != null ? ` · ${t.total}s` : ""));
    await playUrl(data.audioUrl);
    if (callOn) hoeren();
  } catch (e) {
    meld(String(e.message || e), true);
    auflegen();
  }
}

$("start").onclick = () => starteAnruf();

$("hang").onclick = auflegen;

function zeigeBuch(book, writeLive) {
  if (!book) return;
  if (book.dryRun || !book.booked) {
    bubble("sys", writeLive ? "Buchung nicht fest." : "Test: nicht in den Kalender geschrieben, keine SMS.");
    return;
  }
  bubble("sys", "Fest im Kalender: " + (book.slotIso || "Termin"));
}

function zeigeStand(call) {
  const el = $("stand");
  if (!el) return;
  const s = (call && call.sammler) || null;
  if (!s || (!s.nachname && !s.grund && !s.telefon)) {
    el.textContent = "noch kein Anruf";
    return;
  }
  const teile = [];
  if (s.vorname || s.nachname) teile.push(`Name: ${[s.vorname, s.nachname].filter(Boolean).join(" ")}${s.buchstabiert ? " (buchstabiert)" : ""}`);
  if (s.warSchonMal != null) teile.push(s.warSchonMal ? "schon Patient" : "Neupatient");
  if (s.arzt) teile.push(`Arzt: ${s.arzt}`);
  if (s.grund) teile.push(`Grund: ${s.grund}`);
  if (s.telefon) teile.push(`Handy: ${s.telefon}`);
  if (s.phase) teile.push(`Phase: ${s.phase}`);
  el.textContent = teile.join(" · ");
}

function zeigeLetzten(call) {
  const el = $("lastCall");
  if (!el) return;
  if (!call || !call.sessionId) {
    el.textContent = "Letzter Anruf: noch keiner bei dieser Bianca.";
    return;
  }
  const b = call.lastBook;
  const teile = [];
  if (b) teile.push(b.booked ? "FEST gebucht" : (b.dryRun ? "Buchung nur Test" : "nicht gebucht"));
  if (call.lastCancel) teile.push(call.lastCancel.dryRun ? "Absage nur Test" : "abgesagt");
  if (call.lastMove) teile.push(call.lastMove.dryRun ? "Verschieben nur Test" : "verschoben");
  if (call.lastNote) teile.push(call.lastNote.dryRun ? "Notiz nur Test" : "Notiz im Termin");
  el.textContent = `Letzter Anruf: ${call.patientName || "ohne Name"} · ${teile.join(" · ") || "kein Kalender-Werkzeug"}`;
}

boot();
