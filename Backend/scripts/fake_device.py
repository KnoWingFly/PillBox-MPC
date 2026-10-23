"""fake_device.py: a command-line TEST CLIENT that behaves like a PillCare device.

It talks to the backend only through the public device API (REST + WebSocket),
exactly like real firmware or the PySide6 emulator would. It never touches the
database. Its only local state is an offline event buffer (a JSON file), the
same role the emulator's SQLite `events` table plays.

Transports:
  --transport ws   (default) WebSocket for heartbeats + commands
                   (trigger_alarm / time_sync / schedule_updated / refill_mode),
                   REST for telemetry and config.
  --transport rest REST heartbeats only, like the current emulator. Commands
                   are not available; Wi-Fi loss is detected by heartbeat timeout.

Interactive commands (type while it runs):
  popup <slot> | open <slot> | close <slot> | timeout <slot> | unsched <slot>
  battery <pct> | stock <slot> <n> | wifi off | wifi on | flush | status | help | quit

Examples (run from Backend/):
  uv run python -m scripts.fake_device --provision --provisioning-token <PROVISIONING_TOKEN>
  # register the PySide6 emulator's fixed identity:
  uv run python -m scripts.fake_device --provision --provisioning-token <TOKEN> --device-code sim-01 --device-key dummy-key
  uv run python -m scripts.fake_device --device-code PB-1A2B3C4D --device-key <secret>
  uv run python -m scripts.fake_device --device-code PB-1A2B3C4D --device-key <secret> \\
        --wifi-off-at 20 --wifi-off-for 90
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import threading
import uuid
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

log = logging.getLogger("fake_device")

EVENT_TYPES = {
    "popup": "POPUP_ACTIVATED",
    "open": "COMPARTMENT_OPENED",
    "close": "COMPARTMENT_CLOSED",
    "timeout": "ALARM_TIMEOUT",
    "unsched": "UNSCHEDULED_OPEN",
}
FLUSH_CHUNK = 200


class FakeDevice:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.base = args.base_url.rstrip("/")
        self.code: str = args.device_code
        self.key: str = args.device_key
        self.tz = ZoneInfo(args.timezone)
        self.wifi_on = True
        self.battery = args.battery
        self.doors = {slot: "CLOSED" for slot in range(1, 9)}
        self.stock: dict[int, int] = {}
        self.config_version_applied = 0
        self.schedules: list[dict[str, Any]] = []
        self.heartbeat_interval = args.heartbeat_interval
        self.buffer_path = Path(args.buffer_file or f".fake_device_{self.code}.json")
        self.buffer: list[dict[str, Any]] = self._load_buffer()
        self.ws: ClientConnection | None = None
        self.http = httpx.AsyncClient(base_url=f"{self.base}/api/v1", timeout=args.http_timeout)
        self._send_lock = asyncio.Lock()
        self._flush_lock = asyncio.Lock()
        self._reconnected = asyncio.Event()

    # --- local buffer (offline-first) -------------------------------------
    def _load_buffer(self) -> list[dict[str, Any]]:
        if self.buffer_path.exists():
            return json.loads(self.buffer_path.read_text(encoding="utf-8"))
        return []

    def _save_buffer(self) -> None:
        self.buffer_path.write_text(json.dumps(self.buffer, indent=1), encoding="utf-8")

    def now(self) -> str:
        ts = datetime.now(self.tz).replace(microsecond=0)
        return ts.replace(tzinfo=None).isoformat() if self.args.naive_timestamps else ts.isoformat()

    def record(self, event_type: str, slot: int | None = None, **extra: Any) -> None:
        """Every physical event gets a unique event_id and the device's own time,
        and goes to the buffer first; it is sent when Wi-Fi allows."""
        evt = {"event_id": str(uuid.uuid4()), "event_type": event_type, "slot_number": slot,
               "occurred_at": self.now(), **extra}
        self.buffer.append(evt)
        self._save_buffer()
        log.info("event %s slot=%s buffered (%d pending)", event_type, slot, len(self.buffer))

    # --- REST ----------------------------------------------------------------
    @property
    def headers(self) -> dict[str, str]:
        return {"X-Device-Key": self.key}

    def heartbeat_body(self) -> dict[str, Any]:
        return {
            "sent_at": self.now(),
            "battery_percent": self.battery,
            "wifi_rssi_dbm": -55,
            "rtc_time": self.now(),
            "config_version_applied": self.config_version_applied,
            "chambers": [
                {"slot_number": s, "door": d, **({"stock_count": self.stock[s]} if s in self.stock else {})}
                for s, d in self.doors.items()
            ],
        }

    async def rest_heartbeat(self) -> None:
        res = await self.http.post(f"/devices/{self.code}/heartbeat", json=self.heartbeat_body(), headers=self.headers)
        res.raise_for_status()
        body = res.json()
        if body.get("config_update_available"):
            await self.pull_config()

    async def pull_config(self) -> None:
        res = await self.http.get(
            f"/devices/{self.code}/config", params={"since_version": self.config_version_applied}, headers=self.headers
        )
        if res.status_code == 304:
            return
        res.raise_for_status()
        cfg = res.json()
        self.schedules = cfg["schedules"]
        self.config_version_applied = cfg["config_version"]
        ack = await self.http.post(
            f"/devices/{self.code}/config-ack",
            json={"config_version": cfg["config_version"], "applied_at": self.now()},
            headers=self.headers,
        )
        ack.raise_for_status()
        slots = ", ".join(f"{s['slot_number']}@{s['window_start']}" for s in self.schedules if s["active"]) or "none"
        log.info("config v%s applied (active slots: %s)", cfg["config_version"], slots)

    async def flush(self, offline_flush: bool = False) -> None:
        """Send buffered events oldest-first in chunks. Accepted, duplicate and
        rejected events are all final, so they leave the buffer; on a network
        error everything stays buffered for the next attempt."""
        async with self._flush_lock:
            await self._flush(offline_flush)

    async def _flush(self, offline_flush: bool) -> None:
        while self.buffer and self.wifi_on:
            chunk = sorted(self.buffer, key=lambda e: e["occurred_at"])[:FLUSH_CHUNK]
            res = await self.http.post(
                f"/devices/{self.code}/telemetry",
                json={"batch_id": str(uuid.uuid4()), "is_offline_flush": offline_flush, "events": chunk},
                headers=self.headers,
            )
            res.raise_for_status()
            body = res.json()
            done = {r["event_id"] for r in body["results"]}
            self.buffer = [e for e in self.buffer if e["event_id"] not in done]
            self._save_buffer()
            log.info("flushed: accepted=%s duplicates=%s rejected=%s",
                     body["accepted"], body["duplicates"], body["rejected"])
            if body.get("latest_config_version", 0) > self.config_version_applied:
                await self.pull_config()

    # --- WebSocket -------------------------------------------------------------
    async def ws_send(self, message: dict[str, Any]) -> None:
        if self.ws is None:
            raise ConnectionError("no websocket")
        async with self._send_lock:
            await self.ws.send(json.dumps(message))

    async def handle_command(self, msg: dict[str, Any]) -> None:
        command, payload, command_id = msg.get("command"), msg.get("payload") or {}, msg.get("command_id")
        log.info("command received: %s %s", command, payload)
        result: dict[str, Any] = {}
        ok = True
        if command == "trigger_alarm":
            slot = payload.get("slot_number")
            print(f"\n*** ALARM RINGING (slot={slot}, {payload.get('duration_seconds')} s) ***\n")
            self.record("ALARM_STARTED", slot, command_id=command_id, reason="remote")
            result = {"ringing": True, "slot_number": slot}
        elif command == "time_sync":
            before = self.now()
            # A real device would set its RTC from payload["server_time"] here.
            result = {"device_time_before": before, "device_time_after": self.now()}
        elif command == "schedule_updated":
            await self.pull_config()
            result = {"config_version_applied": self.config_version_applied}
        elif command == "refill_mode":
            result = {"is_refill_mode": bool(payload.get("enabled"))}
        else:
            ok = False
        await self.ws_send({"type": "ack", "command_id": command_id, "ok": ok, "result": result,
                            **({} if ok else {"error": f"unsupported command {command}"})})

    async def ws_session(self) -> None:
        uri = self.base.replace("http://", "ws://").replace("https://", "wss://") + f"/ws/device/{self.code}"
        async with connect(uri, additional_headers=self.headers, open_timeout=self.args.http_timeout) as ws:
            self.ws = ws
            log.info("websocket connected")
            heartbeat = asyncio.create_task(self.ws_heartbeats())
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    kind = msg.get("type")
                    if kind == "welcome":
                        self.heartbeat_interval = msg.get("heartbeat_interval_seconds", self.heartbeat_interval)
                    elif kind == "heartbeat_ack":
                        if msg.get("config_update_available"):
                            await self.pull_config()
                    elif kind == "command":
                        await self.handle_command(msg)
                    elif kind == "error":
                        log.warning("server error: %s", msg)
            finally:
                heartbeat.cancel()
                self.ws = None

    async def ws_heartbeats(self) -> None:
        while True:
            await self.ws_send({"type": "heartbeat", **self.heartbeat_body()})
            await asyncio.sleep(self.heartbeat_interval)

    # --- main loops --------------------------------------------------------------
    async def connectivity_loop(self) -> None:
        was_offline = False
        while True:
            if not self.wifi_on:
                was_offline = True
                await self._reconnected.wait()
                continue
            try:
                if was_offline:
                    self.record("NETWORK_RECOVERED")
                await self.rest_heartbeat()  # proves liveness first, like the emulator
                await self.flush(offline_flush=was_offline)
                was_offline = False
                if self.args.transport == "ws":
                    ws_task = asyncio.create_task(self.ws_session())
                    wifi_lost = asyncio.create_task(self._wait_wifi_off())
                    await asyncio.wait({ws_task, wifi_lost}, return_when=asyncio.FIRST_COMPLETED)
                    for task in (ws_task, wifi_lost):
                        task.cancel()
                        with suppress(asyncio.CancelledError, ConnectionClosed):
                            await task
                    if self.wifi_on:
                        await asyncio.sleep(1)  # server closed us (e.g. auth failed): back off
                else:
                    await asyncio.sleep(self.heartbeat_interval)
            except (httpx.HTTPError, OSError, ConnectionClosed, InvalidHandshake, TimeoutError) as exc:
                log.warning("backend unreachable (%s); retrying in 5 s", exc.__class__.__name__)
                await asyncio.sleep(5)

    async def _wait_wifi_off(self) -> None:
        while self.wifi_on:
            await asyncio.sleep(0.2)

    async def flush_loop(self) -> None:
        while True:
            await asyncio.sleep(2)
            if self.wifi_on and self.buffer:
                with suppress(httpx.HTTPError, OSError):
                    await self.flush()

    def set_wifi(self, on: bool) -> None:
        self.wifi_on = on
        if on:
            self._reconnected.set()
            log.info("Wi-Fi ON: reconnecting, then flushing %d buffered event(s)", len(self.buffer))
        else:
            self._reconnected.clear()
            # Dropping Wi-Fi drops the socket. In --transport rest the backend
            # notices only through the heartbeat timeout.
            if self.ws is not None:
                asyncio.create_task(self.ws.close())
            log.info("Wi-Fi OFF: events will be buffered locally")

    async def scripted_wifi(self) -> None:
        if self.args.wifi_off_at is None:
            return
        await asyncio.sleep(self.args.wifi_off_at)
        self.set_wifi(False)
        await asyncio.sleep(self.args.wifi_off_for)
        self.set_wifi(True)

    async def handle_line(self, line: str) -> bool:
        parts = line.split()
        if not parts:
            return True
        cmd = parts[0].lower()
        try:
            if cmd in EVENT_TYPES:
                slot = int(parts[1])
                if cmd in ("open", "unsched"):
                    self.doors[slot] = "OPEN"
                elif cmd == "close":
                    self.doors[slot] = "CLOSED"
                self.record(EVENT_TYPES[cmd], slot)
            elif cmd == "battery":
                self.battery = max(0, min(100, int(parts[1])))
                self.record("BATTERY_STATUS", battery_percent=self.battery)
            elif cmd == "stock":
                self.stock[int(parts[1])] = int(parts[2])
            elif cmd == "wifi":
                self.set_wifi(parts[1].lower() == "on")
            elif cmd == "flush":
                await self.flush()
            elif cmd == "status":
                print(f"wifi={'on' if self.wifi_on else 'off'} ws={'up' if self.ws else 'down'} "
                      f"buffer={len(self.buffer)} config_v={self.config_version_applied} battery={self.battery}")
            elif cmd in ("quit", "exit"):
                return False
            else:
                print(__doc__)
        except (IndexError, ValueError):
            print("bad arguments; type 'help'")
        except httpx.HTTPError as exc:
            print(f"request failed: {exc}")
        return True


def _stdin_reader(loop: asyncio.AbstractEventLoop, queue: "asyncio.Queue[str | None]") -> None:
    for line in sys.stdin:
        loop.call_soon_threadsafe(queue.put_nowait, line.strip())
    loop.call_soon_threadsafe(queue.put_nowait, None)


async def provision(args: argparse.Namespace) -> None:
    async with httpx.AsyncClient(base_url=f"{args.base_url.rstrip('/')}/api/v1", timeout=args.http_timeout) as http:
        body: dict[str, Any] = {}
        if args.device_code:
            body["device_code"] = args.device_code
        if args.device_key:
            # e.g. the PySide6 emulator's fixed "dummy-key" (needs DEVICE_SECRET_MIN_LENGTH <= 9)
            body["device_secret"] = args.device_key
        res = await http.post("/admin/devices", json=body, headers={"X-Provisioning-Token": args.provisioning_token})
        if res.status_code != 201:
            sys.exit(f"provisioning failed: {res.status_code} {res.text}")
        data = res.json()
    print(json.dumps(data, indent=2))
    print("\nKeep device_secret safe: it is shown only once. Pair the device in the app with qr_payload.")


async def run(args: argparse.Namespace) -> None:
    device = FakeDevice(args)
    loop = asyncio.get_running_loop()
    lines: asyncio.Queue[str | None] = asyncio.Queue()
    threading.Thread(target=_stdin_reader, args=(loop, lines), daemon=True).start()
    tasks = [
        asyncio.create_task(device.connectivity_loop()),
        asyncio.create_task(device.flush_loop()),
        asyncio.create_task(device.scripted_wifi()),
    ]
    print(f"fake device {device.code} running ({args.transport}). Type 'help' for commands.")
    try:
        while True:
            line = await lines.get()
            if line is None or not await device.handle_line(line):
                break
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if device.ws is not None:
            await device.ws.close()
        await device.http.aclose()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PillCare fake device (test client)")
    p.add_argument("--base-url", default=os.environ.get("PILLCARE_BASE_URL", "http://localhost:8000"))
    p.add_argument("--device-code", default=os.environ.get("FAKE_DEVICE_CODE"))
    p.add_argument("--device-key", default=os.environ.get("FAKE_DEVICE_KEY"), help="device secret (X-Device-Key)")
    p.add_argument("--transport", choices=("ws", "rest"), default="ws")
    p.add_argument("--timezone", default="Asia/Jakarta")
    p.add_argument("--naive-timestamps", action="store_true", help="send local time without offset (like the emulator)")
    p.add_argument("--heartbeat-interval", type=float, default=15.0)
    p.add_argument("--battery", type=int, default=100)
    p.add_argument("--buffer-file", default=None)
    p.add_argument("--http-timeout", type=float, default=5.0)
    p.add_argument("--wifi-off-at", type=float, default=None, help="seconds after start to turn Wi-Fi off")
    p.add_argument("--wifi-off-for", type=float, default=60.0, help="seconds to stay offline")
    p.add_argument("--provision", action="store_true", help="register a new device via the admin API and exit")
    p.add_argument("--provisioning-token", default=os.environ.get("PROVISIONING_TOKEN"))
    args = p.parse_args()
    if args.provision:
        if not args.provisioning_token:
            p.error("--provision needs --provisioning-token (or PROVISIONING_TOKEN)")
    elif not (args.device_code and args.device_key):
        p.error("--device-code and --device-key are required (or FAKE_DEVICE_CODE / FAKE_DEVICE_KEY)")
    return args


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    asyncio.run(provision(args) if args.provision else run(args))


if __name__ == "__main__":
    main()
