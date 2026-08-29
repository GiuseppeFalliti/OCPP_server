"""Log locali JSON Lines per Charge Point OCPP 1.6J."""

import asyncio
import json
import logging
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("ocpp.v16.json_logger")
_UNSAFE_PATH_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def safe_directory_name(value: str) -> str:
    """Restituisce un nome di directory sicuro e leggibile."""
    sanitized = _UNSAFE_PATH_CHARS.sub("-", value).strip(".-")
    return (sanitized or "unknown")[:120]


def decode_frame(raw: str) -> tuple[str, Any | None]:
    """Estrae action e frame JSON, senza impedire il log di frame non validi."""
    try:
        frame = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return "InvalidFrame", None
    if not isinstance(frame, list) or not frame:
        return "InvalidFrame", frame
    if frame[0] == 2 and len(frame) > 2:
        return str(frame[2]), frame
    if frame[0] == 3:
        return "CallResult", frame
    if frame[0] == 4:
        return "CallError", frame
    return "Unknown", frame


class ChargePointJsonLogger:
    """Writer JSON Lines associato a una singola connessione Charge Point."""

    def __init__(
        self,
        store: "JsonLogStore",
        charge_point_id: str,
        remote_ip: str | None,
        serial_number: str | None = None,
    ) -> None:
        self.store = store
        self.charge_point_id = charge_point_id
        self.remote_ip = remote_ip
        self.serial_number = serial_number
        self.directory = store.directory_for(serial_number or charge_point_id, not serial_number)
        self._lock = asyncio.Lock()

    async def set_serial_number(self, serial_number: str | None) -> None:
        """Sposta i log temporanei nella cartella identificata dal seriale."""
        if not serial_number:
            return
        target = self.store.directory_for(serial_number, temporary=False)
        async with self._lock:
            if self.directory != target:
                try:
                    await asyncio.to_thread(self.store.move_directory, self.directory, target)
                except OSError:
                    LOGGER.exception("Impossibile spostare i log del CP %s", self.charge_point_id)
                    return
                self.directory = target
            self.serial_number = serial_number

    async def event(
        self,
        event_type: str,
        *,
        direction: str | None = None,
        raw: str | None = None,
        action: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Aggiunge un evento al file UTC della giornata corrente."""
        await self.store.cleanup_if_due()
        decoded: Any | None = None
        detected_action: str | None = None
        if raw is not None:
            detected_action, decoded = decode_frame(raw)
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "charge_point_id": self.charge_point_id,
            "serial_number": self.serial_number,
            "remote_ip": self.remote_ip,
        }
        if direction:
            record["direction"] = direction
        if action or detected_action:
            record["action"] = action or detected_action
        if raw is not None:
            record["raw"] = raw
            record["frame"] = decoded
        if details:
            record["details"] = details

        async with self._lock:
            try:
                await asyncio.to_thread(self.store.append, self.directory, record)
            except OSError:
                LOGGER.exception("Impossibile scrivere il log del CP %s", self.charge_point_id)


class JsonLogStore:
    """Gestisce directory, pulizia e writer JSON Lines dei Charge Point."""

    def __init__(self, root: str | Path | None = None, retention_days: int = 30) -> None:
        self.root = Path(root) if root else Path(__file__).resolve().parents[1] / "Logs"
        self.retention_days = retention_days
        self._cleanup_lock = asyncio.Lock()
        self._last_cleanup_date: date | None = None

    def directory_for(self, value: str, temporary: bool = False) -> Path:
        prefix = "_temporary_" if temporary else ""
        return self.root / f"{prefix}{safe_directory_name(value)}"

    async def cleanup(self) -> None:
        """Rimuove i file JSON più vecchi della retention configurata."""
        async with self._cleanup_lock:
            try:
                await asyncio.to_thread(self._cleanup_sync)
            except OSError:
                LOGGER.exception("Impossibile pulire i log JSON OCPP")

    async def cleanup_if_due(self) -> None:
        """Esegue la pulizia al massimo una volta al giorno durante il servizio."""
        today = datetime.now(timezone.utc).date()
        if self._last_cleanup_date == today:
            return
        await self.cleanup()
        self._last_cleanup_date = today

    def _cleanup_sync(self) -> None:
        if not self.root.exists():
            return
        threshold = date.today() - timedelta(days=self.retention_days)
        for log_file in self.root.glob("*/*.json"):
            try:
                log_date = date.fromisoformat(log_file.stem)
            except ValueError:
                continue
            if log_date < threshold:
                log_file.unlink(missing_ok=True)

    def append(self, directory: Path, record: dict[str, Any]) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        log_file = directory / f"{datetime.now(timezone.utc).date().isoformat()}.json"
        line = json.dumps(record, ensure_ascii=False, default=str, separators=(",", ":"))
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")

    def move_directory(self, source: Path, target: Path) -> None:
        """Rinomina oppure unisce una directory temporanea con quella del seriale."""
        if source == target or not source.exists():
            return
        if not target.exists():
            source.rename(target)
            return
        target.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            destination = target / child.name
            if child.is_file() and destination.exists():
                with child.open("rb") as origin, destination.open("ab") as merged:
                    shutil.copyfileobj(origin, merged)
                child.unlink()
            else:
                child.replace(destination)
        source.rmdir()
