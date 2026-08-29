"""Modulo con classi che modellano i tipi di messaggio OCPP.

Contiene anche funzioni di supporto per impacchettare e decomprimere messaggi.
"""

from __future__ import annotations

import asyncio
import decimal
import json
import os
from dataclasses import asdict, is_dataclass
from typing import Callable, Dict, Union

from jsonschema import Draft4Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError

from ocpp.exceptions import (
    FormatViolationError,
    NotImplementedError,
    OCPPError,
    PropertyConstraintViolationError,
    ProtocolError,
    TypeConstraintViolationError,
    UnknownCallErrorCodeError,
    ValidationError,
)

_validators: Dict[str, Draft4Validator] = {}

ASYNC_VALIDATION = True


class _DecimalEncoder(json.JSONEncoder):
    """Codifica valori `decimal.Decimal` usando un solo decimale.

    Serve un encoder personalizzato poiche' `json.dumps()` non puo' codificare
    un valore di tipo decimal.Decimal; altrimenti solleva TypeError:

        >>> import decimal
        >>> import json
        >>> >>> json.dumps(decimal.Decimal(3))
        Traceback (most recent call last):
          File "<stdin>", line 1, in <module>
          File "/home/developer/.pyenv/versions/3.7.0/lib/python3.7/json/__init__.py", line 231, in dumps  # noqa  # Ignora la lunghezza della riga nell'esempio.
            return _default_encoder.encode(obj)
          File "/home/developer/.pyenv/versions/3.7.0/lib/python3.7/json/encoder.py", line 199, in encode
            chunks = self.iterencode(o, _one_shot=True)
          File "/home/developer/.pyenv/versions/3.7.0/lib/python3.7/json/encoder.py", line 257, in iterencode
            return _iterencode(o, 0)
          File "/home/developer/.pyenv/versions/3.7.0/lib/python3.7/json/encoder.py", line 179, in default
            raise TypeError(f'Object of type {o.__class__.__name__} '
        TypeError: Object of type Decimal is not JSON serializable

    Questo problema si evita usando un encoder personalizzato.

    """

    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float("%.1f" % obj)
        try:
            return json.JSONEncoder.default(self, obj)
        except TypeError as e:
            try:
                return obj.to_json()
            except AttributeError:
                raise e


class MessageType:
    """Numero che identifica i diversi tipi di messaggio OCPP."""

    #: Call identifica una richiesta.
    Call = 2

    #: CallResult identifica una risposta riuscita.
    CallResult = 3

    #: CallError identifica una risposta con errore.
    CallError = 4


def unpack(msg):
    """
    Decomprime un messaggio in un Call, CallError o CallResult.
    """
    try:
        msg = json.loads(msg)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise FormatViolationError(
            details={"cause": "Message is not valid JSON", "ocpp_message": msg}
        )

    if not isinstance(msg, list):
        raise ProtocolError(
            details={
                "cause": (
                    "OCPP message hasn't the correct format. It "
                    f"should be a list, but got '{type(msg)}' "
                    "instead"
                )
            }
        )

    for cls in [Call, CallResult, CallError]:
        try:
            if msg[0] == cls.message_type_id:
                return cls(*msg[1:])
        except IndexError:
            raise ProtocolError(
                details={"cause": "Message does not contain MessageTypeId"}
            )
        except TypeError:
            raise ProtocolError(details={"cause": "Message is missing elements."})

    raise PropertyConstraintViolationError(
        details={"cause": f"MessageTypeId '{msg[0]}' isn't valid"}
    )


def pack(msg):
    """
    Restituisce la rappresentazione JSON di un Call, CallError o CallResult.

    Si limita a chiamare il metodo `to_json()` del messaggio; esiste soprattutto
    per completare la funzione `unpack` di questo modulo.
    """
    return msg.to_json()


def get_validator(
    message_type_id: int, action: str, ocpp_version: str, parse_float: Callable = float
) -> Draft4Validator:
    """
    Legge lo schema dal disco e restituisce un `Draft4Validator`. Le istanze
    vengono mantenute in cache per ragioni di prestazioni.

    L'argomento `parse_float` imposta il metodo di conversione dei float. Deve
    essere una callable che accetta un argomento. Il valore predefinito e'
    `float()`, ma alcuni schemi richiedono `decimal.Decimal()`.
    """
    if ocpp_version != "1.6":
        raise ValueError

    schemas_dir = "v" + ocpp_version.replace(".", "")

    schema_name = action
    if message_type_id == MessageType.CallResult:
        schema_name += "Response"
    cache_key = schema_name + "_" + ocpp_version
    if cache_key in _validators:
        return _validators[cache_key]

    dir, _ = os.path.split(os.path.realpath(__file__))
    relative_path = f"{schemas_dir}/schemas/{schema_name}.json"
    path = os.path.join(dir, relative_path)

    with open(path, "r", encoding="utf-8-sig") as f:
        data = f.read()
        validator = Draft4Validator(json.loads(data, parse_float=parse_float))
        _validators[cache_key] = validator

    return _validators[cache_key]


async def validate_payload(message: Union[Call, CallResult], ocpp_version: str) -> None:
    """Valida il payload del messaggio usando gli schemi JSON."""
    if ASYNC_VALIDATION:
        await asyncio.get_event_loop().run_in_executor(
            None, _validate_payload, message, ocpp_version
        )
    else:
        _validate_payload(message, ocpp_version)


def _validate_payload(message: Union[Call, CallResult], ocpp_version: str) -> None:
    if type(message) not in [Call, CallResult]:
        raise ValidationError(
            "Payload can't be validated because message "
            f"type. It's '{type(message)}', but it should "
            "be either 'Call'  or 'CallResult'."
        )

    try:
        # Gli schedule OCPP 1.6 hanno campi di tipo float. Lo schema JSON
        # definisce per tali campi una precisione di 1 decimale: 21.4 e' valido,
        # mentre 4.11 non lo e'.
        #
        # Il problema e' che la rappresentazione interna di Python di 21.4 puo'
        # avere piu' di 1 decimale, ad esempio 21.399999999999995. Questo farebbe
        # fallire la validazione nonostante il payload sia corretto. E' un problema
        # noto di jsonschema, vedere:
        # https://github.com/Julian/jsonschema/issues/247
        #
        # Il problema si risolve usando per i float un parser diverso da quello
        # predefinito.
        #
        # Sia lo schema sia il payload devono essere analizzati con il parser
        # alternativo per i float.
        if ocpp_version == "1.6" and (
            (
                isinstance(message, Call)
                and message.action in ["SetChargingProfile", "RemoteStartTransaction"]
            )
            or (
                isinstance(message, CallResult)
                and message.action == "GetCompositeSchedule"
            )
        ):
            validator = get_validator(
                message.message_type_id,
                message.action,
                ocpp_version,
                parse_float=decimal.Decimal,
            )

            message.payload = json.loads(
                json.dumps(message.payload), parse_float=decimal.Decimal
            )
        else:
            validator = get_validator(
                message.message_type_id, message.action, ocpp_version
            )
    except (OSError, json.JSONDecodeError):
        raise NotImplementedError(
            details={"cause": f"Failed to validate action: {message.action}"}
        )

    try:
        validator.validate(message.payload)
    except SchemaValidationError as e:
        if e.validator == "type":
            raise TypeConstraintViolationError(
                details={"cause": e.message, "ocpp_message": message}
            )
        elif e.validator == "additionalProperties":
            raise FormatViolationError(
                details={"cause": e.message, "ocpp_message": message}
            )
        elif e.validator == "required":
            raise ProtocolError(details={"cause": e.message})

        elif e.validator == "maxLength":
            raise TypeConstraintViolationError(
                details={"cause": e.message, "ocpp_message": message}
            ) from e
        else:
            raise FormatViolationError(
                details={
                    "cause": f"Payload '{message.payload}' for action "
                    f"'{message.action}' is not valid: {e}",
                    "ocpp_message": message,
                }
            )


class Call:
    """Una Call avvia una sequenza richiesta/risposta.
    Sia i central system sia i charge point possono inviare questo messaggio.

    Dalla specifica:

        Una Call ha sempre 4 elementi: MessageTypeId, UniqueId, una specifica
        Action richiesta dall'altra parte e un payload con gli argomenti della
        Action. La sintassi e':

            [<MessageTypeId>, "<UniqueId>", "<Action>", {<Payload>}]

        ...

        Per esempio, una richiesta BootNotification puo' essere:

            [2,
             "19223201",
             "BootNotification",
             {
              "chargePointVendor": "VendorX",
              "chargePointModel": "SingleSocketCharger"
             }
            ]
    """

    message_type_id = 2

    def __init__(self, unique_id, action, payload):
        self.unique_id = unique_id
        self.action = action
        self.payload = payload

        if is_dataclass(payload):
            self.payload = asdict(payload)

    def to_json(self):
        """Restituisce una rappresentazione JSON valida dell'istanza."""
        return json.dumps(
            [
                self.message_type_id,
                self.unique_id,
                self.action,
                self.payload,
            ],
            # Per impostazione predefinita json.dumps() aggiunge uno spazio dopo ogni
            # separatore; impostando il separatore manualmente lo si evita.
            separators=(",", ":"),
            cls=_DecimalEncoder,
        )

    def create_call_result(self, payload):
        call_result = CallResult(self.unique_id, payload)
        call_result.action = self.action
        return call_result

    def create_call_error(self, exception):
        error_code = "InternalError"
        error_description = "An unexpected error occurred."
        error_details = {}

        if isinstance(exception, OCPPError):
            error_code = exception.code
            error_description = exception.description
            error_details = exception.details

        return CallError(
            self.unique_id,
            error_code,
            error_description,
            error_details,
        )

    def __repr__(self):
        return (
            f"<Call - unique_id={self.unique_id}, action={self.action}, "
            f"payload={self.payload}>"
        )


class CallResult:
    """
    Un CallResult indica che una Call e' stata gestita correttamente.

    Dalla specifica:

        Un CallResult ha sempre 3 elementi: MessageTypeId, UniqueId e un payload
        contenente la risposta alla Action della Call originale. La sintassi e':

            [<MessageTypeId>, "<UniqueId>", {<Payload>}]

        ...

        Per esempio, una risposta BootNotification puo' essere:

            [3,
             "19223201",
             {
              "status":"Accepted",
              "currentTime":"2013-02-01T20:53:32.486Z",
              "heartbeatInterval":300
             }
            ]

    """

    message_type_id = 3

    def __init__(self, unique_id, payload, action=None):
        self.unique_id = unique_id
        self.payload = payload

        # Formalmente un'azione non e' richiesta in un CallResult, ma serve per
        # validare il messaggio.
        self.action = action

    def to_json(self):
        return json.dumps(
            [
                self.message_type_id,
                self.unique_id,
                self.payload,
            ],
            # Per impostazione predefinita json.dumps() aggiunge uno spazio dopo ogni
            # separatore; impostando il separatore manualmente lo si evita.
            separators=(",", ":"),
            cls=_DecimalEncoder,
        )

    def __repr__(self):
        return (
            f"<CallResult - unique_id={self.unique_id}, "
            f"action={self.action}, "
            f"payload={self.payload}>"
        )


class CallError:
    """
    Un CallError e' una risposta a una Call che segnala un errore.

    Dalla specifica:

        Un CallError ha sempre 5 elementi: MessageTypeId e UniqueId, una stringa
        errorCode, una stringa errorDescription e un oggetto errorDetails.

        La sintassi di una Call e':

            [<MessageTypeId>, "<UniqueId>", "<errorCode>", "<errorDescription>", {<errorDetails>}] # noqa  # Ignora la lunghezza della riga nell'esempio.
    """

    message_type_id = 4

    def __init__(self, unique_id, error_code, error_description, error_details=None):
        self.unique_id = unique_id
        self.error_code = error_code
        self.error_description = error_description
        self.error_details = error_details

    def to_json(self):
        return json.dumps(
            [
                self.message_type_id,
                self.unique_id,
                self.error_code,
                self.error_description,
                self.error_details,
            ],
            # Per impostazione predefinita json.dumps() aggiunge uno spazio dopo ogni
            # separatore; impostando il separatore manualmente lo si evita.
            separators=(",", ":"),
            cls=_DecimalEncoder,
        )

    def to_exception(self):
        """Restituisce l'eccezione corrispondente al CallError."""
        for error in OCPPError.__subclasses__():
            if error.code == self.error_code:
                return error(
                    description=self.error_description, details=self.error_details
                )

        raise UnknownCallErrorCodeError(
            f"Error code '{self.error_code}' is not defined by the"
            " OCPP specification"
        )

    def __repr__(self):
        return (
            f"<CallError - unique_id={self.unique_id}, "
            f"error_code={self.error_code}, "
            f"error_description={self.error_description}, "
            f"error_details={self.error_details}>"
        )
