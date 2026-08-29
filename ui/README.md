# Console OCPP

La UI viene compilata in `ui/dist` e servita dal processo Python sulla porta configurata da `UI_PORT`.

```bash
cd ui
npm ci
npm run build
```

Nel file `.env` del server impostare `UI_HOST`, `UI_PORT`, `UI_USERNAME` e `UI_PASSWORD`, poi riavviare PM2.
