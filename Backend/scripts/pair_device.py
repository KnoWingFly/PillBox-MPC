"""pair_device.py: one-time setup that pairs a provisioned pillbox to your caregiver
account, using only the public APIs (no direct database access).

What the Mobile app will eventually do on its pairing screens:
  1. log in through the Mobile server (POST {mobile}/api/auth/login) -> access token
  2. create an elderly profile if you have none        (POST /api/v1/elderly)
  3. pair the device with its QR payload + 4-digit PIN (POST /api/v1/devices)

Run from Backend/ (the Mobile dev server must be running for step 1):
  uv run python -m scripts.pair_device --email you@example.com --device-code sim-01 --pin 1234
"""

import argparse
import getpass
import sys
from typing import Any

import httpx


def fail(step: str, res: httpx.Response) -> None:
    sys.exit(f"{step} failed: HTTP {res.status_code} {res.text}")


def main() -> None:
    p = argparse.ArgumentParser(description="Pair a provisioned pillbox to a caregiver account")
    p.add_argument("--mobile-url", default="http://localhost:8081", help="Expo dev server (serves /api/auth/*)")
    p.add_argument("--backend-url", default="http://localhost:8000")
    p.add_argument("--email", required=True)
    p.add_argument("--password", help="omit to be prompted")
    p.add_argument("--device-code", required=True, help="e.g. sim-01 or PB-1A2B3C4D")
    p.add_argument("--pin", default="1234", help="4-digit device PIN to set")
    p.add_argument("--nickname", default="Pillbox Lansia")
    p.add_argument("--elderly-name", default="Lansia", help="used only if you have no elderly profile yet")
    p.add_argument("--timezone", default="Asia/Jakarta")
    args = p.parse_args()
    password = args.password or getpass.getpass("Password: ")

    with httpx.Client(timeout=20) as http:
        res = http.post(f"{args.mobile_url.rstrip('/')}/api/auth/login", json={"email": args.email, "password": password})
        if res.status_code != 200:
            fail("login", res)
        auth = {"Authorization": f"Bearer {res.json()['access_token']}"}
        api = f"{args.backend_url.rstrip('/')}/api/v1"

        me = http.get(f"{api}/me", headers=auth)
        if me.status_code != 200:
            fail("backend auth check (is JWT_ACCESS_SECRET identical in Backend/.env and Mobile/.env.local?)", me)

        elderly = http.get(f"{api}/elderly", headers=auth)
        if elderly.status_code != 200:
            fail("list elderly", elderly)
        items: list[dict[str, Any]] = elderly.json()["data"]
        editable = [e for e in items if e["my_role"] in ("OWNER", "ADMIN")]
        if editable:
            elderly_id = editable[0]["id"]
            print(f"using elderly profile {editable[0]['full_name']} ({elderly_id})")
        else:
            created = http.post(f"{api}/elderly", json={"full_name": args.elderly_name}, headers=auth)
            if created.status_code != 201:
                fail("create elderly", created)
            elderly_id = created.json()["id"]
            print(f"created elderly profile {args.elderly_name} ({elderly_id})")

        scan = http.post(f"{api}/devices/pairing/scan", json={"device_qr_payload": args.device_code}, headers=auth)
        if scan.status_code != 200:
            fail("scan (was the device provisioned?)", scan)
        if scan.json()["is_registered"]:
            print(f"device {args.device_code} is already paired ({scan.json()['device_id']}); nothing to do")
            return

        paired = http.post(
            f"{api}/devices",
            json={
                "device_qr_payload": args.device_code,
                "elderly_id": elderly_id,
                "device_nickname": args.nickname,
                "timezone": args.timezone,
                "device_pin": args.pin,
            },
            headers=auth,
        )
        if paired.status_code != 201:
            fail("pair", paired)
        print(f"paired {args.device_code} -> device id {paired.json()['id']} (PIN {args.pin})")


if __name__ == "__main__":
    main()
