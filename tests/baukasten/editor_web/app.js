/* Editor des Baukasten-Teststudios: Chips -> Story -> Lauf am Bianca-Dienst.
   Mithoeren pollt NUR diesen Server (8097) — die Bianca-Latenz bleibt unberuehrt. */
"use strict";

let KATALOG = null;
const wahl = {
  stimme: "", nachname: "", anliegen: "termin", grund: "", behandler: null,
  versicherung: "", tag: "Mittwoch", slotAnnahme: 0, slotRichtung: "",
  abschweifer: new Set(), extras: new Set(),
};
let storyNr = 1;
let telefonQualitaet = false;
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

function mehrfachwahl(containerId, werte, menge) {
  const box = $(containerId);
  box.innerHTML = "";
  werte.forEach((w) => {
    box.appendChild(chip(w, menge.has(w), (el) => {
      if (menge.has(w)) { menge.delete(w); el.classList.remove("an"); }
      else { menge.add(w); el.classList.add("an"); }
    }));
  });
}

function chipsBauen() {
  einzelwahl("chips-stimme", KATALOG.stimmen, "stimme",
    (s) => `${KATALOG.vornamen[s] || s} (${s})`);
  einzelwahl("chips-nachname", KATALOG.nachnamen, "nachname");
  einzelwahl("chips-anliegen", KATALOG.anliegen, "anliegen");
  einzelwahl("chips-grund", Object.keys(KATALOG.gruende), "grund",
    (g) => `${g} → ${KATALOG.gruende[g]}`);
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
  mehrfachwahl("chips-extras",
    ["halbsatz", "zwischenfragePreis", "readbackFehler", "pzr"], wahl.extras);
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
  return s;
}

function telefonKnopfZeichnen() {
  const el = $("knopf-telefon");
  if (!el) return;
  el.classList.toggle("an", telefonQualitaet);
  el.setAttribute("aria-pressed", telefonQualitaet ? "true" : "false");
  el.textContent = telefonQualitaet
    ? "Telefonqualität an (8 kHz / 8 bit)"
    : "Telefonqualität aus";
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
    telefonQualitaet,
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
  $("status").textContent = d.laeuft
    ? `Lauf ${d.laufId}: Story ${idx}/${d.storiesGesamt} ${d.story || ""}`
    : (d.laufId ? `Lauf ${d.laufId} fertig — ${(d.fertig || []).filter((x) => x.ok).length}/${(d.fertig || []).length} grün` : "bereit");
  $("lauf-hinweis").innerHTML = d.laufId
    ? `<a href="ergebnisse#${d.laufId}" style="color:var(--akzent)">Ergebnisse des Laufs ansehen</a>` : "";
  if (d.fehler) $("fehler").textContent = d.fehler;
  $("knopf-start").disabled = d.laeuft;
  $("knopf-batch").disabled = d.laeuft;
  if ($("knopf-telefon")) $("knopf-telefon").disabled = d.laeuft;

  if (d.warm && d.warm.n) {
    const t = String(d.warm.text || "");
    $("live-story").textContent = `Audio ${d.warm.i}/${d.warm.n}: ${t}`;
  } else if (d.story) {
    $("live-story").textContent = d.story + (telefonQualitaet ? " · Telefonqualität" : "");
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

async function boot() {
  KATALOG = await (await fetch("api/katalog")).json();
  chipsBauen();
  $("knopf-automatik").addEventListener("click", automatik);
  $("knopf-telefon").addEventListener("click", () => {
    telefonQualitaet = !telefonQualitaet;
    telefonKnopfZeichnen();
  });
  telefonKnopfZeichnen();
  $("knopf-start").addEventListener("click", () => laufStarten(1));
  $("knopf-batch").addEventListener("click", () => laufStarten(10));
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
