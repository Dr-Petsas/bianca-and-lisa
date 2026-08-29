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
let poller = null;
const gespielt = new Set();  // Audio-URLs, die das Mithoeren schon abgespielt hat
let spielKette = Promise.resolve();

const $ = (id) => document.getElementById(id);

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

function storyBauen() {
  const s = { nr: storyNr };
  if (wahl.stimme) s.stimme = wahl.stimme;
  if (wahl.stimme) s.vorname = KATALOG.vornamen[wahl.stimme];
  if (wahl.nachname) s.nachname = wahl.nachname;
  if (wahl.anliegen) s.anliegen = wahl.anliegen;
  if (wahl.grund) s.grund = wahl.grund;
  if (wahl.behandler !== null && wahl.behandler !== "") {
    s.behandler = wahl.behandler === "egal" ? "" : wahl.behandler;
  }
  if (wahl.versicherung) s.versicherung = wahl.versicherung;
  if (wahl.slotAnnahme) s.slotAnnahme = wahl.slotAnnahme;
  if (wahl.slotRichtung) s.slotRichtung = wahl.slotRichtung;
  if (wahl.abschweifer.size) {
    const anker = KATALOG.anker;
    s.abschweifer = [...wahl.abschweifer].map((t, i) => [anker[i % anker.length], t]);
  } else {
    s.abschweifer = [];
  }
  s.halbsatz = wahl.extras.has("halbsatz");
  s.zwischenfragePreis = wahl.extras.has("zwischenfragePreis");
  s.readbackFehler = wahl.extras.has("readbackFehler");
  s.pzr = wahl.extras.has("pzr");
  return s;
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
  const body = {
    anzahl, ab: storyNr, tag: wahl.tag || "Mittwoch",
    mithoeren: $("mithoeren").checked,
  };
  if (anzahl === 1) body.story = storyBauen();
  const r = await fetch("/api/lauf", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  if (!d.ok) { $("fehler").textContent = d.fehler || "Start fehlgeschlagen"; return; }
  storyNr += anzahl;
  gespielt.clear();
  $("live-block").style.display = "";
  $("live-dialog").innerHTML = "";
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
  if (z.audioUrl) {
    const knopf = document.createElement("button");
    knopf.textContent = "▶";
    knopf.addEventListener("click", () => new Audio(z.audioUrl).play());
    meta.appendChild(knopf);
  }
  if (meta.children.length) div.appendChild(meta);
  return div;
}

function mithoerenSpielen(z) {
  if (!$("mithoeren").checked || !z.audioUrl || gespielt.has(z.audioUrl)) return;
  gespielt.add(z.audioUrl);
  spielKette = spielKette.then(() => new Promise((fertig) => {
    const a = new Audio(z.audioUrl);
    a.addEventListener("ended", fertig);
    a.addEventListener("error", fertig);
    a.play().catch(fertig);
  }));
}

async function pollen() {
  let d;
  try {
    const r = await fetch("/api/live");
    d = await r.json();
  } catch { return; }
  const idx = d.storyIdx || 0;
  $("status").textContent = d.laeuft
    ? `Lauf ${d.laufId}: Story ${idx}/${d.storiesGesamt} ${d.story || ""}`
    : (d.laufId ? `Lauf ${d.laufId} fertig — ${(d.fertig || []).filter((x) => x.ok).length}/${(d.fertig || []).length} grün` : "bereit");
  $("lauf-hinweis").innerHTML = d.laufId
    ? `<a href="/ergebnisse#${d.laufId}" style="color:var(--akzent)">Ergebnisse des Laufs ansehen</a>` : "";
  if (d.fehler) $("fehler").textContent = d.fehler;
  $("knopf-start").disabled = d.laeuft;
  $("knopf-batch").disabled = d.laeuft;

  if (d.story) $("live-story").textContent = d.story;
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
  if (!poller) poller = setInterval(pollen, 1000);
}

async function boot() {
  KATALOG = await (await fetch("/api/katalog")).json();
  chipsBauen();
  $("knopf-automatik").addEventListener("click", automatik);
  $("knopf-start").addEventListener("click", () => laufStarten(1));
  $("knopf-batch").addEventListener("click", () => laufStarten(10));
  pollen();
  pollerStarten();
}

boot();
