/* Lisa-Kampagne: Liste, eine Leitung, Transkript + Audio. */
const $ = (id) => document.getElementById(id);

let kampagnen = [];
let aktuell = null;
let tenants = [];
let sessionId = "";
let empfaengerId = "";
let callOn = false;
let micStream = null;
let hoerNr = 0;
let zugBusy = false;

function meld(text, bad) {
  const el = $("status");
  el.textContent = text || "";
  el.classList.toggle("bad", !!bad);
  const t = $("toast");
  if (bad && text) {
    t.hidden = false;
    t.textContent = text;
    setTimeout(() => { t.hidden = true; }, 5000);
  } else t.hidden = true;
}

function pill(st) {
  const s = st || "offen";
  const label = ({
    offen: "offen", laeuft: "läuft", erreicht: "erreicht",
    kein_anschluss: "kein Anschluss", spaeter: "später", skip: "übersprungen",
  })[s] || s;
  return `<span class="st ${s}">${label}</span>`;
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || d.error || r.statusText);
  return d;
}

async function ladeTenants() {
  const d = await api("/api/tenants");
  tenants = d.tenants || [];
  const sel = $("kTenant");
  sel.innerHTML = tenants.map((t) =>
    `<option value="${t.id}">${t.praxisName || t.id}</option>`).join("");
  if (d.default) sel.value = d.default;
}

async function ladeListe() {
  const d = await api("/api/kampagnen");
  kampagnen = d.kampagnen || [];
  const box = $("kampListe");
  box.innerHTML = kampagnen.map((k) =>
    `<button type="button" class="k-item${aktuell && aktuell.id === k.id ? " sel" : ""}" data-id="${k.id}">
      <b>${k.name || "Kampagne"}</b>
      <div class="meta">${k.offen} offen · ${k.anzahl} gesamt · ${k.erreicht} erreicht</div>
    </button>`).join("") || "<div class=\"sub\">Noch keine Kampagne.</div>";
  box.querySelectorAll(".k-item").forEach((b) => {
    b.onclick = () => oeffnen(b.dataset.id);
  });
}

function setAktuell(doc) {
  const calls = (aktuell && aktuell.calls) || [];
  aktuell = doc;
  if (!aktuell.calls) aktuell.calls = calls;
  return aktuell;
}

function formAus(doc) {
  $("kName").value = doc.name || "";
  $("kAuftrag").value = doc.auftrag || "";
  if (doc.tenant) $("kTenant").value = doc.tenant;
}

function zeichneEmpfaenger() {
  const rec = (aktuell && aktuell.empfaenger) || [];
  $("empfaenger").innerHTML = rec.map((e) =>
    `<div class="k-row" data-eid="${e.id}">
      <div><b>${e.name}</b><div class="sub">${e.notiz || ""}</div></div>
      <div>${e.phone}</div>
      <div>${pill(e.status)}${e.sessionId ? ` · <a class="link" href="#call-${e.sessionId}">Gespräch</a>` : ""}</div>
      <button class="btn ghost" type="button" data-del="${e.id}">weg</button>
    </div>`).join("") || "<div class=\"sub\">Liste leer — Zeilen oben einfügen.</div>";
  $("empfaenger").querySelectorAll("[data-del]").forEach((b) => {
    b.onclick = () => weg(b.dataset.del);
  });
}

function zeichneCalls() {
  const calls = (aktuell && aktuell.calls) || [];
  const box = $("calls");
  if (!calls.length) {
    box.innerHTML = "<div class=\"sub\">Noch kein Gespräch in dieser Kampagne.</div>";
    return;
  }
  box.innerHTML = calls.map((c) => {
    const zeilen = (c.transcript || []).map((z) => {
      const wer = z.role === "agent" ? "lisa" : "user";
      const audio = z.audioUrl
        ? `<audio controls preload="none" src="${z.audioUrl}"></audio>` : "";
      return `<div class="bubble ${wer}">${esc(z.message || "")}${audio}</div>`;
    }).join("");
    return `<div class="card" id="call-${c.sessionId}" style="margin-bottom:8px">
      <div><b>${c.patientName || "ohne Name"}</b> · ${c.phone || ""}</div>
      <div class="sub">${c.startedAt || ""} · ${c.outcome || ""} · ${c.summary || ""}</div>
      <div class="k-trans" style="margin-top:8px">${zeilen || "<div class=\"sub\">kein Transkript</div>"}</div>
    </div>`;
  }).join("");
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function oeffnen(id) {
  setAktuell(await api("/api/kampagnen/" + id));
  formAus(aktuell);
  zeichneEmpfaenger();
  zeichneCalls();
  ladeListe();
}

async function neu() {
  const d = await api("/api/kampagnen", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: "Neue Kampagne",
      tenant: $("kTenant").value,
    }),
  });
  await ladeListe();
  await oeffnen(d.id);
}

async function speichern() {
  if (!aktuell) { meld("Erst eine Kampagne anlegen.", true); return; }
  setAktuell(await api("/api/kampagnen/" + aktuell.id, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: $("kName").value,
      auftrag: $("kAuftrag").value,
      tenant: $("kTenant").value,
    }),
  }));
  meld("Gespeichert.");
  ladeListe();
}

async function dazu() {
  if (!aktuell) { meld("Erst eine Kampagne anlegen.", true); return; }
  const liste = $("kPaste").value.trim();
  if (!liste) { meld("Keine Zeilen.", true); return; }
  setAktuell(await api("/api/kampagnen/" + aktuell.id + "/empfaenger", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ liste }),
  }));
  $("kPaste").value = "";
  zeichneEmpfaenger();
  ladeListe();
}

async function weg(eid) {
  if (!aktuell) return;
  setAktuell(await api("/api/kampagnen/" + aktuell.id + "/empfaenger/" + eid, { method: "DELETE" }));
  zeichneEmpfaenger();
  ladeListe();
}

async function mark(eid, status, sid) {
  if (!aktuell) return;
  setAktuell(await api("/api/kampagnen/" + aktuell.id + "/markieren", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ empfaengerId: eid, status, sessionId: sid || "" }),
  }));
  zeichneEmpfaenger();
  ladeListe();
}

function naechsterOffen() {
  return ((aktuell && aktuell.empfaenger) || []).find((e) => (e.status || "offen") === "offen");
}

function phase(art, text) {
  $("phase").textContent = text || "";
  $("call").classList.remove("lisa", "du", "warte");
  if (art) $("call").classList.add(art);
}

function bubble(wer, text) {
  if (!text) return;
  const d = document.createElement("div");
  d.className = "bubble " + wer;
  d.textContent = text;
  $("live").appendChild(d);
  $("live").scrollTop = $("live").scrollHeight;
}

async function unlockAudio() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return;
  if (!unlockAudio.ctx) unlockAudio.ctx = new AC();
  if (unlockAudio.ctx.state === "suspended") await unlockAudio.ctx.resume();
}

function stopLisaVoice() {
  const a = $("speaker");
  try { a.pause(); } catch { /* */ }
  try { a.removeAttribute("src"); a.load(); } catch { /* */ }
  try { if (playUrl._src) playUrl._src.stop(); } catch { /* */ }
  playUrl._src = null;
  try {
    if (unlockAudio.ctx && unlockAudio.ctx.state === "suspended") unlockAudio.ctx.resume();
  } catch { /* */ }
}

async function playUrl(url) {
  if (!url || !callOn) return;
  await unlockAudio();
  const ctx = unlockAudio.ctx;
  const streamend = url.includes("/api/audio-stream/");
  if (ctx && !streamend) {
    try {
      if (ctx.state === "suspended") await ctx.resume();
      const raw = await fetch(url).then((r) => r.arrayBuffer());
      const decoded = await ctx.decodeAudioData(raw.slice(0));
      const src = ctx.createBufferSource();
      src.buffer = decoded;
      src.connect(ctx.destination);
      playUrl._src = src;
      const ended = new Promise((done) => { src.onended = () => done(); });
      src.start();
      await ended;
      playUrl._src = null;
      return;
    } catch {
      playUrl._src = null;
    }
  }
  const a = $("speaker");
  try { a.pause(); } catch { /* */ }
  a.volume = 1;
  a.src = url;
  try {
    await a.play();
  } catch {
    meld("Ton blockiert — Gespräch starten noch einmal tippen.", true);
    return;
  }
  await new Promise((res) => {
    a.onended = res;
    a.onerror = res;
  });
}

async function leseZug(r, onFiller) {
  const out = { sessionId: "", textIn: "", text: "", audioUrl: "", empty: false, hangup: false };
  if (!r.ok && !r.body) throw new Error("Antwort fehlgeschlagen");
  const ctype = (r.headers.get("content-type") || "").toLowerCase();
  if (ctype.includes("json") && !ctype.includes("ndjson")) {
    Object.assign(out, await r.json());
    return out;
  }
  const reader = r.body && r.body.getReader ? r.body.getReader() : null;
  if (!reader) {
    try { Object.assign(out, await r.json()); } catch { /* */ }
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
      if (ev.type === "session" || ev.sessionId) out.sessionId = ev.sessionId || out.sessionId;
      if (ev.type === "transcript" && ev.textIn) out.textIn = ev.textIn;
      if (ev.type === "filler" && ev.audioUrl && onFiller) {
        try { onFiller(ev.audioUrl); } catch { /* */ }
      }
      if (ev.type === "reply") {
        out.text = ev.text || "";
        out.audioUrl = ev.audioUrl || out.audioUrl;
        out.hangup = !!ev.hangup;
        if (ev.sessionId) out.sessionId = ev.sessionId;
        if (ev.textIn && !out.textIn) out.textIn = ev.textIn;
      }
      if (ev.type === "audio") out.audioUrl = ev.audioUrl || "";
      if (ev.type === "empty") out.empty = true;
    }
  }
  return out;
}

function recMime() {
  const opts = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  for (const m of opts) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

function aufnehmen() {
  return new Promise((resolve) => {
    const mime = recMime();
    const rec = new MediaRecorder(micStream, mime ? { mimeType: mime } : undefined);
    const chunks = [];
    rec.ondataavailable = (ev) => { if (ev.data && ev.data.size) chunks.push(ev.data); };
    rec.onstop = () => resolve(new Blob(chunks, { type: rec.mimeType || mime || "audio/webm" }));
    rec.start(200);
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const src = ac.createMediaStreamSource(micStream);
    const an = ac.createAnalyser();
    an.fftSize = 512;
    src.connect(an);
    const data = new Uint8Array(an.fftSize);
    let heard = false;
    let quiet = 0;
    const t0 = performance.now();
    const tick = () => {
      if (!callOn || rec.state !== "recording") return;
      an.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / data.length);
      if (rms > 0.02) { heard = true; quiet = 0; }
      else if (heard) quiet += 16;
      const now = performance.now();
      if ((heard && quiet > 700 && now - t0 > 450) || (!heard && now - t0 > 4500) || now - t0 > 20000) {
        try { rec.stop(); } catch { /* */ }
        try { src.disconnect(); } catch { /* */ }
        return;
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

async function hoeren() {
  const nr = hoerNr;
  while (callOn && nr === hoerNr) {
    phase("du", "Sie sprechen …");
    const blob = await aufnehmen();
    if (!callOn || nr !== hoerNr) return;
    if (!blob || blob.size < 80) continue;
    zugBusy = true;
    phase("warte", "Lisa hört zu …");
    try {
      const fd = new FormData();
      fd.append("sessionId", sessionId);
      fd.append("audio", blob, "zug.webm");
      const r = await fetch("/api/listen", { method: "POST", body: fd });
      const d = await leseZug(r);
      if (d.textIn) bubble("user", d.textIn);
      if (d.text) bubble("lisa", d.text);
      phase("lisa", "Lisa spricht …");
      await playUrl(d.audioUrl);
      if (d.hangup) { auflegen(); return; }
    } catch (e) {
      meld(String(e.message || e), true);
    } finally {
      zugBusy = false;
    }
  }
}

function starte() {
  meld("");
  const auftrag = ($("kAuftrag").value || (aktuell && aktuell.auftrag) || "").trim();
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    meld("Dieser Browser gibt das Mikrofon nicht frei.", true);
    return;
  }
  // Ton und Mikro im selben Tipp — sonst sperrt der Browser die Wiedergabe.
  unlockAudio();
  const micBitte = navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  weiterNachMic(auftrag, micBitte);
}

async function weiterNachMic(auftrag, micBitte) {
  try {
    micStream = await micBitte;
  } catch {
    meld("Mikrofon nicht erlaubt. Nochmal tippen und zustimmen.", true);
    return;
  }
  await unlockAudio();
  empfaengerId = "";
  $("live").innerHTML = "";
  $("callName").textContent = "Lisa";
  $("call").classList.add("open");
  document.body.classList.add("incall");
  callOn = true;
  hoerNr += 1;
  phase("warte", "verbindet …");
  try {
    const r = await fetch("/api/kampagne/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tenant: $("kTenant").value || (aktuell && aktuell.tenant) || "",
        auftrag,
        probe: true,
        kampagne: aktuell ? { campaignId: aktuell.id } : {},
      }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || "start fehlgeschlagen");
    }
    const data = await leseZug(r);
    sessionId = data.sessionId || "";
    if (!sessionId) throw new Error("keine Sitzung");
    phase("du", "Jemand hebt ab — Lisa wartet auf die Meldung");
    bubble("sys", "Leitung liegt. Lisa spricht erst, wenn sich jemand gemeldet hat.");
    if (callOn) hoeren();
  } catch (e) {
    meld(String(e.message || e), true);
    auflegen();
  }
}

async function auflegen() {
  const sid = sessionId;
  callOn = false;
  hoerNr += 1;
  stopLisaVoice();
  $("call").classList.remove("open", "lisa", "du", "warte");
  document.body.classList.remove("incall");
  if (micStream) {
    for (const t of micStream.getTracks()) t.stop();
    micStream = null;
  }
  if (sid) {
    try {
      await fetch("/api/hangup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId: sid }),
      });
    } catch { /* */ }
  }
  if (aktuell) {
    try { setAktuell(await api("/api/kampagnen/" + aktuell.id)); } catch { /* */ }
    zeichneEmpfaenger();
    zeichneCalls();
    ladeListe();
  }
  sessionId = "";
  empfaengerId = "";
}

$("neu").onclick = () => neu().catch((e) => meld(String(e.message || e), true));
$("speichern").onclick = () => speichern().catch((e) => meld(String(e.message || e), true));
$("dazu").onclick = () => dazu().catch((e) => meld(String(e.message || e), true));
$("naechste").onclick = () => starte();
$("hang").onclick = () => auflegen();

(async function boot() {
  try {
    await ladeTenants();
    await ladeListe();
    if (kampagnen[0]) await oeffnen(kampagnen[0].id);
  } catch (e) {
    meld(String(e.message || e), true);
  }
})();
