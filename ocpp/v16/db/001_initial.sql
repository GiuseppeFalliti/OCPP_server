-- Schema PostgreSQL per il server applicativo OCPP 1.6J.
-- La migrazione e' idempotente: puo' essere eseguita piu' volte.

CREATE SEQUENCE IF NOT EXISTS ocpp_transaction_id_seq AS BIGINT;
CREATE SEQUENCE IF NOT EXISTS ocpp_chargepoint_number_seq AS BIGINT;

CREATE TABLE IF NOT EXISTS ocpp_vendor (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    ocpp_id TEXT
);

CREATE TABLE IF NOT EXISTS ocpp_chargepointmodel (
    code TEXT PRIMARY KEY,
    description TEXT NOT NULL UNIQUE,
    vendor_id TEXT NOT NULL REFERENCES ocpp_vendor(code)
);

CREATE TABLE IF NOT EXISTS ocpp_network (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS ocpp_station (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    nickname TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    address TEXT,
    zip_code TEXT,
    city TEXT,
    province TEXT,
    gps_latitude NUMERIC,
    gps_longitude NUMERIC,
    sublocation TEXT,
    description TEXT,
    visible_on_map BOOLEAN NOT NULL DEFAULT FALSE,
    accessibility TEXT NOT NULL DEFAULT 'Private',
    charge_network_id BIGINT REFERENCES ocpp_network(id),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS ocpp_cluster (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    grid_limit_amps NUMERIC NOT NULL DEFAULT 30.0,
    headroom_amps NUMERIC NOT NULL DEFAULT 2.0,
    variable_min_amps NUMERIC NOT NULL DEFAULT 6.0,
    variable_max_amps NUMERIC NOT NULL DEFAULT 16.0,
    fixed_current_amps NUMERIC NOT NULL DEFAULT 10.0,
    fixed_chargepoints JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    max_current_per_cp NUMERIC NOT NULL DEFAULT 24.0,
    min_current_per_cp NUMERIC DEFAULT 8.0
);

CREATE TABLE IF NOT EXISTS ocpp_plug (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS ocpp_chargepoint (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chargepoint_id BIGINT NOT NULL,
    name TEXT,
    nickname TEXT,
    serial_number TEXT,
    use_name_for_occp BOOLEAN NOT NULL DEFAULT FALSE,
    firmware TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    authorization_required BOOLEAN NOT NULL DEFAULT TRUE,
    authorization_key TEXT,
    iccid TEXT,
    imsi TEXT,
    sim_operator TEXT,
    sim_number TEXT,
    mac_addr TEXT,
    remote_ip INET,
    meter_sn TEXT,
    meter_type TEXT,
    status TEXT NOT NULL DEFAULT 'Unknown',
    last_status TEXT,
    last_heartbeat TIMESTAMPTZ,
    fault_reporting BOOLEAN NOT NULL DEFAULT TRUE,
    status_reporting_admins BOOLEAN NOT NULL DEFAULT FALSE,
    status_reporting_staff BOOLEAN NOT NULL DEFAULT FALSE,
    connection_reporting BOOLEAN NOT NULL DEFAULT FALSE,
    boot_reporting BOOLEAN NOT NULL DEFAULT FALSE,
    model_id TEXT NOT NULL REFERENCES ocpp_chargepointmodel(code),
    station_id BIGINT NOT NULL REFERENCES ocpp_station(id),
    real_station_id TEXT,
    chargepointorigin TEXT NOT NULL UNIQUE,
    vendor_id TEXT REFERENCES ocpp_vendor(code),
    allowany BOOLEAN NOT NULL DEFAULT FALSE,
    cluster_id BIGINT REFERENCES ocpp_cluster(id) ON DELETE SET NULL,
    plug_and_charge_supported BOOLEAN NOT NULL DEFAULT FALSE,
    supports_load_balancer BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    routing_mode INTEGER NOT NULL DEFAULT 0,
    UNIQUE (station_id, chargepoint_id)
);

CREATE TABLE IF NOT EXISTS ocpp_connector (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connector_id INTEGER NOT NULL,
    nickname TEXT,
    status TEXT NOT NULL DEFAULT 'Unknown',
    "errorCode" TEXT,
    "vendorErrorCode" TEXT,
    fmt TEXT NOT NULL DEFAULT 'Unknown',
    current_max INTEGER NOT NULL DEFAULT 0,
    power_max INTEGER NOT NULL DEFAULT 0,
    power_type TEXT NOT NULL DEFAULT 'Unknown',
    firmware TEXT,
    bt_mac_address TEXT,
    last_power_read TIMESTAMPTZ,
    last_energy_read TIMESTAMPTZ,
    stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    chargepoint_id BIGINT NOT NULL REFERENCES ocpp_chargepoint(id),
    plug_type_id TEXT NOT NULL REFERENCES ocpp_plug(code),
    station_id BIGINT NOT NULL REFERENCES ocpp_station(id),
    station TEXT,
    chargepoint TEXT,
    plug_type TEXT,
    real_station_id TEXT,
    last_heartbeat TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (station_id, chargepoint_id, connector_id)
);

CREATE TABLE IF NOT EXISTS ocpp_rfid_tag (
    id TEXT PRIMARY KEY,
    tag TEXT NOT NULL UNIQUE,
    owner BIGINT,
    status TEXT,
    scope TEXT,
    chargepoint BIGINT REFERENCES ocpp_chargepoint(id),
    connector BIGINT REFERENCES ocpp_connector(id),
    expires_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    targa TEXT,
    num_tag TEXT,
    esterni BOOLEAN,
    vettura BOOLEAN NOT NULL DEFAULT FALSE,
    furgone BOOLEAN,
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    utente TEXT
);

CREATE TABLE IF NOT EXISTS ocpp_transaction (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transaction_id BIGINT NOT NULL UNIQUE,
    last_uuid TEXT,
    id_tag TEXT,
    meter_start BIGINT NOT NULL,
    meter_stop BIGINT,
    ts_start TIMESTAMPTZ NOT NULL,
    ts_stop TIMESTAMPTZ,
    ts_last_meter TIMESTAMPTZ,
    last_meter BIGINT,
    reason TEXT,
    reservation_id BIGINT,
    connector_id BIGINT NOT NULL REFERENCES ocpp_connector(id) ON DELETE CASCADE,
    user_id BIGINT
);

CREATE TABLE IF NOT EXISTS ocpp_metervalues (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    charge_point_id BIGINT REFERENCES ocpp_chargepoint(id) ON DELETE SET NULL,
    ocpp_identity TEXT NOT NULL,
    connector_id INTEGER NOT NULL,
    transaction_db_id BIGINT REFERENCES ocpp_transaction(id) ON DELETE SET NULL,
    ocpp_transaction_pk BIGINT,
    sampled_at TIMESTAMPTZ NOT NULL,
    measurand TEXT,
    context TEXT,
    unit TEXT,
    value NUMERIC,
    value_text TEXT NOT NULL,
    format TEXT,
    phase TEXT,
    location TEXT,
    raw JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ocpp_message_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chargepointorigin TEXT NOT NULL,
    message_type TEXT NOT NULL,
    body TEXT NOT NULL,
    way TEXT NOT NULL CHECK (way IN ('incoming', 'outgoing')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ocpp_invalid_id_tag (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ocpp_identity TEXT,
    chargepoint_id BIGINT REFERENCES ocpp_chargepoint(id) ON DELETE SET NULL,
    connector_id BIGINT,
    id_tag TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    note TEXT
);

CREATE TABLE IF NOT EXISTS ocpp_alertlog (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chargepointorigin TEXT REFERENCES ocpp_chargepoint(chargepointorigin) ON DELETE SET NULL,
    connectorid BIGINT REFERENCES ocpp_connector(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning',
    state TEXT NOT NULL DEFAULT 'unhandled',
    title TEXT,
    status_text TEXT,
    error_code TEXT,
    vendor_error_code TEXT,
    payload JSONB,
    occurred_at TIMESTAMPTZ NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    dismissed BOOLEAN,
    dismissed_by BIGINT,
    notes TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    network_id BIGINT REFERENCES ocpp_network(id),
    station_id BIGINT REFERENCES ocpp_station(id),
    object_class TEXT,
    object_id BIGINT,
    level TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    webhook_last_sent_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ocpp_message_log_identity_created
    ON ocpp_message_log (chargepointorigin, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ocpp_transaction_connector_open
    ON ocpp_transaction (connector_id) WHERE ts_stop IS NULL;
CREATE INDEX IF NOT EXISTS idx_ocpp_metervalues_identity_sampled
    ON ocpp_metervalues (ocpp_identity, sampled_at DESC);
CREATE INDEX IF NOT EXISTS idx_ocpp_connector_chargepoint
    ON ocpp_connector (chargepoint_id, connector_id);
CREATE INDEX IF NOT EXISTS idx_ocpp_alertlog_active
    ON ocpp_alertlog (chargepointorigin, event_type) WHERE active;

INSERT INTO ocpp_network (name, slug)
VALUES ('Auto-created network', 'auto-created')
ON CONFLICT (name) DO NOTHING;
INSERT INTO ocpp_vendor (code, name, ocpp_id)
VALUES ('unknown', 'Unknown vendor', 'unknown')
ON CONFLICT (code) DO NOTHING;
INSERT INTO ocpp_chargepointmodel (code, description, vendor_id)
VALUES ('unknown', 'Unknown model', 'unknown')
ON CONFLICT (code) DO NOTHING;
INSERT INTO ocpp_plug (code, name)
VALUES ('UNKNOWN', 'Unknown connector type')
ON CONFLICT (code) DO NOTHING;
