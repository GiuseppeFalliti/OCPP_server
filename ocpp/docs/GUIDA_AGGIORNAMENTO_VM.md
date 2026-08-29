# Aggiornamento del server OCPP sulla VM Google Cloud

## Posizione del progetto

Il repository clonato sulla VM si trova qui:

```text
/opt/ocpp-server/app
```

Il servizio OCPP viene eseguito dall'utente di sistema `ocpp`, usa l'ambiente virtuale `/opt/ocpp-server/app/.venv` ed è gestito da PM2 con il nome `ocpp-server`.

La configurazione riservata del server è nel file:

```text
/opt/ocpp-server/app/.env
```

Il file `.env` non deve essere committato nel repository e non viene sovrascritto da `git pull`.

Per abilitare la console web, aggiungere inoltre:

```env
UI_HOST=0.0.0.0
UI_PORT=8080
```

## Log JSON locali

Il server conserva una copia giornaliera degli eventi OCPP in:

```text
/opt/ocpp-server/app/ocpp/Logs/<seriale>/YYYY-MM-DD.json
```

Ogni riga è un oggetto JSON indipendente (JSON Lines). I log vengono trattenuti per 30 giorni. Facoltativamente, nel file `.env` è possibile impostare `OCPP_LOG_DIR` per usare un percorso diverso e `OCPP_LOG_RETENTION_DAYS` per cambiare il numero di giorni di conservazione.

## Aggiornare il codice

Collegarsi alla VM via SSH, quindi eseguire questi comandi. Il controllo iniziale evita di sovrascrivere eventuali modifiche locali non ancora salvate.

> Eseguire l'intero blocco, incluso `sudo -u ocpp -H bash -c`. Non lanciare i comandi interni come utente SSH personale: il repository, il virtualenv e il processo PM2 appartengono all'utente di servizio `ocpp`.

```bash
sudo -u ocpp -H bash -c '
set -e
cd /opt/ocpp-server/app
git status --short
git pull --ff-only origin main
.venv/bin/python -m pip install -e .
.venv/bin/python -m ocpp.v16.db.migrate
cd ui && npm ci && npm run build && cd ..
pm2 restart ocpp-server --update-env
pm2 save
'
```

Il comando `git pull --ff-only` aggiorna esclusivamente quando non deve creare un merge automatico. Se `git status --short` mostra file modificati oppure il pull si interrompe, non forzare l'aggiornamento: verificare prima le modifiche presenti sulla VM.

`pip install -e .` aggiorna le dipendenze Python dichiarate dal progetto. La migrazione applica solo gli script SQL non ancora eseguiti. Il riavvio PM2 carica il nuovo codice e mantiene il processo configurato per l'avvio automatico.

> Se il branch principale del repository si chiama diversamente da `main`, sostituire `main` nel comando con il nome corretto, ad esempio `master`.

## Verificare il servizio

```bash
sudo -u ocpp -H pm2 status
sudo -u ocpp -H pm2 logs ocpp-server
```

Nei log, dopo un avvio riuscito, deve comparire una riga simile a:

```text
Server OCPP 1.6J in ascolto su 0.0.0.0:9000
```

Per uscire dalla visualizzazione continua dei log, premere `Ctrl+C`.

Per controllare che la porta sia in ascolto sulla VM:

```bash
sudo ss -ltnp | grep :9000
```

L'output atteso contiene `0.0.0.0:9000`.

La console è disponibile su `http://IP_VM:8080`. Creare una regola firewall Google Cloud TCP `8080`, limitata agli IP amministrativi autorizzati.

## Riavviare senza aggiornare il codice

```bash
sudo -u ocpp -H pm2 restart ocpp-server --update-env
sudo -u ocpp -H pm2 save
```

## Primo avvio, se il processo PM2 non esiste

Usare questo comando solo se `pm2 status` non mostra `ocpp-server`:

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
