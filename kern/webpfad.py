"""Öffentliche URL-Präfixe hinter Reverse-Proxys.

Der Cloudflare-Tunnel zeigt nur auf Lisa (:8095). Bianca liegt darunter unter
``/bianca/``. Absolute Pfade wie ``/studio/`` oder ``<base href="/studio/">``
verlassen den Prefix — CSS/JS werden 404, die Tabs wirken 'platt'.

Nicht je Umgebung hart ``/studio/`` oder ``/bianca/studio/`` einbauen.
Prefix kommt aus ``X-Forwarded-Prefix`` (Lisa setzt ihn), sonst leer.
"""

from __future__ import annotations

import re

ERLAUBTE_PREFIXE = ("", "/bianca")
_BASE_RE = re.compile(r"<base\s+href=['\"][^'\"]*['\"]\s*/?>", re.I)


def prefix_von(headers) -> str:
    raw = ""
    if headers is not None:
        get = getattr(headers, "get", None)
        raw = (get("x-forwarded-prefix") if get else "") or ""
    p = str(raw or "").strip().rstrip("/")
    if p and not p.startswith("/"):
        p = "/" + p
    return p if p in ERLAUBTE_PREFIXE else ""


def oeffentlich(intern: str, prefix: str = "") -> str:
    intern = intern if str(intern).startswith("/") else "/" + str(intern)
    if prefix and (intern == prefix or intern.startswith(prefix + "/")):
        return intern
    return f"{prefix}{intern}" if prefix else intern


def studio_basis(headers=None) -> str:
    return oeffentlich("/studio/", prefix_von(headers))


def location_hinter_prefix(location: str, prefix: str = "/bianca") -> str:
    """Absolute Location hinter den öffentlichen Prefix ziehen."""
    if not location or not location.startswith("/") or not prefix:
        return location
    if location == prefix or location.startswith(prefix + "/"):
        return location
    return prefix + location


def html_studio_pfade(html: str, prefix: str = "/bianca") -> str:
    """Harte /studio/-Links im HTML auf den öffentlichen Prefix umbiegen."""
    if not html or not prefix:
        return html
    for q in ('"', "'"):
        alt = f"/studio/"
        neu = f"{prefix}/studio/"
        html = html.replace(f"href={q}{alt}", f"href={q}{neu}")
        html = html.replace(f"src={q}{alt}", f"src={q}{neu}")
    return html


def html_base_setzen(html: str, basis: str) -> str:
    """Genau ein <base href> auf die öffentliche Studio-Wurzel setzen."""
    tag = f'<base href="{basis}">'
    if _BASE_RE.search(html or ""):
        return _BASE_RE.sub(tag, html, count=1)
    if "<head>" in html:
        return html.replace("<head>", f"<head>\n{tag}", 1)
    if "<head " in html.lower():
        idx = html.lower().find("<head ")
        return html[:idx] + f"<head>\n{tag}\n" + html[idx:]
    return tag + (html or "")
