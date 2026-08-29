import asyncio
import inspect
import logging
import re
import time
import uuid
from dataclasses import Field, asdict, is_dataclass
from typing import Any, Dict, List, Optional, Union, get_args, get_origin
from urllib.parse import urlparse

from ocpp.exceptions import NotImplementedError, NotSupportedError, OCPPError
from ocpp.messages import Call, MessageType, unpack, validate_payload
from ocpp.routing import create_route_map

LOGGER = logging.getLogger("ocpp")


def extract_charge_point_id(path: Optional[str]) -> Optional[str]:
    """Estrai l'ID del charge point da un percorso URL WebSocket.

    In OCPP, i charger si connettono a un endpoint WebSocket e includono il loro
    identificatore come ultimo segmento del percorso URL. Per esempio, un charger
    con ID "CP001" si connetterebbe a ``ws://central-system:9000/CP001``
    o ``ws://central-system:9000/ocpp/CP001``.

    supporta i seguenti formati di percorso:

    - ``/CP001`` → ``CP001``
    - ``/ocpp/CP001`` → ``CP001``
    - ``/`` → ``None``
    - ``""`` → ``None``

    Args:
        path: The URL path from the WebSocket request
            (e.g., ``websocket.request.path``).

    Returns:
        The charge point ID string, or ``None`` if the path does not
        contain a valid identifier.
    """
    if not path:
        return None

    # converte il percorso in un oggetto ParseResult per estrarre il percorso pulito
    parsed = urlparse(path)
    clean_path = parsed.path

    # Rimuove eventuali segmenti vuoti e ottiene l'ultimo segmento come ID del charge point
    segments = [s for s in clean_path.split("/") if s]
    if not segments:
        return None

    charge_point_id = segments[-1]

    # Rimuove eventuali spazi bianchi e verifica se l'ID è vuoto
    charge_point_id = charge_point_id.strip()
    if not charge_point_id:
        return None

    return charge_point_id


def camel_to_snake_case(data):
    """
    Converte tutte le chiavi di tutti i dizionari all'interno dell'argomento dato da
    camelCase a snake_case.

    """
    if isinstance(data, dict):
        snake_case_dict = {}
        for key, value in data.items():
            key = key.replace("ocppCSMSURL", "ocpp_csms_url")
            key = key.replace("V2X", "_v2x").replace("V2G", "_v2g")
            s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", key)
            key = re.sub("([a-z0-9])([A-Z])(?=\\S)", r"\1_\2", s1).lower()

            snake_case_dict[key] = camel_to_snake_case(value)

        return snake_case_dict

    if isinstance(data, list):
        snake_case_list = []
        for value in data:
            snake_case_list.append(camel_to_snake_case(value))

        return snake_case_list

    return data


def snake_to_camel_case(data):
    """
    Converte tutte le chiavi di tutti i dizionari all'interno dell'argomento dato da
    snake_case a camelCase.
    """
    if isinstance(data, dict):
        camel_case_dict = {}
        for key, value in data.items():
            key = key.replace("soc", "SoC")
            key = key.replace("_v2x", "V2X")
            # La specifica usa maiuscole/minuscole incoerenti per "csms" e "url".
            # Ad esempio: "OcppCsmsUrl" rispetto a "ResponderURL" e "CSMSRootCertificate".
            key = key.replace("ocpp_csms_url", "ocppCsmsUrl")
            key = key.replace("csms", "CSMS")
            key = key.replace("_url", "URL")
            key = key.replace("soc", "SoC").replace("_SoCket", "Socket")
            key = key.replace("_v2x", "V2X")
            key = key.replace("soc_limit_reached", "SOCLimitReached")
            key = key.replace("_v2x", "V2X").replace("_v2g", "V2G")
            components = key.split("_")
            key = components[0] + "".join(x[:1].upper() + x[1:] for x in components[1:])
            camel_case_dict[key] = snake_to_camel_case(value)

        return camel_case_dict

    if isinstance(data, list):
        camel_case_list = []
        for value in data:
            camel_case_list.append(snake_to_camel_case(value))

        return camel_case_list

    return data


def _is_dataclass_instance(input: Any) -> bool:
    """Verifica se l'argomento `input` e' una dataclass."""
    return is_dataclass(input) and not isinstance(input, type)


def _is_optional_field(field: Field) -> bool:
    """Verifica se il campo `field` ammette `None` come valore.

    I campi `schema` e `host` della classe seguente restituiscono `False`,
    mentre i campi `post` e `query` restituiscono `True`.

        @dataclass
        class URL:
            schema: str,
            host: str,
            post: Optional[str],
            query: Union[None, str]

    """
    return get_origin(field.type) is Union and type(None) in get_args(field.type)


def serialize_as_dict(dataclass):
    """Serializza ricorsivamente la `dataclass` fornita in un `dict`.

    @dataclass
    class StatusInfoType:
        reason_code: str
        additional_info: Optional[str] = None

    with_additional_info = StatusInfoType(
        reason="Unknown",
        additional_info="More details"
    )

    assert serialize_as_dict(with_additional_info) == {
        'reason': 'Unknown',
        'additional_info': 'More details',
    }

    without_additional_info = StatusInfoType(reason="Unknown")

    assert serialize_as_dict(with_additional_info) == {
        'reason': 'Unknown',
        'additional_info': None,
    }

    """
    serialized = asdict(dataclass)

    for field in dataclass.__dataclass_fields__.values():
        value = getattr(dataclass, field.name)
        if _is_dataclass_instance(value):
            serialized[field.name] = serialize_as_dict(value)
            continue

        if isinstance(value, list):
            serialized[field.name] = []
            for item in value:
                if _is_dataclass_instance(item):
                    serialized[field.name].append(serialize_as_dict(item))
                else:
                    serialized[field.name].append(item)

    return serialized


def remove_nones(data: Union[List, Dict]) -> Union[List, Dict]:
    if isinstance(data, dict):
        return {k: remove_nones(v) for k, v in data.items() if v is not None}

    elif isinstance(data, list):
        return [remove_nones(v) for v in data if v is not None]

    return data


def _raise_key_error(action, version):
    """
    Determina se una keyerror restituita da `_handle_call` e' supportata dalla
    versione OCPP oppure se non e' implementata da server/client, e solleva
    l'errore appropriato.
    """

    from ocpp.v16.enums import Action

    if version != "1.6":
        raise NotSupportedError(details={"cause": f"OCPP{version} is not available."})
    try:
        Action(action)
    except ValueError:
        raise NotSupportedError(
            details={"cause": f"{action} not supported by OCPP{version}."}
        )
    raise NotImplementedError(details={"cause": f"No handler for {action} registered."})


class ChargePoint:
    """
    Elemento di base contenente tutti i messaggi OCPP1.6J necessari per i messaggi
    avviati e ricevuti dal Sistema Centrale.
    """

    def __init__(self, id, connection, response_timeout=30, logger=LOGGER):
        """

        Argomenti:

            charger_id (str): ID del caricatore.
            connection: Connessione al CP.
            response_timeout (int): Se una richiesta non riceve risposta entro
                questo intervallo, viene sollevato `asyncio.TimeoutError`.
            logger: Istanza Logger opzionale usata per il logging. Per
                impostazione predefinita viene usato il logger `ocpp`.

        """
        self.id = id

        # Tempo massimo, in secondi, entro cui un CP puo' rispondere a una CALL.
        # Se il limite viene superato viene sollevato asyncio.TimeoutError.
        self._response_timeout = response_timeout

        # Connessione al client. Al momento e' un'istanza di gh.
        self._connection = connection

        # Dizionario degli hook per le Action. Quando il CS riceve un'azione,
        # la cerca in questa mappa ed esegue gli hook corrispondenti, se presenti.
        self.route_map = create_route_map(self)

        self._call_lock = asyncio.Lock()

        # Coda usata per passare CallResult e CallError dal task self.serve()
        # al task self.call().
        self._response_queue = asyncio.Queue()

        # Funzione usata per generare ID univoci per le CALL. Per impostazione
        # predefinita usa uuid.uuid4(), ma puo' essere sostituita principalmente
        # per avere ID prevedibili nei test.
        self._unique_id_generator = uuid.uuid4

        # Logger usato per registrare i messaggi.
        self.logger = logger

    async def start(self):
        while True:
            message = await self._connection.recv()
            self.logger.info("%s: receive message %s", self.id, message)

            await self.route_message(message)

    async def route_message(self, raw_msg):
        """
        Instradare un messaggio ricevuto da un CP.

        Se il messaggio e' di tipo Call, vengono eseguiti gli hook corrispondenti.
        Se e' di tipo CallResult o CallError, viene passato alla funzione `call()`
        attraverso `response_queue`.
        """
        try:
            msg = unpack(raw_msg)
        except OCPPError as e:
            self.logger.exception(
                "Unable to parse message: '%s', it doesn't seem "
                "to be valid OCPP: %s",
                raw_msg,
                e,
            )
            return

        if msg.message_type_id == MessageType.Call:
            try:
                await self._handle_call(msg)
            except OCPPError as error:
                self.logger.exception("Error while handling request '%s'", msg)
                response = msg.create_call_error(error).to_json()
                await self._send(response)

        elif msg.message_type_id in [MessageType.CallResult, MessageType.CallError]:
            self._response_queue.put_nowait(msg)

    async def _handle_call(self, msg):
        """
        Esegue gli hook installati per l'Action del messaggio.

        Prima esegue l'hook `_on_action` e restituisce la sua risposta al client.
        Se non esiste un hook `_on_action` per l'Action, restituisce un CallError
        con `NotImplementedError`; se l'Action non e' supportata dalla versione
        OCPP, restituisce `NotSupportedError`.

        Successivamente esegue l'hook `_after_action`.

        """
        try:
            handlers = self.route_map[msg.action]
        except KeyError:
            _raise_key_error(msg.action, self._ocpp_version)
            return

        if not handlers.get("_skip_schema_validation", False):
            await validate_payload(msg, self._ocpp_version)

        # OCPP usa camelCase per le chiavi del payload. Per gli argomenti con nome
        # e' piu' idiomatico Python usare snake_case; le chiavi devono quindi essere
        # "tradotte". Alcuni esempi:
        #
        # * chargePointVendor diventa charge_point_vendor
        # * firmwareVersion diventa firmware_version
        snake_case_payload = camel_to_snake_case(msg.payload)

        try:
            handler = handlers["_on_action"]
        except KeyError:
            _raise_key_error(msg.action, self._ocpp_version)
        handler_signature = inspect.signature(handler)
        call_unique_id_required = "call_unique_id" in handler_signature.parameters
        try:
            # call_unique_id va passato come argomento con nome solo se e' definito
            # esplicitamente nella firma dell'handler.
            if call_unique_id_required:
                response = handler(**snake_case_payload, call_unique_id=msg.unique_id)
            else:
                response = handler(**snake_case_payload)
            if inspect.isawaitable(response):
                response = await response
        except Exception as e:
            self.logger.exception("Error while handling request '%s'", msg)
            response = msg.create_call_error(e).to_json()
            await self._send(response)

            return

        temp_response_payload = serialize_as_dict(response)

        # remove_nones elimina gli argomenti opzionali non impostati, con valore
        # predefinito None.
        response_payload = remove_nones(temp_response_payload)

        # Il payload di risposta deve essere "tradotto" da snake_case a camelCase:
        #
        # * charge_point_vendor diventa chargePointVendor
        # * firmware_version diventa firmwareVersion
        camel_case_payload = snake_to_camel_case(response_payload)

        response = msg.create_call_result(camel_case_payload)

        if not handlers.get("_skip_schema_validation", False):
            await validate_payload(response, self._ocpp_version)

        await self._send(response.to_json())

        try:
            handler = handlers["_after_action"]
            handler_signature = inspect.signature(handler)
            call_unique_id_required = "call_unique_id" in handler_signature.parameters
            # call_unique_id va passato come argomento con nome solo se e' definito
            # esplicitamente nella firma dell'handler.
            if call_unique_id_required:
                snake_case_payload["call_unique_id"] = msg.unique_id
            # call_response va passato come argomento con nome solo se l'handler
            # after e' decorato con inject_response=True.
            if getattr(handler, "_inject_response", False):
                snake_case_payload["call_response"] = response_payload
            response = handler(**snake_case_payload)
            # Crea un task per non bloccare quando si effettua una chiamata
            # nell'handler after.
            if inspect.isawaitable(response):
                asyncio.ensure_future(response)
        except KeyError:
            # Gli hook '_on_after' non sono obbligatori: ignora l'eccezione quando
            # non ne e' registrato alcuno.
            pass
        return response

    async def call(
        self, payload, suppress=True, unique_id=None, skip_schema_validation=False
    ):
        """
        Invia un messaggio Call al client e restituisce il payload della risposta.

        Il payload fornito viene trasformato in un oggetto Call in base al suo
        tipo. Un BootNotificationPayload genera una Call con Action
        BootNotification, un HeartbeatPayload una Call con Action Heartbeat, e
        cosi' via.

        Se non arriva una risposta entro il timeout configurato, viene sollevata
        un'eccezione di timeout.

        Durante l'attesa non puo' essere inviato un altro messaggio Call, in
        conformita' alla specifica OCPP.

        `suppress` mantiene la compatibilita' all'indietro: se e' `True`, un
        CallError viene soppresso; se e' `False`, viene sollevata l'eccezione
        corrispondente.

        Impostare `skip_schema_validation=True` per saltare la validazione dello
        schema di richiesta e risposta.

        """
        camel_case_payload = snake_to_camel_case(serialize_as_dict(payload))

        unique_id = (
            unique_id if unique_id is not None else str(self._unique_id_generator())
        )

        action_name = payload.__class__.__name__

        call = Call(
            unique_id=unique_id,
            action=action_name,
            payload=remove_nones(camel_case_payload),
        )

        if not skip_schema_validation:
            await validate_payload(call, self._ocpp_version)

        # Usa un lock per garantire che venga inviato un solo messaggio alla volta.
        async with self._call_lock:
            await self._send(call.to_json())
            try:
                response = await self._get_specific_response(
                    call.unique_id, self._response_timeout
                )
            except asyncio.TimeoutError:
                raise asyncio.TimeoutError(
                    f"Waited {self._response_timeout}s for response on "
                    f"{call.to_json()}."
                )

        if response.message_type_id == MessageType.CallError:
            self.logger.warning("Received a CALLError: %s'", response)
            if suppress:
                return
            raise response.to_exception()
        elif not skip_schema_validation:
            response.action = call.action
            await validate_payload(response, self._ocpp_version)

        snake_case_payload = camel_to_snake_case(response.payload)
        # Crea l'istanza Payload corretta in base al payload ricevuto. Se questo
        # metodo e' chiamato con call.BootNotificationPayload, crea
        # call_result.BootNotificationPayload; con call.HeartbeatPayload crea
        # call_result.HeartbeatPayload, e cosi' via.
        cls = getattr(self._call_result, payload.__class__.__name__)  # noqa  # Ignora il controllo di stile per questa riga.
        return cls(**snake_case_payload)

    async def _get_specific_response(self, unique_id, timeout):
        """
        Restituisce la risposta con l'ID univoco indicato o solleva
        `asyncio.TimeoutError`.
        """
        wait_until = time.time() + timeout
        try:
            # Attende la risposta al messaggio Call.
            response = await asyncio.wait_for(self._response_queue.get(), timeout)
        except asyncio.TimeoutError:
            raise

        if response.unique_id == unique_id:
            return response

        self.logger.error("Ignoring response with unknown unique id: %s", response)
        timeout_left = wait_until - time.time()

        if timeout_left < 0:
            raise asyncio.TimeoutError

        return await self._get_specific_response(unique_id, timeout_left)

    async def _send(self, message):
        self.logger.info("%s: send %s", self.id, message)
        await self._connection.send(message)
