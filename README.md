# Dashboard Schneider EVCE2

Dashboard web modulaire pour monitorer des bornes via l'API EVCE2.

## Fonctionnalites

- Connexion API avec login/mot de passe
- Connexion API directe par token Bearer
- Polling automatique des donnees
- KPI: nombre de bornes, disponibilite, sessions en cours, energie
- Graphe repartition du courant par phase (L1/L2/L3)
- Graphe repartition des bornes par zone
- Graphiques: repartition des statuts, top bornes actives, tendance sessions
- Tableau detaille des bornes
- Backend proxy local pour eviter les problemes CORS

## Endpoints EVCE2 utilises

- `POST /login/login`
- `POST /login/logout`
- `GET /stations`
- `GET /stations/statuses`
- `GET /transactions/ongoing`
- `GET /transactions/ended`
- `GET /maintenance/product_status`

## Lancer le dashboard

```bash
node server.js
```

Puis ouvrir:

- `http://localhost:8080`

## Mode token direct

Dans le formulaire:

- renseigner `URL API`
- coller le token dans `Token Bearer`
- laisser `Login` et `Mot de passe` vides

Le token peut etre fourni avec ou sans prefixe `Bearer`.

## Saisie Agence Externe

- Ecran TV/dashboard principal: `http://localhost:8080/`
- Page de saisie externe agence: `http://localhost:8080/agency-input.html`

Les informations saisies sur la page externe sont stockees cote serveur (`agency-info.json`) et affichees automatiquement sur le dashboard TV.

## Message du Jour

- Page de saisie: `http://localhost:8080/message-du-jour.html`
- API: `GET/POST /backend/motd` (stocke dans `motd.json`)

## Meteo

- Page de saisie: `http://localhost:8080/meteo.html`
- API: `GET/POST /backend/weather` (stocke dans `weather.json`)

Note: la meteo peut aussi etre modifiee directement dans l'admin du dashboard TV.

## Page RS485 (compteur)

Page de lecture Modbus RTU via adaptateur USB/RS485 (profil Schneider iEM3250):

- URL: `http://localhost:8080/rs485.html`
- API: `POST /backend/rs485/read`
- Scan auto: `POST /backend/rs485/scan`
- Bouton `Tester profil iEM3250` (base table Schneider `DOCA0005EN-15`, lecture float32 avec test offset registre)
- Parametres typiques:
  - Port: `COMx` (ex: `COM3`)
  - Baud: `19200`
  - ID: `5`

Dependance necessaire:

```bash
npm i modbus-serial
```

## Compteur IRVE (GPIO)

- API lecture dashboard: `GET /backend/irve`
- API push depuis Raspberry: `POST /backend/irve`

Payload attendu:

```json
{
  "pin": 17,
  "pulses": 1234,
  "dt_s": 2.45,
  "power_kw": 14.6,
  "ea_pulse_kwh": 12.34,
  "ea_session_kwh": 12.34,
  "ea_total_kwh": 1053.54,
  "timestamp_iso": "2026-03-05 16:25:00",
  "timestamp_unix": 1772727900
}
```

Lecture RS485 fixe utilisee par l'index (si disponible):

- port: `COM11` (override: `IRVE_RS485_PORT`)
- baud: `19200` (override: `IRVE_RS485_BAUD`)
- id: `1` (override: `IRVE_RS485_UNIT_ID`)
- adresse energie: `0xB02A` (override: `IRVE_RS485_ENERGY_REGISTER`)
- format serie: `8N1` (data bits 8, parity none, stop bit 1)

## Certificat TLS auto-signe

Si votre EVCE2 utilise HTTPS avec certificat auto-signe, lancez:

```bash
ALLOW_INSECURE_TLS=1 node server.js
```

Sur PowerShell:

```powershell
$env:ALLOW_INSECURE_TLS=1; node server.js
```

## Structure

- `server.js`: serveur HTTP + proxy API EVCE2
- `public/index.html`: interface dashboard
- `public/styles.css`: theme et layout responsive
- `public/api.js`: client frontend vers backend
- `public/charts.js`: creation/mise a jour des graphes
- `public/app.js`: orchestration UI + polling + transformations data
"# Testrecup" 
