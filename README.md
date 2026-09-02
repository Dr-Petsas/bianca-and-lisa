# Bianca & Lisa Telefon-KI

Eigenständiger Dienst. **Rührt Clara, Clara-dev, DemoClara, Lena-Voice und MAS-Prozesse nicht an.**

| Dienst | Port | Live (pickadoc1) |
|--------|------|------------------|
| Lisa | **8095** | `http://100.82.122.62:8095` |
| Bianca | **8096** | `http://100.82.122.62:8096` |
| SIP-Brücke Inbound (Bianca) | 40101 | Asterisk → Tunnel |
| SIP-Brücke Outbound (Lisa) | 40102 | Asterisk → Tunnel |

- LLM/STT/TTS: lokal auf der 5090 (`LLM_BASE`, `STT_BASE`, `TTS_BASE`)
- Schreiben am echten Kalender: **an** (`WRITE_LIVE=1` — nicht zurücksetzen, außer Chef stoppt es)
- Dev lokal: `powershell -File .\start.ps1` → [http://127.0.0.1:8095](http://127.0.0.1:8095)
- Deploy: siehe `.cursor/rules/deploy-server.mdc`

Arbeitsregeln und Patch-Historie: `AGENTS.md`.

---

## Lisa Outbound (KI Recall / CampaignR)

Ausgehende Anrufe laufen **nicht** mehr über ElevenLabs, sondern:

**Cloud Function** → `POST https://lisa-live…/api/outbound/dial` → Lisa (8095) → SSH Call-File → Asterisk/Zaluma → AudioSocket **40102** → `sipbridge-lisa` → Lisa-Gespräch.

Bianca-Inbound (40101 / `extensions_bianca.conf`) bleibt parallel unberührt.

### Cloudflare-Tunnel (wichtige Fallen)

| URL | Was dahinter steckt |
|-----|---------------------|
| `https://lisa-live.pickadoc-tunnel.com` | **Neuer** Named Tunnel → pickadoc1 Lisa (`outbound:true`, LLM `100.82.122.62`) |
| `https://lisa.pickadoc-tunnel.com` | **Alter** Tunnel `pickadoc-mas` → andere Lisa (`100.77.30.98`) — **nicht umbiegen** |

- Connector: Compose-Service `lisa-public` (`network_mode: host`), Token in Server-`.env`: `CLOUDFLARE_TELEFONKI_TOKEN`
- Public Hostname in Zero Trust: Service **`http://localhost:8095`** (wegen Host-Netz — nicht `lisa:8095`, nicht Tailscale-IP)
- Cloud Functions können **keine** Tailscale-IPs erreichen (`100.82…` → Timeout). Öffentliche Tunnel-URL ist Pflicht.
- Token mit `#`/`$` in `.env` in **einfachen** Quotes (Compose-Falle wie beim Phone-Call-Token)

### Cloud Run / Firebase Functions (europe-west3)

Services: `startoutboundcall`, `callcampaignpatients`, `runcampaignrtest`

```powershell
gcloud run services update startoutboundcall `
  --project=docgenda --region=europe-west3 `
  --update-env-vars="OUTBOUND_PROVIDER=lisa,LISA_OUTBOUND_BASE_URL=https://lisa-live.pickadoc-tunnel.com,LISA_OUTBOUND_API_TOKEN=lisa-out-dev-token"
```

Dasselbe für `callcampaignpatients` und `runcampaignrtest`.

| Variable | Bedeutung |
|----------|-----------|
| `OUTBOUND_PROVIDER` | `lisa` oder Rollback `elevenlabs` |
| `LISA_OUTBOUND_BASE_URL` | Tunnel-URL ohne Slash am Ende |
| `LISA_OUTBOUND_API_TOKEN` | Gleicher Wert wie `LISA_OUTBOUND_API_TOKEN` auf pickadoc1 |

### Abnahme / Logs

1. `curl.exe -sf https://lisa-live.pickadoc-tunnel.com/health` → `"outbound":true`, `llmBase` mit `100.82.122.62`
2. Portal: „KI Recall“
3. pickadoc1: `docker logs -f telefonki-lisa-1` (`lisa-outbound dial`) und `telefonki-sipbridge-lisa-1` (`bruecke-start mode=outbound`)

### Nicht anfassen

- Clara 8091/8093/8094, MAS-2, Lena-Voice, vLLM-Neustart
- Bianca-Inbound-Dialplan / DID-Blöcke in `extensions_bianca.conf`
- Alten Tunnel `lisa.pickadoc-tunnel.com` / `pickadoc-mas` migrieren
- `WRITE_LIVE=0` setzen
