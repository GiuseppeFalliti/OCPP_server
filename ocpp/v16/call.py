from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from ocpp.v16 import datatypes, enums

# La maggior parte dei tipi di messaggio CALL puo' provenire da una sola fonte:
# un Charge Point oppure il Central System, non da entrambi.
#
# Prendiamo come esempio la CALL per l'azione ChangeConfiguration. Questo tipo di
# CALL puo' essere inviato solo dal Central System alla Charging Station, non viceversa.
#
# Per alcuni tipi di CALL vale il contrario, ad esempio la CALL dell'azione
# BootNotification: puo' provenire solo da un Charge Point ed essere inviata
# a un Central System.
#
# L'unica CALL che puo' provenire sia dal Central System sia dal Charge Point
# e' quella dell'azione DataTransfer.

# La sezione di classi seguente riguarda le CALL che fluiscono dal Central System
# al Charge Point.


@dataclass
class CancelReservation:
    reservation_id: int


@dataclass
class CertificateSigned:
    certificate_chain: str


@dataclass
class ChangeAvailability:
    connector_id: int
    type: enums.AvailabilityType


@dataclass
class ChangeConfiguration:
    key: str
    value: str


@dataclass
class ClearCache:
    pass


@dataclass
class ClearChargingProfile:
    id: Optional[int] = None
    connector_id: Optional[int] = None
    charging_profile_purpose: Optional[enums.ChargingProfilePurposeType] = None
    stack_level: Optional[int] = None


@dataclass
class DeleteCertificate:
    certificate_hash_data: Dict


@dataclass
class ExtendedTriggerMessage:
    requested_message: enums.MessageTrigger
    connector_id: Optional[int] = None


@dataclass
class GetCompositeSchedule:
    connector_id: int
    duration: int
    charging_rate_unit: Optional[enums.ChargingRateUnitType] = None


@dataclass
class GetConfiguration:
    key: Optional[List] = None


@dataclass
class GetDiagnostics:
    location: str
    retries: Optional[int] = None
    retry_interval: Optional[int] = None
    start_time: Optional[str] = None
    stop_time: Optional[str] = None


@dataclass
class GetInstalledCertificateIds:
    certificate_type: enums.CertificateUse


@dataclass
class GetLocalListVersion:
    pass


@dataclass
class GetLog:
    log: Dict
    log_type: enums.Log
    request_id: int
    retries: Optional[int] = None
    retry_interval: Optional[int] = None


@dataclass
class InstallCertificate:
    certificate_type: enums.CertificateUse
    certificate: str


@dataclass
class RemoteStartTransaction:
    id_tag: str
    connector_id: Optional[int] = None
    charging_profile: Optional[Union[Dict, datatypes.ChargingProfile]] = None


@dataclass
class RemoteStopTransaction:
    transaction_id: int


@dataclass
class ReserveNow:
    connector_id: int
    expiry_date: str
    id_tag: str
    reservation_id: int
    parent_id_tag: Optional[str] = None


@dataclass
class Reset:
    type: enums.ResetType


@dataclass
class SendLocalList:
    list_version: int
    update_type: enums.UpdateType
    local_authorization_list: List = field(default_factory=list)


@dataclass
class SetChargingProfile:
    connector_id: int
    cs_charging_profiles: Union[datatypes.ChargingProfile, Dict]


@dataclass
class SignedUpdateFirmware:
    request_id: int
    firmware: Dict
    retries: Optional[int] = None
    retry_interval: Optional[int] = None


@dataclass
class TriggerMessage:
    requested_message: enums.MessageTrigger
    connector_id: Optional[int] = None


@dataclass
class UnlockConnector:
    connector_id: int


@dataclass
class UpdateFirmware:
    location: str
    retrieve_date: str
    retries: Optional[int] = None
    retry_interval: Optional[int] = None


# Le CALL che fluiscono dal Charge Point al Central System sono elencate nella
# parte finale di questo modulo.


@dataclass
class Authorize:
    id_tag: str


@dataclass
class BootNotification:
    charge_point_model: str
    charge_point_vendor: str
    charge_box_serial_number: Optional[str] = None
    charge_point_serial_number: Optional[str] = None
    firmware_version: Optional[str] = None
    iccid: Optional[str] = None
    imsi: Optional[str] = None
    meter_serial_number: Optional[str] = None
    meter_type: Optional[str] = None


@dataclass
class DiagnosticsStatusNotification:
    status: enums.DiagnosticsStatus


@dataclass
class FirmwareStatusNotification:
    status: enums.FirmwareStatus


@dataclass
class Heartbeat:
    pass


@dataclass
class LogStatusNotification:
    status: enums.UploadLogStatus
    request_id: int


@dataclass
class MeterValues:
    connector_id: int
    meter_value: List = field(default_factory=list)
    transaction_id: Optional[int] = None


@dataclass
class SecurityEventNotification:
    type: str
    timestamp: str
    tech_info: Optional[str]


@dataclass
class SignCertificate:
    csr: str


@dataclass
class SignedFirmwareStatusNotification:
    status: enums.FirmwareStatus
    request_id: int


@dataclass
class StartTransaction:
    connector_id: int
    id_tag: str
    meter_start: int
    timestamp: str
    reservation_id: Optional[int] = None


@dataclass
class StopTransaction:
    meter_stop: int
    timestamp: str
    transaction_id: int
    reason: Optional[enums.Reason] = None
    id_tag: Optional[str] = None
    transaction_data: Optional[List] = None


@dataclass
class StatusNotification:
    connector_id: int
    error_code: enums.ChargePointErrorCode
    status: enums.ChargePointStatus
    timestamp: Optional[str] = None
    info: Optional[str] = None
    vendor_id: Optional[str] = None
    vendor_error_code: Optional[str] = None


# La CALL DataTransfer puo' essere inviata sia dal Central System sia dal Charge Point.


@dataclass
class DataTransfer:
    vendor_id: str
    message_id: Optional[str] = None
    data: Optional[str] = None
