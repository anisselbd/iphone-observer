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

# Capture pcap brute (voir limite ci-dessous)
uv run iphone-observer capture -o capture.pcapng --count 500

# Storage: actif par defaut (data/iphone-observer.sqlite). Pour le couper:
uv run iphone-observer serve --no-store
uv run iphone-observer serve --db /chemin/vers/historique.sqlite
```

## App macOS native (phase 7)

App SwiftUI dans `macapp/`. Elle lance le collector Python en **sidecar** (process
separe, jamais linke: frontiere GPL nette) et lui parle en WebSocket. Fenetre
dashboard (etat, device, batterie, indexation, table process, reseau, logs) +
icone menu bar avec statut rapide.

```bash
cd macapp
swift build
swift run            # ou .build/debug/iPhoneObserver
```

Si aucun collector ne repond sur le port 8765, l'app en lance un
(`uv run iphone-observer serve`) depuis `~/Desktop/Dev/iphone-observer`
(surchargeable par la variable d'env IPHONE_OBSERVER_PROJECT).

Limite connue: SwiftUI `Table` emet un warning `reentrant operation in NSTableView`
avec un flux qui change chaque seconde (non fatal). A revisiter (List custom ou
throttle) si ca devient bloquant sur une future version de macOS.

## Storage et timeline

Tout event est persiste dans SQLite (table `events(seq, ts, source, type, udid,
data)`, WAL, index sur ts). Les gros payloads (sysmontap, networking) sont
stockes en version compacte (totaux + top 20) pour borner la croissance; le flux
live reste complet. La timeline unifiee (`/api/timeline?minutes=10`) superpose
sur un meme axe temps: CPU agrege, temperature batterie, debit reseau, bandes
d'indexation et marqueurs d'erreurs syslog.

## Limites connues (iOS 26)

- **pcap**: le service `com.apple.pcapd.shim.remote` est annonce par le device
  mais refuse de demarrer via le tunnel userspace (StartServiceError, gate cote
  iOS 26). La commande `capture` est en place mais le device la rejette. La vue
  reseau live (channel `networking`) couvre RxBytes/TxBytes/RTT par connexion.
- **pid reseau**: le channel networking renvoie pid = -2 pour la plupart des
  connexions (iOS n'attribue pas le pid par connexion), donc le nom de process
  est rarement resolu cote reseau.
- **etat thermique**: non expose proprement; on remonte la temperature batterie.

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
- [x] Phase 5: reseau (channel networking live; pcap gate par iOS 26, voir limites)
- [x] Phase 6: storage SQLite + timeline unifiee (CPU + temp batterie + reseau + indexation + erreurs)
- [x] Phase 7: shell natif SwiftUI (fenetre dashboard + menu bar, collector en sidecar)

## Convention

Pas de tirets cadratins ni demi-cadratins dans le code, les commentaires ou l'UI.
