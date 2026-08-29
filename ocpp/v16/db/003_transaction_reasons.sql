-- Origine operativa distinta dal motivo OCPP tecnico in ocpp_transaction.reason.
ALTER TABLE ocpp_transaction
    ADD COLUMN IF NOT EXISTS start_reason TEXT NOT NULL DEFAULT 'LocalStart',
    ADD COLUMN IF NOT EXISTS stop_reason TEXT;
