/* Eine Übergabe-Liste: alle Vorfälle, ein Kopierknopf. */

function studioWurzel() {
  const p = location.pathname.replace(/\/+$/, "");
  if (p.endsWith("/uebergabe")) return p.slice(0, -"/uebergabe".length) + "/";
  return p.endsWith("/") ? p : p + "/";
}

function apiUrl(rel) {
  return new URL(rel.replace(/^\//, ""), location.origin + studioWurzel()).href;
}

function $(id) {
  return document.getElementById(id);
}

async function laden() {
  const r = await fetch(apiUrl("api/uebergabe"));
  const d = await r.json();
  $("text").textContent = d.markdown || "(noch leer)";
  const n = d.anzahl || 0;
  $("status").textContent = n
    ? `${n} Vorfall${n === 1 ? "" : "e"} in einer Liste`
    : "noch kein Einzellauf";
  $("pfade").textContent = d.ordner
    ? `Ordner: ${d.ordner}  ·  Datei: liste.md`
    : "";
}

function perAuswahlKopieren() {
  const pre = $("text");
  const range = document.createRange();
  range.selectNodeContents(pre);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  try {
    return document.execCommand("copy");
  } catch (e) {
    return false;
  }
}

async function kopieren() {
  const t = $("text").textContent || "";
  if (!t.trim() || t.trim() === "(noch leer)") {
    $("kopier-status").textContent = "Nichts zum Kopieren";
    return;
  }
  let ok = false;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(t);
      ok = true;
    } catch (e) {
      ok = false;
    }
  }
  if (!ok) ok = perAuswahlKopieren();
  $("kopier-status").textContent = ok
    ? "Kopiert. Im Cursor-Chat einfügen."
    : "Text ist markiert — Strg+C drücken.";
}

$("knopf-kopieren").addEventListener("click", kopieren);
$("knopf-kopieren-unten").addEventListener("click", kopieren);
laden().catch(() => {
  $("status").textContent = "Studio-API nicht erreichbar (8097)";
});
