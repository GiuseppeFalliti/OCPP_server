-- Compatibilità per database creati prima delle colonne operative del server.
-- ALTER TABLE ... IF NOT EXISTS rende la migrazione sicura anche su installazioni nuove.

ALTER TABLE ocpp_chargepoint
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'Unknown',
    ADD COLUMN IF NOT EXISTS last_status TEXT,
    ADD COLUMN IF NOT EXISTS last_heartbeat TIMESTAMPTZ;

ALTER TABLE ocpp_connector
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'Unknown',
    ADD COLUMN IF NOT EXISTS "errorCode" TEXT,
    ADD COLUMN IF NOT EXISTS "vendorErrorCode" TEXT,
    ADD COLUMN IF NOT EXISTS last_heartbeat TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
