/* Ergebnisseite: Laeufe -> Stories (gruen/rot) -> Bubble-Dialog mit Latenz,
   Waechter und Audio je Zug; ganzer Anruf abspielbar. */
"use strict";

const $ = (id) => document.getElementById(id);
let aktuellerLauf = "";
let spielListe = [];
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
    try {
      const r = await fetch(url, { cache: "no-store" });
      if (r.ok) blob = await r.blob();
    } catch { /* */ }
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
          fertig();
        };
        lautsprecher.addEventListener("ended", ende);
        lautsprecher.addEventListener("error", ende);
      });
    } catch (e) {
      console.warn("studio-ton play", url, e);
    } finally {
      try { URL.revokeObjectURL(obj); } catch { /* */ }
    }
  })();
}

async function laeufeLaden() {
  const d = await (await fetch("api/laeufe")).json();
  const box = $("laeufe");
  box.innerHTML = "";
  (d.laeufe || []).forEach((l) => {
    const div = document.createElement("div");
    div.className = "laufkarte";
    div.innerHTML = `<strong>${l.laufId}</strong>
      <span class="klein">${l.gestartet || ""}</span>
      <span style="margin-left:auto">
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
      <span style="margin-left:auto" class="klein">max ${s.latenzMaxS || "?"}s</span>`;
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

laeufeLaden().then(() => {
  const h = location.hash.replace("#", "");
  if (h) laufOeffnen(h);
});
