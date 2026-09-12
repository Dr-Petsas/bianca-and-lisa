/* Ergebnisseite: Laeufe -> Stories (gruen/rot) -> Bubble-Dialog mit Latenz,
   Waechter und Audio je Zug; ganzer Anruf abspielbar. */
"use strict";

const $ = (id) => document.getElementById(id);
let aktuellerLauf = "";
let spielListe = [];
let letzteStatistik = null;
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
  const m = String(text || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}.${m[2]}.` : "—";
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
    `<tr><td>${esc(p.problem)}</td><td>${esc(p.anzahl)}</td><td>${esc(datumKurz(p.zuletzt))}</td><td>${esc(p.empfehlung)}</td></tr>`
  ).join("") || '<tr><td colspan="4" class="klein">Keine wiederkehrenden Probleme.</td></tr>';
  $("stat-analysen").innerHTML = (d.analysen || []).map((a) => `
    <div class="analyse" data-lauf="${esc(a.laufId)}" data-story="${esc(a.storyId)}" data-art="${esc(a.art)}">
      <div class="analyse-kopf"><strong>${esc(a.storyId)}</strong><span class="klein">${esc(a.art)} · ${esc(datumKurz(a.zeit))} · ${esc(a.turns)} Züge</span></div>
      <div class="analyse-problem">${esc((a.probleme || []).join(" · "))}</div>
      <div class="analyse-empfehlung">${esc(a.empfehlung)}</div>
    </div>`).join("") || '<span class="klein">Keine Gespräche mit Verbesserungsbedarf.</span>';
  document.querySelectorAll(".analyse[data-art='Studio']").forEach((el) => {
    el.style.cursor = "pointer";
    el.addEventListener("click", () => {
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
  await Promise.all([laeufeLaden(), statistikLaden()]);
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
      if (q) qwenTag.title = q;
      meta.appendChild(qwenTag);
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
});

datenLaden().then(() => {
  const h = location.hash.replace("#", "");
  if (h) laufOeffnen(h);
});
