from dataclasses import dataclass
from typing import Dict, List, Optional

from ocpp.v16 import datatypes, enums

# La maggior parte dei tipi di messaggio CALLRESULT puo' provenire da una sola fonte:
# un Charge Point oppure il Central System, non da entrambi.
#
# Prendiamo come esempio il CALLRESULT dell'azione Authorize. Questo tipo di
# CALLRESULT puo' essere inviato solo dal Central System alla Charging Station,
# non viceversa.
#
# Per alcuni tipi di CALLRESULT vale il contrario, ad esempio il CALLRESULT
# dell'azione Reset: puo' provenire solo da un Charge Point ed essere inviato
# a un Central System.
#
# L'unico CALLRESULT che puo' provenire sia dal Central System sia dal Charge Point
# e' quello dell'azione DataTransfer.

# La sezione di classi seguente riguarda i CALLRESULT che fluiscono dal Central
# System al Charge Point.


@dataclass
class Authorize:
    id_tag_info: datatypes.IdTagInfo


@dataclass
class BootNotification:
    current_time: str
    interval: int
    status: enums.RegistrationStatus


@dataclass
class DiagnosticsStatusNotification:
    pass


@dataclass
class FirmwareStatusNotification:
    pass


@dataclass
class Heartbeat:
    current_time: str


@dataclass
class LogStatusNotification:
    pass


@dataclass
class SecurityEventNotification:
    pass


@dataclass
class SignCertificate:
    status: enums.GenericStatus


@dataclass
class MeterValues:
    pass


@dataclass
class StartTransaction:
    transaction_id: int
    id_tag_info: datatypes.IdTagInfo


@dataclass
class StatusNotification:
    pass


@dataclass
class StopTransaction:
    id_tag_info: Optional[datatypes.IdTagInfo] = None


# I CALLRESULT che fluiscono dal Charge Point al Central System sono elencati
# nella parte finale di questo modulo.


@dataclass
class CancelReservation:
    status: enums.CancelReservationStatus


@dataclass
class CertificateSigned:
    status: enums.CertificateSignedStatus


@dataclass
class ChangeAvailability:
    status: enums.AvailabilityStatus


@dataclass
class ChangeConfiguration:
    status: enums.ConfigurationStatus


@dataclass
class ClearCache:
    status: enums.ClearCacheStatus


@dataclass
class ClearChargingProfile:
    status: enums.ClearChargingProfileStatus


@dataclass
class DeleteCertificate:
    status: enums.DeleteCertificateStatus


@dataclass
class ExtendedTriggerMessage:
    status: enums.TriggerMessageStatus


@dataclass
class GetInstalledCertificateIds:
    status: enums.GetInstalledCertificateStatus
    certificate_hash_data: Optional[List] = None


@dataclass
class GetCompositeSchedule:
    status: enums.GetCompositeScheduleStatus
    connector_id: Optional[int] = None
    schedule_start: Optional[str] = None
    charging_schedule: Optional[Dict] = None


@dataclass
class GetConfiguration:
    configuration_key: Optional[List] = None
    unknown_key: Optional[List] = None


@dataclass
class GetDiagnostics:
    file_name: Optional[str] = None


@dataclass
class GetLocalListVersion:
    list_version: int


@dataclass
class GetLog:
    status: enums.LogStatus
    filename: Optional[str] = None


@dataclass
class InstallCertificate:
    status: enums.CertificateStatus


@dataclass
class RemoteStartTransaction:
    status: enums.RemoteStartStopStatus


@dataclass
class RemoteStopTransaction:
    status: enums.RemoteStartStopStatus


@dataclass
class ReserveNow:
    status: enums.ReservationStatus


@dataclass
class Reset:
    status: enums.ResetStatus


@dataclass
class SendLocalList:
    status: enums.UpdateStatus


@dataclass
class SetChargingProfile:
    status: enums.ChargingProfileStatus


@dataclass
class SignedFirmwareStatusNotification:
    pass


@dataclass
class SignedUpdateFirmware:
    status: enums.UpdateFirmwareStatus


@dataclass
class TriggerMessage:
    status: enums.TriggerMessageStatus


@dataclass
class UnlockConnector:
    status: enums.UnlockStatus


@dataclass
class UpdateFirmware:
    pass


# Il CALLRESULT DataTransfer puo' essere inviato sia dal Central System sia dal
# Charge Point.


@dataclass
class DataTransfer:
    status: enums.DataTransferStatus
    data: Optional[str] = None
