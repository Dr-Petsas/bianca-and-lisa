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

async function kopieren() {
  const t = $("text").textContent || "";
  if (!t.trim() || t.trim() === "(noch leer)") {
    $("kopier-status").textContent = "Nichts zum Kopieren";
    return;
  }
  try {
    await navigator.clipboard.writeText(t);
    $("kopier-status").textContent = "Kopiert. Im Cursor-Chat einfügen.";
  } catch (e) {
    $("kopier-status").textContent = "Zwischenablage blockiert — Text markieren und Strg+C.";
  }
}

$("knopf-kopieren").addEventListener("click", kopieren);
$("knopf-kopieren-unten").addEventListener("click", kopieren);
laden().catch(() => {
  $("status").textContent = "Studio-API nicht erreichbar (8097)";
});
