"""
enphase_auth.py — Enphase Envoy JWT authentication

Auth flow:
  1. POST to Enlighten login → session_id
  2. POST to Entrez with session_id + serial → JWT for local Envoy

The JWT is long-lived (~1 year). This module auto-refreshes when expired.
Run directly to refresh the token in .env:
    python3 enphase_auth.py
"""

import os
import json
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

ENV_FILE = Path(__file__).parent / ".env"

ENLIGHTEN_LOGIN_URL = "https://enlighten.enphaseenergy.com/login/login.json"
ENTREZ_TOKEN_URL = "https://entrez.enphaseenergy.com/tokens"


def get_session_id(email: str, password: str) -> str:
    """Login to Enlighten, return session_id."""
    resp = requests.post(ENLIGHTEN_LOGIN_URL, data={
        "user[email]": email,
        "user[password]": password,
    })
    resp.raise_for_status()
    data = resp.json()
    if data.get("message") != "success":
        raise RuntimeError(f"Enlighten login failed: {data}")
    return data["session_id"]


def get_envoy_jwt(session_id: str, serial: str, email: str) -> str:
    """Exchange Enlighten session for a local Envoy JWT."""
    resp = requests.post(ENTREZ_TOKEN_URL, json={
        "session_id": session_id,
        "serial_num": serial,
        "username": email,
    })
    resp.raise_for_status()
    return resp.text.strip()


def token_expiry(jwt: str) -> int:
    """Decode JWT exp claim (no signature verification needed)."""
    try:
        import base64
        payload = jwt.split(".")[1]
        # Add padding
        payload += "=" * (4 - len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data.get("exp", 0)
    except Exception:
        return 0


def is_token_valid(jwt: str, buffer_days: int = 30) -> bool:
    """Return True if token is still valid with buffer_days remaining."""
    exp = token_expiry(jwt)
    return exp > (time.time() + buffer_days * 86400)


def load_token() -> str:
    """
    Load ENPHASE_TOKEN from .env.
    If missing or expiring within 30 days, auto-refresh and save.
    Requires ENPHASE_EMAIL and ENPHASE_PASSWORD in .env (or env vars).
    """
    load_dotenv(ENV_FILE, override=True)
    token = os.getenv("ENPHASE_TOKEN", "").strip()

    if token and is_token_valid(token):
        return token

    # Refresh needed
    email = os.getenv("ENPHASE_EMAIL", "rob.hartwig@gmail.com")
    password = os.getenv("ENPHASE_PASSWORD")
    serial = os.getenv("ENPHASE_SERIAL")

    if not password:
        raise RuntimeError(
            "ENPHASE_TOKEN is expired/missing and ENPHASE_PASSWORD not set in .env. "
            "Run: python3 enphase_auth.py to refresh manually."
        )

    print("Refreshing Enphase JWT token...")
    session_id = get_session_id(email, password)
    new_token = get_envoy_jwt(session_id, serial, email)
    save_token(new_token)
    print(f"Token refreshed. Expires: {time.strftime('%Y-%m-%d', time.localtime(token_expiry(new_token)))}")
    return new_token


def save_token(token: str):
    """Update ENPHASE_TOKEN in .env (in-place)."""
    lines = ENV_FILE.read_text().splitlines()
    updated = []
    replaced = False
    for line in lines:
        if line.startswith("ENPHASE_TOKEN="):
            updated.append(f"ENPHASE_TOKEN={token}")
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        updated.append(f"ENPHASE_TOKEN={token}")
    ENV_FILE.write_text("\n".join(updated) + "\n")


def envoy_request(path: str, token: str = None) -> dict:
    """
    Make an authenticated request to the local Envoy.
    path: e.g. "/api/v1/production" or "/ivp/meters/readings"
    """
    if token is None:
        token = load_token()
    envoy_ip = os.getenv("ENPHASE_IP", "192.168.68.63")
    url = f"https://{envoy_ip}{path}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=5)
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    import sys
    load_dotenv(ENV_FILE)

    print(f"Enphase Envoy: {os.getenv('ENPHASE_IP')} (serial {os.getenv('ENPHASE_SERIAL')})")

    token = os.getenv("ENPHASE_TOKEN", "").strip()
    if token:
        exp = token_expiry(token)
        days_left = (exp - time.time()) / 86400
        print(f"Current token expires: {time.strftime('%Y-%m-%d', time.localtime(exp))} ({days_left:.0f} days)")
        if "--force" not in sys.argv and is_token_valid(token, buffer_days=30):
            print("Token is still valid. Use --force to refresh anyway.")
            sys.exit(0)

    # Refresh
    email = os.getenv("ENPHASE_EMAIL", "rob.hartwig@gmail.com")
    password = os.getenv("ENPHASE_PASSWORD")
    serial = os.getenv("ENPHASE_SERIAL")

    if not password:
        print("ERROR: Set ENPHASE_PASSWORD in .env to refresh automatically.")
        sys.exit(1)

    session_id = get_session_id(email, password)
    print(f"Session: {session_id}")
    new_token = get_envoy_jwt(session_id, serial, email)
    save_token(new_token)
    exp = token_expiry(new_token)
    print(f"Token saved. Expires: {time.strftime('%Y-%m-%d', time.localtime(exp))}")
