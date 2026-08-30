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
// W-TEMPO (29.08.2026): Ruhe-Schwelle fürs Zugende — der Server sagt nach
// jedem Zug, was er erwartet (350 ms nach Ja/Nein-/Wahlfragen, 650 ms beim
// Ziffern-Diktat, sonst 500). Ohne Ansage bleibt der bewährte Default.
let stilleSoll = 500;
let stilleStupse = 0;
// Barge-in mit Fortsetzung (W-BARGE 29.08.2026): beim Reinsprechen merkt sich
// das Dock, WELCHES Audio bei WIE VIEL ms gestoppt wurde, spielt sofort eine
// vorgewärmte Quittung ("Hm."/"Okay.") und meldet beides mit dem nächsten Zug
// an den Server — der reagiert auf den Einwand und fährt danach fort, wo
// Bianca stehengeblieben ist. Fehlalarm (nichts gesagt) => api/weiter.
let bargeInfo = null;
let quittungen = [];
let quittungNr = 0;

function bargeMerken(url, ms) {
  bargeInfo = { url, ms: Math.max(0, Math.round(ms || 0)) };
  // Sofort-Quittung: hörbar aufhören und den Floor abgeben.
  if (!quittungen.length) return;
  const a = quittungen[quittungNr++ % quittungen.length];
  try { a.currentTime = 0; a.play().catch(() => {}); } catch { /* */ }
}

// W-STILLE (Chef 29.08.2026): Nach dem Sprechende des Anrufers darf NIE mehr
// als ~1,4 s Stille herrschen — es darf nie das Gefühl entstehen, die KI sei
// abgestürzt. Zweite Verteidigungslinie hinter den Server-Füllern: lokale,
// beim Boot als BLOB geladene Warte-Ansagen. Sie spielen über ein EIGENES
// Audio-Objekt (die playUrl-Kette bleibt unberührt) und verstummen, sobald
// die echte Antwort loslegt. Blobs spielen auch bei hängendem Server.
const WACHT_MS = 1400;
const WACHT_MAX = 3;
let notfall = [];
let wachtTimer = null;
let wachtAudio = null;

function wachtStopp() {
  if (wachtTimer) { clearInterval(wachtTimer); wachtTimer = null; }
  if (wachtAudio) { try { wachtAudio.pause(); } catch { /* */ } wachtAudio = null; }
}

function wachtStart(nr) {
  wachtStopp();
  if (!notfall.length) return;
  let tRuhe = performance.now();
  let zahl = 0;
  wachtTimer = setInterval(() => {
    if (!callOn || nr !== hoerNr) return wachtStopp();
    if (kiSpricht) {
      // Echter Ton (Füller/Antwort) läuft — eigene Ansage sofort räumen.
      if (wachtAudio) { try { wachtAudio.pause(); } catch { /* */ } wachtAudio = null; }
      tRuhe = performance.now();
      return;
    }
    if (wachtAudio) {
      if (!wachtAudio.ended && !wachtAudio.paused) { tRuhe = performance.now(); return; }
      wachtAudio = null;
      tRuhe = performance.now();
      return;
    }
    if (performance.now() - tRuhe < WACHT_MS) return;
    if (zahl >= WACHT_MAX) return wachtStopp();
    // Eskalation: erst "Einen kleinen Moment", zuletzt "bleiben Sie dran".
    const a = new Audio(notfall[Math.min(zahl, notfall.length - 1)]);
    zahl += 1;
    wachtAudio = a;
    a.play().catch(() => { wachtAudio = null; });
  }, 150);
}

function wachtNot() {
  // Hörbarer Fehlerfall (Netz/Server weg): die ehrliche letzte Ansage —
  // losgelöst vom Timer, damit der nächste Anlauf sie nicht abwürgt.
  if (!notfall.length) return;
  try { new Audio(notfall[notfall.length - 1]).play().catch(() => {}); } catch { /* */ }
}

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
  // W-STILLE: beim Reinsprechen verstummt auch die lokale Warte-Ansage.
  wachtStopp();
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

function bargeOderCap(dauerMs, barge) {
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
        if (barge) bargeMerken(barge.url, barge.pos ? barge.pos() : 0);
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
          // Position VOR dem Stopp ablesen — stopVoice() leert die Quelle.
          if (barge) bargeMerken(barge.url, barge.pos ? barge.pos() : 0);
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
  // Nach einem Barge nichts mehr abspielen (auch keine nachlaufende
  // Füller-Kette oder frisch eingetroffene Antwort) — erst wenn der
  // nächste Zug die Unterbrechung an den Server gemeldet hat.
  if (!url || !callOn || bargeInfo) return;
  // Für die Barge-Meldung zählt der ORIGINAL-Pfad aus der Server-Antwort —
  // der Server vergleicht ihn mit seiner Satz-Karte.
  const urlOrig = url;
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
      const t0 = ctx.currentTime;
      src.start();
      await Promise.race([ended, bargeOderCap((decoded.duration || 12) * 1000 + 200,
        { url: urlOrig, pos: () => (ctx.currentTime - t0) * 1000 })]);
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
  await Promise.race([ended, bargeOderCap(limit, { url: urlOrig, pos: () => (a.currentTime || 0) * 1000 })]);
  kiSpricht = false;
}

async function leseZug(r, onFiller) {
  const out = { sessionId: "", textIn: "", text: "", audioUrl: "", book: null, writeLive: false, timings: {}, empty: false, error: "", hangup: false, warte: false, stilleMs: 0 };
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
      if (ev.type === "warte") {
        // Halbsatz-Wache: Satz klingt unfertig — still weiterhören.
        out.warte = true;
        if (ev.stilleMs) out.stilleMs = ev.stilleMs;
      }
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
        if (ev.hangup) out.hangup = true;
        if (ev.stilleMs) out.stilleMs = ev.stilleMs;
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
    const blobTyp = () => recLocal.mimeType || mime || "audio/webm";
    // W-TEMPO Vorab-STT: ab 200 ms Ruhe geht der bisherige Stand schon zur
    // Transkription — die restliche Wartezeit bis zum Zugende überlappt mit
    // dem STT. Spricht der Anrufer doch weiter, wird das Vorab verworfen.
    let vorabWunsch = false;
    let vorabLauf = null;
    recLocal.ondataavailable = (e) => {
      if (e.data && e.data.size) chunks.push(e.data);
      if (vorabWunsch && !vorabLauf && chunks.length) {
        vorabLauf = vorabStt(new Blob(chunks, { type: blobTyp() }));
      }
    };
    recLocal.onstop = () => {
      rec = null;
      resolve({
        blob: new Blob(chunks, { type: blobTyp() }),
        vorab: vorabWunsch ? vorabLauf : null,
      });
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
      if (rms > 0.02) {
        heard = true; quiet = 0;
        // Wieder Sprache: ein laufendes Vorab ist wertlos — verwerfen,
        // bei der nächsten Ruhephase startet ein frisches mit mehr Audio.
        if (vorabWunsch) { vorabWunsch = false; vorabLauf = null; }
      }
      else if (heard) quiet += dt;
      if (heard && quiet > 200 && !vorabWunsch) {
        vorabWunsch = true;
        // Sofortiger Chunk-Flush, damit das Vorab auch das letzte Wortende
        // trägt (sonst hinge es am 250-ms-Raster des Recorders).
        try { recLocal.requestData(); } catch { /* */ }
      }
      // Adaptive Ruhe-Schwelle (stilleSoll, Server-Ansage) statt fix 500 ms:
      // nicht in Denkpausen hineinreden (27.08.2026), aber nach Ja/Nein-
      // Fragen nicht unnötig warten. Ohne jedes Geräusch nach STILLE_MS
      // abbrechen: der Stille-Wächter stupst dann an.
      if ((heard && quiet > stilleSoll && now - t0 > 450) || (!heard && now - t0 > STILLE_MS) || now - t0 > 8000) {
        recLocal.stop();
        try { src.disconnect(); } catch { /* */ }
        return;
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

async function vorabStt(blob) {
  // W-TEMPO: reines Vorab-Ohr (api/hoeren) — Server transkribiert mit den
  // Tenant-Hotwords des echten Zugs. Leer/Fehler => Audio-Weg wie bisher.
  try {
    const fd = new FormData();
    fd.append("sessionId", sessionId);
    fd.append("audio", blob, blob.type.includes("mp4") ? "vorab.m4a" : "vorab.webm");
    const r = await fetch("api/hoeren", { method: "POST", body: fd });
    const d = await r.json();
    return d && d.ok ? (d.text || "") : "";
  } catch { return ""; }
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
    if (d && d.stilleMs) stilleSoll = d.stilleMs;
    if (d.empty || !d.audioUrl) return false;
    // Halbsatz-Flush: der Stups beantwortet ein gehaltenes Satz-Fragment —
    // dann gehört der Anrufer-Satz auch in den Verlauf.
    if (d.textIn) bubble("user", d.textIn);
    if (d.text) bubble("ki", d.text);
    phase("ki", "Bianca spricht …");
    await playUrl(d.audioUrl);
    return true;
  } catch { return false; }
}

async function sendeZug({ text, blob, nr }) {
  if (!callOn || nr !== hoerNr || zugBusy) return;
  zugBusy = true;
  // W-BARGE: die gemerkte Unterbrechung wandert mit DIESEM Zug zum Server
  // (der stutzt sein Protokoll und hält den ungesprochenen Rest bereit).
  const barge = bargeInfo;
  bargeInfo = null;
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
    if (hatLive && blob) {
      // W-MITSCHNITT: auch der Vorab-TEXT-Zug (W-TEMPO) schickt die
      // Aufnahme mit — der Server nutzt weiter den Text (kein zweites STT),
      // archiviert aber das Anrufer-Audio für die Anrufliste (/anrufe).
      const fd = new FormData();
      fd.append("sessionId", sessionId);
      fd.append("text", text);
      fd.append("bargeUrl", barge ? barge.url : "");
      fd.append("bargeMs", String(barge ? barge.ms : 0));
      fd.append("audio", blob, blob.type.includes("mp4") ? "turn.m4a" : "turn.webm");
      const r = await fetch("api/listen", { method: "POST", body: fd });
      data = await leseZug(r, spielFiller);
    } else if (hatLive) {
      const r = await fetch("api/turn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId, text, bargeUrl: barge ? barge.url : "", bargeMs: barge ? barge.ms : 0 }),
      });
      data = await leseZug(r, spielFiller);
    } else {
      const fd = new FormData();
      fd.append("sessionId", sessionId);
      fd.append("bargeUrl", barge ? barge.url : "");
      fd.append("bargeMs", String(barge ? barge.ms : 0));
      fd.append("audio", blob, blob.type.includes("mp4") ? "turn.m4a" : "turn.webm");
      const r = await fetch("api/listen", { method: "POST", body: fd });
      data = await leseZug(r, spielFiller);
    }
    if (fillerLauf) { try { await fillerLauf; } catch { /* */ } }
    if (data && data.stilleMs) stilleSoll = data.stilleMs;
    if (!callOn || nr !== hoerNr) { zugBusy = false; return; }
    if (data.warte) {
      // Halbsatz-Wache: der Satz klingt unfertig (Denkpause) — Bianca
      // schweigt bewusst und hört mit längerer Ruhe-Schwelle weiter; der
      // nächste Zug wird serverseitig an das Fragment angefügt.
      wachtStopp();
      phase("du", "… Sie sprechen — Bianca hört weiter zu");
      zugBusy = false;
      if (callOn && nr === hoerNr) hoeren();
      return;
    }
    if (bargeInfo && data.audioUrl && bargeInfo.url !== data.audioUrl) {
      // Reinsprecher während Füller/Vorab: die frische Antwort NICHT mehr
      // abspielen — sie gilt als bei null unterbrochen, der Server holt sie
      // im nächsten Zug als Rest zurück (bargeMs 0).
      bargeInfo = { url: data.audioUrl, ms: 0 };
    }
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
    if (data.hangup) { auflegen(); return; }
    if (callOn && nr === hoerNr) hoeren();
  } catch (e) {
    $("status").textContent = String(e.message || e);
    // W-STILLE: ein Netz-/Serverfehler darf nicht stumm bleiben — die
    // ehrliche "bleiben Sie dran"-Ansage spielt lokal aus dem Blob.
    wachtStopp();
    wachtNot();
    zugBusy = false;
    if (callOn && nr === hoerNr) setTimeout(hoeren, 600);
  }
}

async function bargeWeiter(nr) {
  // W-BARGE-Fehlalarm: reingesprochen, aber nichts Verwertbares gesagt —
  // Bianca spricht an der Unterbrechungsstelle weiter (Server: api/weiter,
  // deterministisch, ohne LLM). false = nichts fortzusetzen.
  const b = bargeInfo;
  bargeInfo = null;
  if (!callOn || nr !== hoerNr || zugBusy || !b) return false;
  try {
    const r = await fetch("api/weiter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId, bargeUrl: b.url, bargeMs: b.ms }),
    });
    const d = await r.json();
    if (d && d.stilleMs) stilleSoll = d.stilleMs;
    if (!callOn || nr !== hoerNr) return true;
    if (d.empty || !d.audioUrl) return false;
    if (d.text) bubble("ki", d.text);
    phase("ki", "Bianca spricht …");
    await playUrl(d.audioUrl);
    return true;
  } catch { return false; }
}

async function hoeren() {
  const nr = hoerNr;
  if (!callOn || !micStream || !sessionId || zugBusy) return;
  // W-STILLE: solange der Anrufer dran ist, wacht niemand — Stille gehört ihm.
  wachtStopp();
  phase("du", "Sie sind dran — einfach reden");
  let blob;
  let vorab = null;
  try {
    const auf = await recordUntilSilence(micStream);
    blob = auf.blob;
    vorab = auf.vorab;
  } catch (e) {
    $("status").textContent = String(e.message || e);
    if (callOn && nr === hoerNr) setTimeout(hoeren, 400);
    return;
  }
  if (!callOn || nr !== hoerNr) return;
  if (!blob || blob.size < 1200) {
    // W-BARGE-Fehlalarm: Unterbrechung ohne Einwand — weiterreden.
    if (bargeInfo && await bargeWeiter(nr)) {
      if (callOn && nr === hoerNr) hoeren();
      return;
    }
    // Stille-Wächter: nichts gehört — erst anstupsen.
    if (await stilleStups(nr)) {
      if (callOn && nr === hoerNr) hoeren();
      return;
    }
    phase("du", "Nichts gehört — bitte nochmal");
    if (callOn) setTimeout(hoeren, 250);
    return;
  }
  // W-STILLE: ab dem Sprechende zählt die Stille-Uhr — bis zum ersten Ton
  // der Antwort dürfen nie mehr als ~1,4 s vergehen, sonst spricht die
  // lokale Warte-Ansage.
  wachtStart(nr);
  // W-TEMPO: liegt das Vorab-Transkript rechtzeitig vor, geht der Zug als
  // TEXT raus (STT ist dann schon bezahlt); sonst wie bisher als Audio.
  let vorabText = "";
  if (vorab) {
    vorabText = await Promise.race([
      vorab,
      new Promise((r) => setTimeout(() => r(""), 700)),
    ]) || "";
  }
  await sendeZug({ text: vorabText, blob, nr });
}

function auflegen() {
  const sid = sessionId;
  callOn = false;
  hoerNr += 1;
  zugBusy = false;
  bargeInfo = null;
  wachtStopp();
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
  try {
    // W-BARGE: Sofort-Quittungen vorladen, damit sie beim Stopp ohne
    // Netz-Umweg spielen.
    const q = await (await fetch("api/quittung")).json();
    quittungen = (q.urls || []).map((u) => { const a = new Audio(apiUrl(u)); a.preload = "auto"; return a; });
  } catch { /* */ }
  try {
    // W-STILLE: Notfall-Ansagen als BLOB vorladen — sie spielen auch dann
    // noch, wenn der Server hängt oder das Netz weg ist.
    const n = await (await fetch("api/notfall")).json();
    const urls = [];
    for (const u of (n.urls || [])) {
      const b = await (await fetch(apiUrl(u))).blob();
      urls.push(URL.createObjectURL(b));
    }
    notfall = urls;
  } catch { /* */ }
  const t = await (await fetch("api/tenants")).json();
  $("tenant").innerHTML = (t.tenants || []).map((x) =>
    `<option value="${x.id}" ${x.id === t.default ? "selected" : ""}>${x.praxisName}</option>`
  ).join("");
}

function starteAnruf() {
  meld("");
  $("koennen").hidden = true; // Schaufenster zu, sobald es ernst wird
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
  stilleSoll = 500;
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
  if (call.praxisNotiz) teile.push(`NOTIZ an Praxis: ${call.praxisNotiz}`);
  el.textContent = `Letzter Anruf: ${call.patientName || "ohne Name"} · ${teile.join(" · ") || "kein Kalender-Werkzeug"}`;
}

// ---------------------------------------------------------------------------
// "Das kann ich" (Chef 29.08.2026): Schaufenster mit zwei Reitern — Koennen
// (alles, was Bianca fachlich kann) und Technik (Ohr/Hirn/Mund-Pipelines plus
// ALLE Patches/Fixes/Upgrades tabellarisch, exakte Kuerzel). Reine Anzeige,
// kein Einfluss auf den Anruf-Pfad. Bei neuen Features/Patches HIER mitpflegen.

const KOENNEN = [
  { t: "Terminverwaltung — der Kern", p: [
    "<b>Buchen:</b> Termine fest in den echten Praxiskalender (Neupatient wie Bestand), inklusive Bestätigungs-SMS der Praxis.",
    "<b>Behandler-Wahl zu Beginn:</b> Dr. Petsas, Dr. Patrikis oder Dr. Nikolaou — „egal“ sucht global den schnellsten Termin.",
    "<b>Finden &amp; ansagen:</b> „Wann ist mein Termin?“ → Bianca liest ihn vor und bietet gleich Verschieben oder Absagen an.",
    "<b>Absagen (Sammel-Prozedur):</b> erst „Wann ist der Termin?“, bei „weiß nicht mehr“ die Behandler-Frage, dann der Name — bestätigt wird mit Anrede: „Soll ich den Termin wirklich absagen, Herr Berger?“ Versteht alle Sprech-Formen: absagen, stornieren, löschen, streichen, canceln, „fällt aus“, „nicht wahrnehmen“ — und startet nach einem Fehlversuch sauber neu, statt am alten Stand zu kleben.",
    "<b>Verschieben:</b> gleiche Such-Prozedur; alter Termin und neuer Wunsch werden sauber getrennt.",
    "<b>Mehrere Treffer:</b> Eingrenzen über die Behandlung, dann klare Auswahl-Liste.",
    "<b>Nicht gefunden:</b> ehrliche Ansage plus echte Praxis-Notiz — „das wird Doktor X vorgelegt“ — und im MAS entsteht ein Rückruf-Vorgang.",
    "<b>Behandlungsgrund erkennen:</b> Schmerzen/Notfall, Kontrolle, PZR, Füllung, Überweisung … — Dringend-Fälle bekommen den nächstmöglichen Platz.",
    "<b>Rückblick auf den Vortermin:</b> ist der letzte Besuch in der Kartei gefunden, spricht Bianca ihn an („Ihr letzter Besuch ist … her — da ging es um …“) — mit Verlaufs-Frage passend zur damaligen Behandlung (verheilt? zufrieden? Zahn ruhig?).",
    "<b>Zahnreinigung mit anbieten:</b> sobald der Vortermin gefunden ist, bietet Bianca die professionelle Zahnreinigung zum Mitbuchen an — nie bei Schmerz-/Notfall-Terminen, nie wenn der Termin selbst die Reinigung ist, nie wenn gerade erst eine war. Die Zusage steht als „PLUS PZR heute“ in der Terminnotiz.",
  ]},
  { t: "Patientenakte & Kartei", p: [
    "<b>Akte anlegen:</b> Vorname, Nachname, Handynummer, Geschlecht und Versichertenstatus gehen als neue Patientenakte ins System.",
    "<b>Geschlecht am Vornamen erkennen</b> (Vornamen-Wächter mit kuratierten Listen) und <b>geschlechtsspezifisch ansprechen:</b> „Frau Müller“ / „für Herrn Müller“ — grammatisch gebeugt.",
    "<b>Kartei schlägt Schätzung:</b> steht das Geschlecht in der Akte, gilt die Akte; bleibt ein Vorname unklar, kommt die Termin-Notiz „Bitte Geschlecht aktualisieren“.",
    "<b>Versichertenstatus (privat/gesetzlich)</b> erfragen und in die Kartei eintragen: Neupatienten als Pflichtfrage, Bestand nach über sechs Monaten als kurze Rückfrage — ein Wechsel geht sofort in die Akte.",
    "<b>Handynummer mit Ziffern-Rückbestätigung:</b> das Readback ist immer deterministisch — nie „aus dem Bauch“.",
    "<b>Buchstabierte Namen</b> verstehen und festhalten.",
    "<b>Kartei-Suche im Hintergrund,</b> während das Gespräch normal weiterläuft: schon Patient? Letzter Besuch? Bei welchem Behandler?",
  ]},
  { t: "Praxisgedächtnis (MAS-Brain) & Notizen", p: [
    "<b>Gesprächs-Report nach jedem Anruf:</b> Zusammenfassung im Terminpopup-Stil ins MAS-Praxisgedächtnis („Laut Anruf (Bianca): …“).",
    "<b>Kontext aus Vorbehandlung holen — im Hintergrund:</b> frühere Anrufe und Kontakte werden während des Gesprächs abgefragt; Rückrufer werden erkannt, statt bei Null anzufangen.",
    "<b>Terminnotiz im Termin:</b> „telefonisch Termin vereinbart wegen … // Bianca“ — direkt im Terminpopup sichtbar.",
    "<b>Besonderes automatisch heraushören</b> und notieren: Angst, Allergie, Begleitung, „bitte nur vormittags“ …",
    "<b>Offene Anliegen als Vorgang:</b> nicht gefundene Termine oder Rückruf-Wünsche landen als offenes Ticket bei der Praxis.",
    "<b>Anrufliste mit Mitschnitt:</b> jedes Gespräch liegt unter „Anrufe“ im Browser — Transkript als Blasen, Audio je Zug (Anrufer UND Bianca), alle Zeiten (Uhrzeit, Offset, stt/llm/tts je Zug), Buchungs-Ergebnis und Praxis-Notiz.",
  ]},
  { t: "Gesprächsführung", p: [
    "<b>Smalltalk &amp; Abschweifen:</b> Nebenthemen bekommen Raum (Talk-Schicht) — danach führt genau EINE Brücke zurück zur offenen Frage.",
    "<b>Unterbrechen erlaubt (Barge-in):</b> sofort „Hm.“/„Okay.“, auf den Einwand eingehen — und dann weitersprechen, wo sie stehen geblieben ist. „Stopp“ gilt sofort.",
    "<b>Halbsätze:</b> klingt ein Satz unfertig, wartet Bianca kurz und fügt die Teile zusammen, statt Halbes zu beantworten.",
    "<b>Stille-Stups:</b> nach ~4 Sekunden Funkstille meldet sie sich selbst — mit dem Stand und der offenen Frage.",
    "<b>Nie-Stille-Garantie:</b> nie mehr als ~1,5 Sekunden Schweigen (Füller, Nachschub, lokale Notfall-Ansagen im Dock).",
    "<b>Wiederholungs-Wächter:</b> nie zweimal wortgleich dieselbe Frage.",
    "<b>Praxiswissen:</b> Öffnungszeiten, Anfahrt, Leistungen und Preise — nur aus dem hinterlegten Wissen, nichts wird erfunden.",
    "<b>Weiterleiten ans Behandlungsteam:</b> „Kann ich Doktor Petsas sprechen?“ / „Ich möchte verbunden werden“ — Ansage, Verbinden-Jingle, durchstellen; versteht auch Hörfehler („Petzers“) und Formen ohne Titel („Herrn Petsas sprechen“). Mitarbeiter-Wünsche (Empfang, Buchhaltung, Chef) bekommen ehrlich die Personalfrei-Auskunft plus Arzt-Angebot.",
    "<b>Anrufer-Tempo:</b> die Hör-Schwelle passt sich der Frage an — Ja/Nein: flott, Nummern-Diktat: geduldig.",
    "<b>Sprech-Qualität:</b> Uhrzeiten und Daten in gesprochenen Worten („morgen, Mittwoch, um neun Uhr fünfzehn“) — nie Datums-Kürzel.",
  ]},
];

const TECHNIK = [
  { t: "Ohr — STT-Pipeline (hören)", p: [
    "<b>Engine:</b> primeline-parakeet — deutsches Parakeet-TDT-Finetune (2,95 % Wort-Fehlerrate) als ONNX, CPU-only im eigenen Container (5090:8212). Gemessen: 0,34–0,44 s je Zug.",
    "<b>Whisper-GPU-Vorstufe (W-STT-WHISPER):</b> ist STT_WHISPER_BASE gesetzt, hört zuerst Whisper large-v3 auf der Dev-GPU (Stream-Container über Tailscale); fällt der Dev-Rechner aus, übernimmt Parakeet automatisch (30-s-Pause statt Connect-Timeout je Zug) — nie ElevenLabs.",
    "<b>Stille-Trim (W-STT-TRIM):</b> Vor-/Nachlauf-Stille wird vor der Inferenz energie-basiert abgeschnitten — „Ja“/„Nein“ gehen nicht mehr unter, reine Stille wird verworfen statt halluziniert.",
    "<b>Fuzzy-Nachkorrektur</b> (Claras bewährte Strecke): Anlaut-Gruppen P/B und T/D/Z, Token-Paare, Behandler-Namen als Hotwords („Betsas“ → „Petsas“).",
    "<b>Vorab-STT (W-TEMPO):</b> ab 200 ms Ruhe wird schon transkribiert — die Rest-Stille überlappt mit der Erkennung; adaptive Ruhe-Schwelle je Fragetyp: 350 ms nach Ja/Nein-Fragen, 1500 ms Diktat-Geduld bei Nummern (W-STT-SCHWANZ), sonst 500 ms.",
    "<b>Echo-Wache:</b> das Lautsprecher-Echo der eigenen Stimme wird erkannt und verworfen — kurze echte Antworten („ja“, „nein“, „stopp“) nie.",
  ]},
  { t: "Hirn — LLM-Pipeline (verstehen & entscheiden)", p: [
    "<b>Modell:</b> Qwen 3.6 35B-A3B auf vLLM (5090:8000, Prefix-Cache) — ein Container für alle Stimmen des Hauses.",
    "<b>Zwei Schichten:</b> die deterministische Job-Maschine hält Termine, Namen und Nummern; die Talk-Schicht redet frei bei Nebenthemen (Gravity + Rückweg-Brücke).",
    "<b>Satz-Deckel (P2):</b> der Stream schließt hart nach zwei Sätzen plus Frage — nichts Abgehacktes.",
    "<b>Satzweises Streaming (P5):</b> jeder fertige Satz wird sofort vertont, während das Modell weiterschreibt.",
    "<b>Wachen um jeden Zug:</b> Fakten kommen aus Werkzeugen (Kalender, Kartei, Wissen), nie aus dem Bauch — Halbsatz-, Wiederholungs-, Buchungs- und Nachbesserungs-Wachen.",
  ]},
  { t: "Mund — TTS-Pipeline (sprechen)", p: [
    "<b>Engine:</b> Qwen3-TTS 0.6B-Base Hybrid — Triton-Kerne + CUDA-Graph (5090:8213), mit <b>Zero-Shot-Voice-Cloning:</b> Biancas Stimme entsteht aus EINER Referenz-Aufnahme, ohne Training.",
    "<b>Audio-Chunk-Streaming (Phase 2):</b> der ganze Satz geht ans TTS, PCM-Stücke kommen sofort zurück — erster Ton nach ~0,2 s statt 0,6–2,3 s Voll-Render. Kein Text-Schnitt (Genuschel-Verbot).",
    "<b>Ziffern-Sicherheit:</b> Zahlwort-Ketten gehen als Einzelziffern an die Engine; der Nachhör-Wächter (Parakeet) hört jedes Nummern-Readback gegen, BEVOR es der Anrufer hört.",
    "<b>Warm-Kette:</b> Füller-Platten-Cache (Dienststart ~2 s statt ~60 s), Satz-Pinning im RAM (feste Fragen ~0,0 s), Warm-Abnahme per Gegenhören, Pausen-Straffung, RMS-Pegel-Angleich.",
  ]},
  { t: "Gedächtnis & Kalender (Werkzeuge)", p: [
    "<b>MAS-Praxisgedächtnis:</b> Gesprächs-Reports (/brain/events) + Anrufer-Kontext (/brain/caller-context) — im Hintergrund, nie blockierend.",
    "<b>Pickadoc-Cloud-Functions:</b> Patientensuche, Terminsuche, Buchung, Absage, Verschieben, Versichertenstatus, Terminnotizen — echter Kalender (WRITE_LIVE).",
    "<b>Alles Wesentliche lokal:</b> STT, LLM und TTS laufen auf eigener Hardware (5090) — keine Cloud-Sprachdienste im Gesprächspfad.",
  ]},
];

// Exakte Kuerzel wie in AGENTS.md — [Patch/Fix, Stand, Bereich, Wirkung].
const PATCHES = [
  ["Job+Talk-Schichten", "27.08.", "Gespräch", "Deterministische Termin-Maschine + freie Talk-Schicht mit Gravity; zurück führt genau eine Brücke."],
  ["Wiederholungs-Wächter", "27.08.", "Gespräch", "Pflichtfragen nie wortgleich doppelt; Varianten tragen die Kern-Wörter, Readbacks bleiben unangetastet."],
  ["Stille-Wächter (Stups)", "27.08.", "Gespräch", "~4 s Funkstille → Bianca meldet Stand + offene Frage; max. 2 Stupse in Folge."],
  ["Lokales TTS (Shootout)", "27.08.", "Mund", "Umschalten per TTS_BASE, bewusst OHNE Cloud-Rückfall — Fehler müssen in der Testphase hörbar sein."],
  ["Füller-Platten-Cache", "28.08.", "Mund", "Statische Sätze als WAV auf Platte; Dienststart ~2 s statt ~60 s."],
  ["Satz-Pinning", "28.08.", "Mund", "Feste Fragen im gepinnten RAM (~0,0 s statt 1–2 s); mehrsätzige Antworten satzweise gefügt — ein WAV, keine Naht."],
  ["Lokales STT (Parakeet)", "28.08.", "Ohr", "primeline-parakeet ONNX/CPU im Container (8212): 0,34–0,44 s je Zug statt 0,8–2,0 s Cloud-STT."],
  ["Ziffern-Transformation", "28.08.", "Mund", "Zahlwort-Ketten gehen als Einzelziffern an die Engine — Readback 5/5 statt 1/5."],
  ["Nachhör-Wächter", "28.08.", "Mund", "Parakeet hört jedes Ziffern-Audio gegen (max. 3 Würfe); nur Verifiziertes erreicht den Anrufer."],
  ["Warm-Abnahme", "28.08.", "Mund", "Gegenhören beim Vorwärmen: Babble fliegt raus, der bessere Wurf wird gepinnt."],
  ["Neustart Mitternacht", "28.08.", "Alle", "Rücksetzer auf den Gesprächs-Stand 02:18 („weltklasse“); Genuschel-Ära ausgebaut."],
  ["Qwen3-TTS Hybrid", "29.08.", "Mund", "0.6B-Base mit Triton-Kernen + CUDA-Graph (8213); Ziffern-Probe 5/5."],
  ["Audio-Chunk-Streaming (Phase 2)", "29.08.", "Mund", "PCM-Stücke ab dem Codec: erster Ton ~0,2 s statt 0,6–2,3 s Voll-Render; Readbacks bleiben blocking."],
  ["W-STT-TRIM", "29.08.", "Ohr", "Stille-Trim vor der Inferenz: „Ja“/„Nein“ gehen nicht mehr unter (Probe 13/13); Retry-Guard für onnx-asr."],
  ["W-TEMPO", "29.08.", "Ohr", "Adaptive Ruhe-Schwelle (350/650 ms) + Vorab-STT ab 200 ms Ruhe: −150 bis −550 ms je Zug."],
  ["W-HALBSATZ", "29.08.", "Gespräch", "Unfertige Sätze halten und serverseitig fügen; Termin-Auskunft statt Zwangs-Buchung."],
  ["W-BARGE", "29.08.", "Gespräch", "Sofort-Quittung, Einwand beantworten, dann fortsetzen an der Unterbrechungsstelle; „Stopp“ verwirft."],
  ["W-SAMMELN", "29.08.", "Termine", "Absagen/Verschieben: erst Wann → Behandler → Name sammeln, DANN suchen; ehrliche Praxis-Notiz mit Rückruf-Vorgang."],
  ["W-STILLE", "29.08.", "Gespräch", "Nie länger als ~1,5 s still: Füller-Nachschub + Dock-Watchdog mit lokalen Blob-Ansagen."],
  ["W-GEDAECHTNIS", "29.08.", "Gedächtnis", "Gesprächs-Reports ins MAS-Brain + Anrufer-Kontext im Hintergrund; offene Anliegen als Vorgang."],
  ["Versicherung + Vornamen-Wächter", "29.08.", "Akte", "privat/gesetzlich in die Kartei (Wechsel sofort); Geschlecht am Vornamen, Anrede gebeugt."],
  ["Behandler-Wahl", "29.08.", "Termine", "Kalender-Klärung zu Gesprächsbeginn; „egal“ = global schnellster Termin."],
  ["Rückblick + PZR-Mitbuchung", "29.08.", "Termine", "Vortermin wird angesprochen (Verlaufs-Frage je Behandlung); Zahnreinigung zum Mitbuchen, sobald der Vortermin gefunden ist — Zusage als „PLUS PZR heute“ in der Terminnotiz."],
  ["Motiv-Mapping je Behandler", "29.08.", "Termine", "Besuchsgrund wird je Anruf frisch gegen den Katalog des Ziel-Behandlers aufgelöst (calendarIds, online-buchbare zuerst)."],
  ["Politik-Leitplanke", "29.08.", "Gespräch", "Bei Politik/Krieg/Religion keine Meinung — kurz Verständnis zeigen, zurück zum Anliegen; Fußball-Smalltalk bleibt willkommen."],
  ["Überweiser- & Praxis-Wissen", "29.08.", "Wissen", "Dr. Grüger/Dr. Lange (Schlaflabor → Narval-Schiene), Invisalign vor Schlafschiene, Ratenzahlung/Taxi-Auskunft ohne Zusagen."],
  ["Wächter-Spur", "29.08.", "Technik", "Jede Antwort trägt sichtbar, welche Wache eingegriffen hat (Halbsatz, Barge, Wiederholung, Stups, Talk-Floor …)."],
  ["Baukasten-Testfabrik", "29.08.", "Technik", "~40 Satz-Bausteine × 10 Formulierungen + 8 Anrufer-Stimmklone rendern echte Test-Anrufe gegen die komplette Pipeline."],
  ["W-VERBINDEN", "29.08.", "Gespräch", "Verbinde-Wunsch in allen Formen deterministisch („mit Doktor X verbunden?“, „ich möchte verbunden“, Name ohne Titel, „Chef ans Telefon“) → Jingle statt LLM-Ablehnung; Prompt-Leitplanke gegen erfundene Absagen."],
  ["W-ABSAGE-NEUSTART", "29.08.", "Termine", "Absage-Varianten breit (stornieren, löschen, streichen, canceln, „fällt aus“ …); nach erledigtem/gescheitertem Anliegen startet ein neuer Wunsch die Sammel-Prozedur frisch, nach „nicht gefunden“ wird der (oft verhörte) Name neu erfragt."],
  ["P1 Readback-Parallelisierung", "29.08.", "Mund", "Dreisatz-Readback: Vorsatz sofort aus dem Pin-Cache, Ziffern-Satz parallel gerendert und verifiziert."],
  ["P2 Satz-Deckel", "29.08.", "Hirn", "LLM-Stream schließt hart nach zwei Sätzen plus Frage — nichts Abgehacktes."],
  ["P5 Satzweises LLM→TTS", "29.08.", "Hirn/Mund", "Jeder fertige Satz wird sofort vertont, während der Stream weiterliest — URLs in Reihenfolge."],
  ["P4 Speculative Decoding", "29.08.", "Hirn", "Geprüft und bewusst NICHT aktiv: kein freier VRAM neben TTS (30,5/32,6 GB belegt)."],
  ["Pausen-Straffung", "29.08.", "Mund", "Gewärmte Renders: Anlauf 120 ms, Satzpausen 350 ms, Ausklang 250 ms — Sprache bleibt Sample-identisch."],
  [".env-BOM-Fix", "29.08.", "Betrieb", "PowerShell-BOM schaltete WRITE_LIVE still aus; Config liest jetzt utf-8-sig."],
  ["W-SIP (AudioSocket-Brücke)", "29.08.", "Telefon", "Echte Anrufe: Zaluma → Asterisk → AudioSocket über SSH-Rücktunnel → sip_bridge (pickadoc1) → Bianca-API; Barge-in, Stille-Stups und Auflegen wie im Dock."],
  ["W-SIP-RAUSCH (Leitungs-VAD)", "29.08.", "Telefon", "Adaptiver Rauschteppich statt starrer RMS-Schwelle: Telefon-Grundrauschen löst keinen falschen Barge mehr aus; Dauer-Stille-Rahmen halten den Medienstrom am Leben."],
  ["W-MITSCHNITT (Anrufliste)", "30.08.", "Betrieb", "Jeder Anruf als Ordner unter .data/anrufe (Manifest + Audio je Zug, sofort geschrieben); Browser-Seite /anrufe mit Transkript, Abspiel-Knöpfen und allen Zeiten. Notaus: MITSCHNITT=0."],
  ["Anruf-Download (ein WAV)", "30.08.", "Betrieb", "Knopf \"Audio herunterladen\" auf /anrufe: der Server fügt alle Züge (Anrufer + Bianca, Gesprächsreihenfolge, 250 ms Pause) zu EINER WAV-Datei — api/anrufe/<sid>/download."],
  ["W-SIP-KURZJA (kurze Antworten)", "30.08.", "Telefon", "Ein kurzes lautes \"Ja\" zählt jetzt als Zug (Kurz-aber-laut-Ausnahme statt 240-ms-Deckel), und die Echo-Sperre klingt nach Biancas Sprechende ab statt 800 ms hart zu blocken."],
  ["W-STUDIO-5090 (Test-Studio auf dem Server)", "30.08.", "Technik", "Das Baukasten-Studio läuft auch auf pickadoc1 (…:8096/studio): eigener Editor- und Test-Bianca-Container, Testläufe stören nie die Live-Bianca; Testtermine löschen sich nach 2 h selbst."],
  ["W-SIP-PEGEL (Telefon-Lautheit)", "30.08.", "Telefon", "Biancas Studio-Pegel (−14 dBFS, Peaks am Deckel) klang auf der G.711-Strecke übersteuert — die Brücke dämpft jetzt nur Richtung Asterisk um 6 dB (BRIDGE_GAIN, 1.0 = aus); Docks unverändert."],
  ["W-SIP-ECHO-RAUS (Echo-Sperre aus)", "30.08.", "Telefon", "Die Halbduplex-Echo-Sperre verschluckte echte Antworten (Sprache leiser als die Echo-Referenz) — jetzt default aus; Echo-Transkripte fängt die Text-Wache im Dienst. Rückweg: BRIDGE_ECHO=1."],
  ["W-STT-WHISPER (GPU-Ohr mit Rückfall)", "30.08.", "Ohr", "Whisper large-v3 auf der Dev-GPU hört zuerst (WebSocket-Stream über Tailscale, gleiche Fuzzy-Nachkorrektur); ist der Dev-Rechner weg, übernimmt Parakeet automatisch — nie ElevenLabs. Leer = Parakeet wie bisher."],
  ["W-STT-SCHWANZ (nichts mehr verschluckt)", "30.08.", "Ohr", "Leise Satz-Enden (letzte Ziffern) gingen verloren: Diktat-Geduld 650 → 1500 ms, Hysterese in der Brücken-VAD (leiser Auslauf hält das Zugende offen), Trim-Grenzen im STT-Container über eine zartere Schwelle, Brücken-Vorlauf 300 → 500 ms."],
];

let kTab = "faehig";

function kListe(bloecke) {
  return bloecke.map((b) =>
    `<div class="k-block"><h3>${b.t}</h3><ul>${b.p.map((x) => `<li>${x}</li>`).join("")}</ul></div>`
  ).join("");
}

function kTabelle() {
  const zeilen = PATCHES.map((z) =>
    `<tr><td class="kz">${z[0]}</td><td class="st">${z[1]}</td><td class="br">${z[2]}</td><td>${z[3]}</td></tr>`
  ).join("");
  return `<div class="k-block"><h3>Patches, Fixes &amp; Upgrades — komplett</h3>` +
    `<div class="k-tabelle-wrap"><table class="k-tabelle">` +
    `<thead><tr><th>Patch / Fix</th><th>Stand</th><th>Bereich</th><th>Wirkung</th></tr></thead>` +
    `<tbody>${zeilen}</tbody></table></div></div>`;
}

function kRender() {
  const el = $("kInhalt");
  if (!el) return;
  el.innerHTML = kTab === "technik"
    ? `<div class="k-live" id="kLive">Live-Stand wird geladen …</div>` + kListe(TECHNIK) + kTabelle()
    : kListe(KOENNEN);
  for (const b of document.querySelectorAll(".k-tab")) b.classList.toggle("aktiv", b.dataset.tab === kTab);
  el.scrollTop = 0;
  if (kTab === "technik") kLive();
}

async function kLive() {
  // Live-Zeile aus /health — zeigt, was JETZT wirklich läuft.
  try {
    const h = await (await fetch("health")).json();
    const teile = [];
    if (h.stt) teile.push("Ohr: " + h.stt);
    if (h.ttsEngine) teile.push("Stimme: " + h.ttsEngine);
    teile.push("Hirn: " + (h.llmModel || "LLM") + (h.llm && h.llm.ok ? "" : " — OFFLINE"));
    if (h.gedaechtnis && h.gedaechtnis !== "aus") teile.push("Gedächtnis: an");
    teile.push(h.writeLive ? "Kalender: ECHT (WRITE_LIVE)" : "Kalender: Testmodus");
    const el = $("kLive");
    if (el) el.textContent = "Live: " + teile.join(" · ");
  } catch {
    const el = $("kLive");
    if (el) el.textContent = "Live-Stand nicht abrufbar.";
  }
}

$("koennenBtn").onclick = () => { $("koennen").hidden = false; kRender(); };
$("koennenZu").onclick = () => { $("koennen").hidden = true; };
function studioAuf(titel, pfad) {
  $("studioTitel").textContent = titel;
  $("studioRahmen").src = pfad;
  $("studio").hidden = false;
}
$("studioBtn").onclick = () => studioAuf("Test-Studio", "studio/");
$("ergebnisseBtn").onclick = () => studioAuf("Ergebnisse", "studio/ergebnisse");
$("studioZu").onclick = () => {
  $("studio").hidden = true;
  $("studioRahmen").src = "about:blank";
};
for (const b of document.querySelectorAll(".k-tab")) {
  b.onclick = () => { kTab = b.dataset.tab; kRender(); };
}

boot();
