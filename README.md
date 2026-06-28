# iphone-observer

Observabilite live d'un iPhone (iPhone 17 Pro Max, iOS 26) depuis macOS, sans
jailbreak: CPU/RAM par process, batterie/hardware, reseau, logs systeme, dans un
dashboard unifie. Outil perso.

Le moteur bas niveau est [pymobiledevice3](https://github.com/doronz88/pymobiledevice3)
(GPL-3.0), isole dans le package collector `iphone_observer` et invoque comme
**sidecar** (process separe). L'UI native (phase 2) ne linke jamais ce package:
elle parle au collector via WebSocket.

## Prerequis (iOS 26)

1. **Python 3.14+** (permet le tunnel `--userspace`, sans root). Verifie: `python3.14 --version`.
2. **Mode developpeur** active sur l'iPhone: Reglages > Confidentialite et
   securite > Mode developpeur, puis redemarrage du tel.
3. **Appairage USB** fait au moins une fois (deverrouille + "Se fier"). Ensuite le
   WiFi fonctionne (meme reseau, tel deverrouille).
4. **Tunnel RemoteXPC** lance (obligatoire en iOS >= 17).

## Installation

```bash
uv sync
```

## Usage (phase 1)

```bash
# Verifier les prerequis (trust, Mode developpeur, tunnel)
uv run iphone-observer doctor

# Demarrer et maintenir le tunnel (laisser tourner dans un terminal dedie)
uv run iphone-observer tunnel start

# Identite du device
uv run iphone-observer info
uv run iphone-observer info --json     # dump lockdown complet

# Collector + dashboard live (tunnel + sysmontap -> WebSocket)
uv run iphone-observer serve           # http://127.0.0.1:8765
uv run iphone-observer serve --interval 500 --port 8765
```

## Schema d'events

Tous les flux partagent une enveloppe unique horodatee:

```
{ ts, source, udid, type, seq, data }
```

`source` dans {collector, sysmontap, diagnostics, syslog, networking, pcap}.
Storage (phase 6): une table SQLite events(ts, source, type, udid, seq, data).

## Etat

- [x] Phase 1: tunnel + connexion + device info
- [x] Phase 2: sysmontap -> WebSocket -> dashboard
- [x] Phase 3: batterie / diagnostics (temperature, voltage, amperage, cycles, sante, chargeur)
- [x] Phase 4: syslog (filtre + rate-limite) + detecteur d'indexation (CPU des daemons, hysteresis)
- [ ] Phase 5: reseau (pcap + networking)
- [ ] Phase 6: storage + timeline unifiee
- [ ] Phase 7: shell natif

## Convention

Pas de tirets cadratins ni demi-cadratins dans le code, les commentaires ou l'UI.
