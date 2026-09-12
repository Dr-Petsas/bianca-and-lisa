"""Anrufer-Audio fuer den Baukasten-Test: (Stimme, Text) -> WAV mit Cache.

Gerendert wird on demand ueber den Qwen3-TTS-Container (TTS_BASE, blocking
/speak) mit den Anrufer-Klonen aus tts_serve/stimmen/. Jeder Render laeuft
durch dieselbe Pegel-Schicht wie live (kern.tts.pcm16_wav) und landet unter
tests/baukasten/audio/<stimme>/<hash>.wav plus .txt-Beizettel — einmal
gerendert, fuer immer wiederverwendbar (Engine-Wechsel = neuer Hash, weil
die TTS-Basis im Schluessel steckt).
"""

from __future__ import annotations

import array
import hashlib
import re
import struct
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from kern.config import TTS_BASE  # noqa: E402
from kern.tts import pcm16_wav  # noqa: E402
from tests.baukasten import saetze  # noqa: E402

AUDIO_DIR = Path(__file__).resolve().parent / "audio"
PCM_RATE = 24000


TEL_RATE = 8000  # Schmalband-Telefon (G.711)
TEL_BITS = 8     # 8 kHz × 8 bit μ-law = 64 kbit/s wie Zaluma
# Cache-Bruch, wenn sich die Leitungssimulation aendert.
TEL_DATEI_SUFFIX = ".tel-g711.wav"
# Heisse Leitung: Zaluma kam live mit Clipping an.
TEL_GAIN = 1.18
TEL_RAUSCHEN = 90  # PCM16-Amplituden, Leitungszischen
HZ_STUFEN = (8000, 16000, 24000)
DEMO_STIMME = "markus"
DEMO_SATZ = (
    "Hallo, ich bin Markus Müller, ich hätte gerne einen Termin heute als Notfall."
)
# Studio-Default: echte Telefonleitung, Regler von dort aus feiner.
LEITUNG_DEFAULT = {
    "hz": 8000,
    "rauschen": 28,
    "artefakte": 12,
    "dropouts": 6,
    "pegel": 75,
    "g711": True,
}


def wav_schliessen(blob: bytes) -> bytes:
    """Offenen Stream-WAV-Header (0xFFFFFFFF) auf die echte PCM-Laenge setzen.

    Biancas /api/audio-stream liefert einen wachsenden WAV mit unbekannter
    Groesse — Chrome spielt die gespeicherte Datei sonst nicht (Play-Knopf
    da, kein Ton). Standard-44-Byte-Header wie kern.tts.wav_header_offen."""
    if not blob or blob[:4] != b"RIFF" or len(blob) < 44:
        return blob
    pcm = len(blob) - 44
    data_size = struct.unpack_from("<I", blob, 40)[0]
    if data_size == pcm:
        return blob
    out = bytearray(blob)
    struct.pack_into("<I", out, 4, 36 + pcm)
    struct.pack_into("<I", out, 40, pcm)
    return bytes(out)

# Qwen3-TTS bricht lange Renders nach ~8 s ab (Modell-Deckel) — der
# Grunewald-Buchstabier-Satz endete live bei "L wie" und Bianca lief in
# den Frage-Loop. Texte ueber dieser Laenge werden deshalb an Komma-/
# Satz-Fugen gestueckelt, einzeln gerendert und mit kurzer Pause gefuegt.
_HAPPEN_ZEICHEN = 80
_PAUSE_S = 0.22


def _happen(text: str) -> list[str]:
    """Langen Text an Satz-/Komma-Fugen in TTS-sichere Haeppchen teilen."""
    if len(text) <= _HAPPEN_ZEICHEN:
        return [text]
    teile = re.split(r"(?<=[.!?,;:])\s+", text)
    out: list[str] = []
    akt = ""
    for t in teile:
        if akt and len(akt) + 1 + len(t) > _HAPPEN_ZEICHEN:
            out.append(akt)
            akt = t
        else:
            akt = f"{akt} {t}".strip()
    if akt:
        out.append(akt)
    return out


def _schluessel(stimme: str, text: str) -> str:
    roh = f"{TTS_BASE}|{stimme}|{' '.join(text.split())}"
    return hashlib.sha1(roh.encode("utf-8")).hexdigest()[:20]


def audio_pfad(stimme: str, text: str) -> Path:
    return AUDIO_DIR / stimme / f"{_schluessel(stimme, text)}.wav"


def audio_holen(stimme: str, text: str, *, timeout: float = 180.0) -> Path:
    """WAV-Pfad fuer den Satz — rendert nur, wenn er nicht im Cache liegt."""
    if not TTS_BASE:
        raise RuntimeError("TTS_BASE fehlt — Baukasten-Audio braucht den lokalen Container.")
    pfad = audio_pfad(stimme, text)
    if pfad.is_file() and pfad.stat().st_size > 44:
        return pfad
    pfad.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    pcm = b""
    pause = b"\x00\x00" * int(PCM_RATE * _PAUSE_S)
    for i, teil in enumerate(_happen(text)):
        r = httpx.post(f"{TTS_BASE}/speak", json={"text": teil, "voice": stimme},
                       timeout=timeout)
        r.raise_for_status()
        if i:
            pcm += pause
        pcm += r.content
    wav = pcm16_wav(pcm)
    if len(wav) <= 44:
        raise RuntimeError(f"leerer Render fuer {stimme}: {text!r}")
    tmp = pfad.with_suffix(".tmp")
    tmp.write_bytes(wav)
    tmp.replace(pfad)
    pfad.with_suffix(".txt").write_text(text, encoding="utf-8")
    print(f"baukasten-klang: {stimme} {len(wav) / (PCM_RATE * 2):.1f}s "
          f"render={time.perf_counter() - t0:.1f}s {pfad.name}", flush=True)
    return pfad


def _wav_pcm16_header(data_len: int, rate: int) -> bytes:
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_len, b"WAVE",
        b"fmt ", 16, 1, 1, rate, rate * 2, 2, 16,
        b"data", data_len,
    )


def _ulaw_encode(s: int) -> int:
    """PCM16 -> μ-law-Byte (ITU-T G.711), wie Zaluma auf der Leitung."""
    bias, clip = 0x84, 32635
    sign = 0
    if s < 0:
        sign = 0x80
        s = -s
    if s > clip:
        s = clip
    s += bias
    exp, mask = 7, 0x4000
    while exp > 0 and not (s & mask):
        exp -= 1
        mask >>= 1
    mant = (s >> (exp + 3)) & 0x0F
    return ~(sign | (exp << 4) | mant) & 0xFF


def _ulaw_decode(u: int) -> int:
    u = ~u & 0xFF
    sign = u & 0x80
    exp = (u >> 4) & 0x07
    mant = u & 0x0F
    s = ((mant << 3) + 0x84) << exp
    s -= 0x84
    return -s if sign else s


def _clip16(v: float) -> int:
    if v > 32767:
        return 32767
    if v < -32768:
        return -32768
    return int(v)


def _clamp_pct(v: object) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        n = 0
    return max(0, min(100, n))


def leitung_norm(d: dict | None = None) -> dict:
    """Regler der Audioqualitäts-Box — immer dieselben sechs Felder."""
    src = dict(LEITUNG_DEFAULT)
    if isinstance(d, dict):
        src.update(d)
    hz = int(src.get("hz") or TEL_RATE)
    hz = min(HZ_STUFEN, key=lambda x: abs(x - hz))
    g711 = src.get("g711")
    if isinstance(g711, str):
        g711 = g711.strip().lower() not in {"0", "false", "aus", "off", ""}
    return {
        "hz": hz,
        "rauschen": _clamp_pct(src.get("rauschen")),
        "artefakte": _clamp_pct(src.get("artefakte")),
        "dropouts": _clamp_pct(src.get("dropouts")),
        "pegel": _clamp_pct(src.get("pegel")),
        "g711": bool(g711),
    }


def leitung_suffix(leitung: dict | None) -> str:
    L = leitung_norm(leitung)
    g = "g711" if L["g711"] else "pcm"
    return (
        f".tel-h{L['hz']}-r{L['rauschen']}-a{L['artefakte']}"
        f"-d{L['dropouts']}-p{L['pegel']}-{g}.wav"
    )


def _rng(n: int) -> int:
    return ((n * 1103515245 + 12345) >> 16) & 0xFF


def _resample(samples: array.array, src: int, dst: int) -> array.array:
    if src == dst or not samples:
        return samples
    ratio = src / dst
    n = max(1, int(len(samples) / ratio))
    out = array.array("h")
    last = len(samples) - 1
    for i in range(n):
        pos = i * ratio
        j = int(pos)
        frac = pos - j
        a = samples[min(j, last)]
        b = samples[min(j + 1, last)]
        out.append(_clip16(a + (b - a) * frac))
    return out


def _telefon_wav_klassisch(blob: bytes, src_rate: int) -> bytes:
    """Fester 8-kHz-G.711-Pfad — bleibt der Default ohne Regler."""
    if not blob or blob[:4] != b"RIFF" or len(blob) < 44:
        return blob
    rate = struct.unpack_from("<I", blob, 24)[0] or src_rate
    pcm = blob[44:]
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if not samples:
        return blob
    step = max(1, int(round(rate / TEL_RATE)))
    prev_x = 0
    prev_y = 0.0
    out = array.array("h")
    n = 0
    for i in range(0, len(samples) - step + 1, step):
        acc = sum(samples[i:i + step]) // step
        y = acc - prev_x + 0.86 * prev_y
        prev_x = acc
        prev_y = y
        rausch = (_rng(n) - 128) * TEL_RAUSCHEN // 128
        heiss = _clip16(y * TEL_GAIN + rausch)
        out.append(_ulaw_decode(_ulaw_encode(heiss)))
        n += 1
    data = out.tobytes()
    return _wav_pcm16_header(len(data), TEL_RATE) + data


def _telefon_wav_leitung(blob: bytes, src_rate: int, L: dict) -> bytes:
    if not blob or blob[:4] != b"RIFF" or len(blob) < 44:
        return blob
    rate = struct.unpack_from("<I", blob, 24)[0] or src_rate
    pcm = blob[44:]
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if not samples:
        return blob
    ziel = int(L["hz"])
    out = _resample(samples, rate, ziel)
    if ziel <= 8000:
        prev_x = 0
        prev_y = 0.0
        gefiltert = array.array("h")
        for acc in out:
            y = acc - prev_x + 0.86 * prev_y
            prev_x = acc
            prev_y = y
            gefiltert.append(_clip16(y))
        out = gefiltert
    gain = 0.85 + (int(L["pegel"]) / 100.0) * 0.55
    rausch_amp = int(L["rauschen"]) * 320 // 100
    click_p = int(L["artefakte"]) / 100.0 * 0.18
    drop_p = int(L["dropouts"]) / 100.0 * 0.35
    frame = max(1, ziel // 50)
    drop_bis = -1
    n = 0
    fertig = array.array("h")
    for i, s in enumerate(out):
        if i <= drop_bis:
            fertig.append(0)
            n += 1
            continue
        if drop_p and i % frame == 0 and (_rng(n + 9000) / 255.0) < drop_p:
            drop_bis = i + frame - 1
            fertig.append(0)
            n += 1
            continue
        y = s * gain
        if rausch_amp:
            y += (_rng(n) - 128) * rausch_amp / 128.0
        if click_p and (_rng(n + 4000) / 255.0) < (click_p / 40.0):
            y += 16000 if _rng(n + 7) >= 128 else -16000
        heiss = _clip16(y)
        if L["g711"]:
            heiss = _ulaw_decode(_ulaw_encode(heiss))
        fertig.append(heiss)
        n += 1
    data = fertig.tobytes()
    return _wav_pcm16_header(len(data), ziel) + data


def telefon_wav(blob: bytes, *, src_rate: int = PCM_RATE,
                leitung: dict | None = None) -> bytes:
    """Studio-WAV -> Telefonleitung, dann wieder PCM16-WAV.

    Ohne ``leitung`` bleibt der klassische 8-kHz-G.711-Pfad (Tests).
    Mit Regler: Samplefrequenz, Rauschen, Artefakte, Dropouts, Pegel,
    echte G.711 μ-law hin und zurück (8 bit, 64 kbit/s).
    """
    if leitung is None:
        return _telefon_wav_klassisch(blob, src_rate)
    return _telefon_wav_leitung(blob, src_rate, leitung_norm(leitung))


def telefon_datei(pfad: Path, *, leitung: dict | None = None) -> Path:
    """Downsample-Cache neben der Studio-WAV (Suffix wechselt mit Algorithmus)."""
    suffix = TEL_DATEI_SUFFIX if leitung is None else leitung_suffix(leitung)
    ziel = pfad.with_name(pfad.stem + suffix)
    if ziel.is_file() and ziel.stat().st_size > 44:
        return ziel
    blob = telefon_wav(pfad.read_bytes(), leitung=leitung)
    tmp = ziel.with_suffix(".tmp")
    tmp.write_bytes(blob)
    tmp.replace(ziel)
    return ziel


def dauer_s(pfad: Path) -> float:
    """Spieldauer eines PCM16-WAV; Rate steht im Header (24 kHz oder 8 kHz)."""
    try:
        raw = pfad.read_bytes()[:44]
    except OSError:
        return 0.0
    if len(raw) < 44 or raw[:4] != b"RIFF":
        return 0.0
    rate = struct.unpack_from("<I", raw, 24)[0] or PCM_RATE
    bits = struct.unpack_from("<H", raw, 34)[0] or 16
    try:
        groesse = pfad.stat().st_size
    except OSError:
        return 0.0
    byte_ps = max(1, rate * max(1, bits // 8))
    return max(0.0, (groesse - 44) / byte_ps)


def vorwaermen(stimme: str, texte: list[str]) -> list[Path]:
    """Eine Satzliste fuer eine Stimme vorab rendern (Cache fuellen)."""
    return [audio_holen(stimme, t) for t in texte]


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Baukasten-Audio rendern/probieren")
    p.add_argument("--stimme", default="markus")
    p.add_argument("--text", default="")
    p.add_argument("--probe", action="store_true",
                   help="einen Testsatz mit allen acht Anrufer-Stimmen rendern")
    a = p.parse_args()

    if a.probe:
        satz = saetze.EROEFFNUNG_MACHEN[0]
        for s in saetze.STIMMEN_M + saetze.STIMMEN_W:
            audio_holen(s, satz)
        return
    if a.text:
        pfad = audio_holen(a.stimme, a.text)
        print(pfad)
        return
    p.print_help()


if __name__ == "__main__":
    main()
