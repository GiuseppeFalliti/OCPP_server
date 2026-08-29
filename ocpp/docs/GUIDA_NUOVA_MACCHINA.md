# Installazione del server OCPP su una nuova macchina

## 1. Prerequisiti

La macchina deve avere PostgreSQL raggiungibile, Python 3.11 o superiore, Git, Node.js con npm e PM2.

Su Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip postgresql-client nodejs npm
sudo npm install -g pm2
```

## 2. Utente e repository

```bash
sudo useradd --system --create-home --home-dir /opt/ocpp-server --shell /usr/sbin/nologin ocpp
sudo -u ocpp -H git clone https://github.com/GiuseppeFalliti/OCPP_server.git /opt/ocpp-server/app
sudo -u ocpp -H bash -c '
set -e
cd /opt/ocpp-server/app
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
cd ui
npm ci
npm run build
'
```

## 3. Configurazione

Creare `/opt/ocpp-server/app/.env` come utente `ocpp`:

```bash
sudo -u ocpp -H nano /opt/ocpp-server/app/.env
```

Esempio per PostgreSQL locale:

```env
DATABASE_URL=postgresql://UTENTE:PASSWORD@127.0.0.1:5432/ocpp
OCPP_HOST=0.0.0.0
OCPP_PORT=9000
HEARTBEAT_INTERVAL=60
LOG_LEVEL=INFO
UI_HOST=0.0.0.0
UI_PORT=8080
OCPP_LOG_RETENTION_DAYS=30
```

Se PostgreSQL è remoto, sostituire `127.0.0.1` con IP o hostname del database e autorizzare l'IP della nuova macchina in `pg_hba.conf` del server PostgreSQL.

Proteggere il file:

```bash
sudo chown ocpp:ocpp /opt/ocpp-server/app/.env
sudo chmod 600 /opt/ocpp-server/app/.env
```

## 4. Database e avvio

La migrazione crea/aggiorna le tabelle e i dati tecnici predefiniti:

```bash
sudo -u ocpp -H bash -c '
set -e
cd /opt/ocpp-server/app
.venv/bin/python -m ocpp.v16.db.migrate
pm2 start ocpp/v16/server.py \
  --name ocpp-server \
  --interpreter /opt/ocpp-server/app/.venv/bin/python \
  --cwd /opt/ocpp-server/app \
  --time \
  --restart-delay 5000
pm2 save
'
```

Configurare anche il riavvio automatico; PM2 stamperà un comando `sudo` da eseguire:

```bash
sudo -u ocpp -H pm2 startup systemd -u ocpp --hp /opt/ocpp-server
sudo -u ocpp -H pm2 save
```

## 5. Porte e firewall

| Porta | Protocollo | Uso | Esposizione |
| --- | --- | --- | --- |
| 9000 | TCP / WebSocket | Endpoint OCPP 1.6J per i Charge Point | Consentire solo IP dei CP quando possibile |
| 8080 | TCP / HTTP | Console React e API amministrativa | Consentire solo IP amministrativi o usare VPN/reverse proxy HTTPS |
| 5432 | TCP / PostgreSQL | Database | Non esporre pubblicamente; consentire solo server OCPP e amministratori autorizzati |

Un CP usa un URL nel formato:

```text
ws://IP_O_HOST_SERVER:9000/IDENTITA_CP
```

La console è disponibile su:

```text
http://IP_O_HOST_SERVER:8080
```

## 6. Charge Point reali

Il server supporta OCPP 1.6J su WebSocket con sottoprotocollo `ocpp1.6`. Al Boot crea o aggiorna l'anagrafica, registra heartbeat, stati, connettori, transazioni, meter values e frame raw in PostgreSQL e nei file JSON giornalieri.

`Authorize` e `StartTransaction` accettano solo RFID presenti in `ocpp_rfid_tag` con `status = 'Accepted'`, `locked = false` e non scaduti. La console invia `RemoteStartTransaction` e `RemoteStopTransaction` solo a CP connessi; il CP deve supportare e accettare tali comandi.

Il server espone attualmente `ws://`, non `wss://`. Se il CP reale richiede TLS o un Security Profile OCPP con certificati, installare un reverse proxy HTTPS/WSS con certificato valido prima di esporlo in produzione.

## 7. Controlli operativi

```bash
sudo -u ocpp -H pm2 status
sudo -u ocpp -H pm2 logs ocpp-server
sudo ss -ltnp | grep -E ':9000|:8080'
sudo -u ocpp -H find /opt/ocpp-server/app/ocpp/Logs -type f -name '*.json'
```
