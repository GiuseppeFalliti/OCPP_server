# Server OCPP 1.6J con PostgreSQL

Questo e' il server applicativo del progetto. Accetta charge point OCPP 1.6J tramite WebSocket, registra ogni messaggio, gestisce RFID e salva stato, transazioni e telemetria in PostgreSQL.

```text
Il server sarà raggiugibile dai CP su ws://34.73.197.164:9000/ID_CP
```

## Struttura del server

```text
ocpp/v16/
├── server.py                         # Processo WebSocket e handler OCPP
│   ├── main()                        # Carica .env, apre il pool PostgreSQL e il listener
│   ├── on_connect()                  # Valida protocollo e ID del CP nel path
│   └── ChargePoint                   # Gestisce una singola connessione CP
│       ├── route_message()           # Registra ogni frame in ingresso
│       ├── _send()                   # Registra ogni frame in uscita
│       ├── on_boot_notification()    # Censimento/aggiornamento del CP
│       ├── on_heartbeat()            # Aggiorna la connessione del CP
│       ├── on_status_notification()  # Stato e fault di CP/connettore
│       ├── on_authorize()            # Verifica RFID
│       ├── on_start_transaction()    # Apre una transazione
│       ├── on_meter_values()         # Salva telemetria e misure
│       ├── on_stop_transaction()     # Chiude una transazione
│       └── handler eventi tecnici    # Firmware, diagnostica, log, sicurezza
├── db/
│   ├── 001_initial.sql               # Tabelle, indici, sequenze e dati tecnici iniziali
│   ├── migrate.py                    # Comando per creare/aggiornare il database
│   └── repository.py                 # Query PostgreSQL asincrone degli handler
├── schemas/                          # Schemi JSON ufficiali OCPP 1.6J
├── call.py                           # Payload delle richieste OCPP
├── call_result.py                    # Payload delle risposte OCPP
├── datatypes.py                      # Strutture dati OCPP
├── enums.py                          # Action e valori della specifica
└── __init__.py                       # Classe base OCPP 1.6J
```

I file `ocpp/charge_point.py`, `ocpp/messages.py`, `ocpp/routing.py` e `ocpp/exceptions.py` sono il motore protocollo: ricevono frame WebSocket, validano il JSON OCPP, instradano le Action agli handler e producono le risposte.

## Configurazione e avvio

Il file `.env` nella radice viene caricato automaticamente da server e migrazione. Inserire i dati reali di PostgreSQL:

```dotenv
DATABASE_URL=postgresql://ocpp_app:password@127.0.0.1:5432/ocpp
OCPP_HOST=0.0.0.0
OCPP_PORT=9000
HEARTBEAT_INTERVAL=60
LOG_LEVEL=INFO
```

Al primo avvio creare le tabelle, poi avviare il listener:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m ocpp.v16.db.migrate
python -m ocpp.v16.server
```

Il listener e' disponibile su `ws://<ip-server>:9000/<id-cp>` e negozia obbligatoriamente il sottoprotocollo WebSocket `ocpp1.6`. Per esempio, il CP `CP001` deve collegarsi a `ws://192.168.1.10:9000/CP001` con `Sec-WebSocket-Protocol: ocpp1.6`.

## Cosa fa quando si collega un CP

1. Il server verifica che il sottoprotocollo sia `ocpp1.6` e che il path contenga un ID CP. Altrimenti chiude la connessione.
2. Ogni frame ricevuto viene salvato in `ocpp_message_log` prima dell'elaborazione; anche ogni risposta inviata viene registrata. Questo garantisce una traccia completa dei dati OCPP.
3. Al primo messaggio il CP viene creato automaticamente. Con `BootNotification` il server salva o aggiorna vendor, modello, seriali, firmware, ICCID, IMSI e contatore; crea anche rete, stazione e connettori tecnici predefiniti quando necessari.
4. Risponde a `BootNotification` con `Accepted`, ora UTC e intervallo heartbeat configurato. Un `Heartbeat` successivo aggiorna `last_heartbeat` e riceve l'ora UTC.
5. Ogni `StatusNotification` aggiorna lo stato del CP e del connettore. Uno stato `Faulted` crea o aggiorna un alert attivo; firmware, diagnostica, log e security event falliti sono anch'essi segnalati come alert.

## RFID e transazioni

### Autorizzazione

`Authorize` e `StartTransaction` usano la tabella `ocpp_rfid_tag`. Un tag e' valido esclusivamente quando:

- `tag` coincide con l'`idTag` ricevuto;
- `status` e' `Accepted`;
- `locked` e' `false`;
- `expires_at` e' vuoto oppure futuro.

Un tag non valido riceve lo stato OCPP `Invalid` e viene salvato in `ocpp_invalid_id_tag`. Per autorizzare un tag:

```sql
INSERT INTO ocpp_rfid_tag (id, tag, status)
VALUES ('rfid-001', '04AABBCCDD', 'Accepted');
```

### Avvio transazione

Quando il CP invia `StartTransaction` con un RFID valido, il server:

1. crea o recupera il connettore indicato;
2. genera un `transactionId` OCPP globale tramite una sequenza PostgreSQL;
3. salva tag, contatore iniziale, timestamp, prenotazione e connettore in `ocpp_transaction`;
4. risponde con `Accepted` e il nuovo `transactionId`.

Con RFID non valido non viene creata alcuna transazione e la risposta e' `Invalid`.

### Misure e stop

`MeterValues` salva ogni valore campionato in `ocpp_metervalues`: timestamp, misura, contesto, unita', fase, posizione e payload JSONB originale. Il dato raw consente di conservare anche misure firmate o non numeriche.

Quando arriva `StopTransaction`, il server aggiorna la transazione con contatore finale, orario di chiusura e motivo. Se `transactionData` contiene misure aggiuntive, vengono salvate come normali `MeterValues` e associate alla transazione.

## Funzioni disponibili e limiti attuali

- Gestite: BootNotification, Heartbeat, StatusNotification, Authorize, StartTransaction, MeterValues, StopTransaction, FirmwareStatusNotification, DiagnosticsStatusNotification, LogStatusNotification, SecurityEventNotification e DataTransfer.
- Le action OCPP non gestite rimangono comunque nel log raw e ricevono la risposta standard `NotImplemented`.
- Il server registra e riceve dati; i comandi remoti come `RemoteStartTransaction`, `RemoteStopTransaction`, reset e smart charging non sono ancora esposti tramite API amministrativa.

Per un uso esposto in rete pubblica usare un reverse proxy TLS, endpoint `wss://`, firewall, backup PostgreSQL e un servizio Windows/Linux che riavvii automaticamente il processo.
