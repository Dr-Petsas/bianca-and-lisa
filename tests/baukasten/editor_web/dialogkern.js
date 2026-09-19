/* Dialogkern-Probe im Studio: Praxis waehlen, Einstellungen sehen und
   uebersteuern, Gespraech gegen den reinen Kern spielen.

   Ersetzt das fruehere Einzel-Dock (Port 8199). Werkzeuge sind simuliert —
   diese Seite bucht nichts und schreibt keine Einstellungen. */
'use strict';

const $ = (id) => document.getElementById(id);

let SCHEMA = null;     // Maskenschema vom Server
let WIRKUNG = null;    // aufgeloeste Policy der gewaehlten Praxis
let UEBER = null;      // uebersteuerte Policy (null = Praxisstand)
let SID = '';          // laufende Probe
let BUSY = false;

/* ------------------------------------------------------------------ Hilfen */

function status(text, art) {
  const el = $('status');
  el.textContent = text || '';
  el.style.color = art === 'rot' ? 'var(--rot)' : art === 'gruen' ? 'var(--gruen)' : '';
}

function fehler(text) {
  const el = $('fehler');
  el.hidden = !text;
  el.textContent = text || '';
}

async function hole(pfad, daten) {
  const opt = daten === undefined
    ? {}
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(daten) };
  const r = await fetch(pfad, opt);
  const j = await r.json();
  if (!j.ok) throw new Error(j.fehler || 'Unbekannter Fehler');
  return j;
}

/** Wert an einem Pfad wie ["anliegen","buchen","an"] lesen. */
function lese(obj, pfad) {
  let cur = obj;
  for (const teil of pfad) {
    if (cur === null || typeof cur !== 'object') return undefined;
    cur = cur[teil];
  }
  return cur;
}

/** Wert an einem Pfad setzen, fehlende Ebenen anlegen. */
function setze(obj, pfad, wert) {
  let cur = obj;
  for (const teil of pfad.slice(0, -1)) {
    if (cur[teil] === null || typeof cur[teil] !== 'object') cur[teil] = {};
    cur = cur[teil];
  }
  cur[pfad[pfad.length - 1]] = wert;
}

/** Tiefe Kopie ohne Verweise (die Maske darf WIRKUNG nie veraendern). */
const kopie = (o) => JSON.parse(JSON.stringify(o));

/* ------------------------------------------------------- Maske aufbauen */

function maskeZeichnen() {
  const wurzel = $('maske');
  wurzel.innerHTML = '';
  if (!SCHEMA || !WIRKUNG) return;
  const stand = UEBER || WIRKUNG;

  for (const gruppe of SCHEMA.gruppen) {
    const box = document.createElement('div');
    box.className = 'kern-gruppe';
    const titel = document.createElement('h3');
    titel.textContent = gruppe.titel;
    box.appendChild(titel);
    if (gruppe.hinweis) {
      const h = document.createElement('p');
      h.className = 'klein';
      h.textContent = gruppe.hinweis;
      box.appendChild(h);
    }
    for (const feld of gruppe.felder) box.appendChild(feldZeichnen(feld, stand));
    wurzel.appendChild(box);
  }
}

function aendern(pfad, wert) {
  if (!UEBER) UEBER = kopie(WIRKUNG);
  setze(UEBER, pfad, wert);
  $('knopf-start').classList.add('an');
  status('Maske geändert — „Gespräch starten“ übernimmt sie.', 'gruen');
}

function feldZeichnen(feld, stand) {
  const wert = lese(stand, feld.pfad);

  if (feld.typ === 'bool') {
    const l = document.createElement('label');
    l.className = 'schalter kern-schalter';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = !!wert;
    cb.addEventListener('change', () => aendern(feld.pfad, cb.checked));
    l.appendChild(cb);
    l.appendChild(document.createTextNode(feld.text));
    return l;
  }

  if (feld.typ === 'zahl') {
    const l = document.createElement('label');
    l.className = 'kern-feld kern-feld-zahl';
    const s = document.createElement('span');
    s.textContent = feld.text + (feld.hinweis ? ' — ' + feld.hinweis : '');
    const inp = document.createElement('input');
    inp.type = 'number';
    inp.min = feld.min;
    inp.max = feld.max;
    inp.value = Number(wert || 0);
    inp.addEventListener('change', () => {
      let n = parseInt(inp.value, 10);
      if (!Number.isFinite(n)) n = feld.min;
      n = Math.min(feld.max, Math.max(feld.min, n));
      inp.value = n;
      aendern(feld.pfad, n);
    });
    l.appendChild(s);
    l.appendChild(inp);
    return l;
  }

  if (feld.typ === 'liste') {
    const box = document.createElement('div');
    box.className = 'kern-liste';
    const s = document.createElement('span');
    s.className = 'klein';
    s.textContent = feld.text;
    box.appendChild(s);
    const chips = document.createElement('div');
    chips.className = 'chips';
    const gewaehlt = Array.isArray(wert) ? wert.slice() : [];
    for (const opt of feld.auswahl) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'chip' + (gewaehlt.includes(opt) ? ' an' : '');
      b.textContent = opt;
      b.addEventListener('click', () => {
        const i = gewaehlt.indexOf(opt);
        if (i >= 0) gewaehlt.splice(i, 1);
        else gewaehlt.push(opt);
        b.classList.toggle('an');
        // Reihenfolge der Auswahl-Liste ist die Fragereihenfolge.
        aendern(feld.pfad, feld.auswahl.filter((o) => gewaehlt.includes(o)));
      });
      chips.appendChild(b);
    }
    box.appendChild(chips);
    return box;
  }

  // text: freie Liste mit Komma (Transfer-Ziele)
  const l = document.createElement('label');
  l.className = 'kern-feld';
  const s = document.createElement('span');
  s.textContent = feld.text;
  const inp = document.createElement('input');
  inp.type = 'text';
  inp.value = Array.isArray(wert) ? wert.join(', ') : String(wert || '');
  inp.addEventListener('change', () => {
    const teile = inp.value.split(',').map((t) => t.trim()).filter(Boolean);
    aendern(feld.pfad, teile);
  });
  l.appendChild(s);
  l.appendChild(inp);
  return l;
}

/* ------------------------------------------------------------- Kopfzeilen */

function quelleZeichnen(kopf) {
  const text = {
    uebersteuert: 'Maske übersteuert den Praxisstand (nur dieser Testlauf)',
    vertrag: 'Veröffentlichte Praxis-Einstellungen (DialogPolicyV1)',
    legacy: 'Noch keine veröffentlichten Einstellungen — abgeleitet aus den Mandanten-Flags',
  }[kopf.quelle] || kopf.quelle;
  $('quelle').innerHTML = '';
  const zeile = (k, v) => {
    const d = document.createElement('div');
    d.innerHTML = '<span>' + k + '</span><strong></strong>';
    d.querySelector('strong').textContent = v;
    return d;
  };
  $('quelle').appendChild(zeile('Quelle', text));
  $('quelle').appendChild(zeile('Fach', kopf.fachId || '—'));
  $('quelle').appendChild(zeile('Revision', String(kopf.revision ?? 0)));
}

function warnungenZeichnen(liste) {
  const box = $('warnungen');
  box.innerHTML = '';
  for (const w of liste || []) {
    const d = document.createElement('div');
    d.className = 'warnung';
    d.textContent = w;
    box.appendChild(d);
  }
}

function invariantenZeichnen() {
  const ul = $('invarianten');
  ul.innerHTML = '';
  for (const inv of (SCHEMA && SCHEMA.invarianten) || []) {
    const li = document.createElement('li');
    li.textContent = inv.text;
    ul.appendChild(li);
  }
}

/* --------------------------------------------------------------- Gespräch */

function blase(klasse, text, tags) {
  const d = document.createElement('div');
  d.className = 'bubble ' + klasse;
  const p = document.createElement('div');
  p.textContent = text;
  d.appendChild(p);
  if (tags && tags.length) {
    const meta = document.createElement('div');
    meta.className = 'meta';
    for (const t of tags) {
      if (!t || !t.text) continue;
      const s = document.createElement('span');
      s.className = 'tag' + (t.art ? ' ' + t.art : '');
      s.textContent = t.text;
      meta.appendChild(s);
    }
    d.appendChild(meta);
  }
  const dlg = $('dialog');
  dlg.appendChild(d);
  dlg.scrollTop = dlg.scrollHeight;
}

function zugZeichnen(zug) {
  const dbg = zug.debug || {};
  const tags = [
    dbg.intent ? { text: 'Intent ' + dbg.intent, art: 'gesprochen' } : null,
    dbg.frage_id ? { text: 'Frage ' + dbg.frage_id } : null,
    zug.tool ? { text: 'Werkzeug ' + zug.tool, art: 'stt-gewinner' } : null,
    zug.grund ? { text: zug.grund, art: 'waechter' } : null,
    zug.uebergeben ? { text: 'übergeben', art: 'waechter' } : null,
    zug.hangup ? { text: 'legt auf', art: 'waechter' } : null,
  ].filter(Boolean);
  blase('bianca', zug.antwort || '—', tags);
  if (zug.llm) {
    const d = document.createElement('div');
    d.className = 'kern-llm';
    d.textContent = zug.llm;
    $('dialog').appendChild(d);
  }
  zustandZeichnen(zug.zustand || {});
}

function zustandZeichnen(z) {
  const box = $('zustand');
  box.innerHTML = '';
  const zeile = (k, v, art) => {
    const d = document.createElement('div');
    d.className = 'kern-zeile' + (art ? ' ' + art : '');
    const a = document.createElement('span');
    a.textContent = k;
    const b = document.createElement('strong');
    b.textContent = v;
    d.appendChild(a);
    d.appendChild(b);
    box.appendChild(d);
  };
  zeile('Zug', String(z.zugNr ?? 0));
  zeile('Anliegen', z.task || '—');
  zeile('Phase', z.phase || '—');
  if ((z.geparkt || []).length) zeile('Geparkt', z.geparkt.join(', '));
  const budget = Number(z.stockBudget || 0);
  const zahl = Number(z.stockZahl || 0);
  if (z.stockFrage) {
    const art = zahl > budget ? 'bad' : zahl === budget ? 'warn' : '';
    zeile('Schleifen-Aufsicht', z.stockFrage + ' ' + zahl + '/' + budget, art);
  }
  if (z.terminal) zeile('Terminal', 'ja', 'bad');
  if (z.letzterWrite) zeile('Letzter Write', z.letzterWrite, 'ok');

  const slots = z.slots || {};
  const bekannt = z.bekannt || {};
  const tabelle = (titel, daten) => {
    const keys = Object.keys(daten);
    if (!keys.length) return;
    const h = document.createElement('div');
    h.className = 'kern-subtitel';
    h.textContent = titel;
    box.appendChild(h);
    for (const k of keys) zeile(k, String(daten[k]));
  };
  tabelle('Slots des Anliegens', slots);
  tabelle('Im Gespräch bekannt', bekannt);

  const led = $('ledger');
  led.innerHTML = '';
  for (const e of z.ledger || []) {
    const d = document.createElement('div');
    d.className = 'kern-zeile ' + (e.committed ? 'ok' : e.status === 'OK' ? '' : 'warn');
    const a = document.createElement('span');
    a.textContent = e.name;
    const b = document.createElement('strong');
    b.textContent = e.status + (e.committed ? ' ✓' : '');
    d.appendChild(a);
    d.appendChild(b);
    led.appendChild(d);
  }
  if (!(z.ledger || []).length) {
    led.innerHTML = '<div class="klein">Noch kein Werkzeug gelaufen.</div>';
  }
}

/* ----------------------------------------------------------------- Aktionen */

async function policyLaden() {
  status('lädt Praxis …');
  try {
    const j = await hole('api/kern/policy', { tenant: $('tenant').value, policy: UEBER });
    WIRKUNG = j.policy;
    quelleZeichnen(j);
    warnungenZeichnen(j.warnungen);
    maskeZeichnen();
    status(j.praxis, 'gruen');
  } catch (e) {
    status('Fehler: ' + e.message, 'rot');
  }
}

async function starten() {
  if (BUSY) return;
  BUSY = true;
  fehler('');
  $('dialog').innerHTML = '';
  status('startet …');
  try {
    const j = await hole('api/kern/start', {
      tenant: $('tenant').value,
      szenario: $('szenario').value,
      policy: UEBER,
    });
    SID = j.kopf.sid;
    WIRKUNG = j.kopf.policy;
    quelleZeichnen(j.kopf);
    warnungenZeichnen(j.kopf.warnungen);
    maskeZeichnen();
    blase('bianca', j.zug.antwort, [{ text: j.kopf.hirn ? 'LLM an' : 'LLM aus (nur Regeln)' }]);
    zustandZeichnen(j.zug.zustand || {});
    $('eingabe').disabled = false;
    $('knopf-senden').disabled = false;
    $('knopf-start').classList.remove('an');
    $('eingabe').focus();
    status(j.kopf.praxis + ' · ' + j.kopf.szenario, 'gruen');
  } catch (e) {
    status('Fehler: ' + e.message, 'rot');
    fehler(e.message);
  } finally {
    BUSY = false;
  }
}

async function senden() {
  const text = $('eingabe').value.trim();
  if (!text || !SID || BUSY) return;
  BUSY = true;
  fehler('');
  blase('anrufer', text);
  $('eingabe').value = '';
  try {
    const j = await hole('api/kern/zug', { sid: SID, text });
    zugZeichnen(j.zug);
  } catch (e) {
    fehler(e.message);
  } finally {
    BUSY = false;
    $('eingabe').focus();
  }
}

/* --------------------------------------------------------------- Startseite */

async function init() {
  try {
    SCHEMA = await hole('api/kern/maske');
  } catch (e) {
    status('Maske nicht ladbar: ' + e.message, 'rot');
    return;
  }
  invariantenZeichnen();

  const sz = $('szenario');
  for (const s of SCHEMA.szenarien) {
    const o = document.createElement('option');
    o.value = s.id;
    o.textContent = s.text;
    sz.appendChild(o);
  }

  try {
    const t = await hole('api/tenants');
    const sel = $('tenant');
    for (const m of t.tenants) {
      const o = document.createElement('option');
      o.value = m.id;
      o.textContent = (m.praxisName || m.id) + ' (' + m.id + ')';
      sel.appendChild(o);
    }
    sel.value = t.default;
  } catch (e) {
    status('Praxen nicht ladbar: ' + e.message, 'rot');
    return;
  }

  $('tenant').addEventListener('change', () => { UEBER = null; policyLaden(); });
  $('szenario').addEventListener('change', () => { $('knopf-start').classList.add('an'); });
  $('knopf-start').addEventListener('click', starten);
  $('knopf-zuruecksetzen').addEventListener('click', () => { UEBER = null; policyLaden(); });
  $('knopf-senden').addEventListener('click', senden);
  $('eingabe').addEventListener('keydown', (e) => { if (e.key === 'Enter') senden(); });

  await policyLaden();
}

init();
