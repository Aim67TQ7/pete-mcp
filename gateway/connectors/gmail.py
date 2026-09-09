"""Gmail multi-account adapter (PETE = pete@by-pete.com mailbox, LEAN =
bunting.lean account) using Google OAuth refresh tokens stored server-side.

Send is a write op: requires connector:gmail:send scope, an effect_key, and a
policy re-check; a simulated send never marks anything contacted (spec)."""
import base64
from email.message import EmailMessage

import httpx

from ..config import Settings
from . import ConnectorError, ConnectorStatus, classify_http

INSTANCES = ["PETE", "LEAN"]

OPERATIONS = {
    "profile": {"write": False},
    "search": {"write": False},    # params: q, max_results?
    "get_message": {"write": False},  # params: id
    "send": {"write": True},       # params: to, subject, body_text
    "accounts": {"write": False},
}


def _oauth_env(account: str) -> tuple[str, str, str]:
    acct = (account or "").upper()
    if acct not in INSTANCES:
        raise ConnectorError("unavailable", f"unknown account '{account}'. Registered: {', '.join(INSTANCES)}")
    cid = Settings.secret(f"GMAIL_{acct}_CLIENT_ID")
    csec = Settings.secret(f"GMAIL_{acct}_CLIENT_SECRET")
    rtok = Settings.secret(f"GMAIL_{acct}_REFRESH_TOKEN")
    if not all([cid, csec, rtok]):
        raise ConnectorError("unconfigured", f"GMAIL_{acct}_CLIENT_ID/_CLIENT_SECRET/_REFRESH_TOKEN not all set")
    return cid, csec, rtok


async def _access_token(account: str) -> str:
    cid, csec, rtok = _oauth_env(account)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post("https://oauth2.googleapis.com/token", data={
                "client_id": cid, "client_secret": csec,
                "refresh_token": rtok, "grant_type": "refresh_token",
            })
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise ConnectorError("unavailable", f"transport failure: {type(exc).__name__}")
    if resp.status_code != 200:
        raise ConnectorError("reauth_required", "Google token refresh rejected; reauthorize this mailbox")
    return resp.json()["access_token"]


async def _api(account: str, method: str, path: str, *, query=None, body=None) -> dict:
    token = await _access_token(account)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                method, f"https://gmail.googleapis.com/gmail/v1/users/me{path}",
                params=query, json=body, headers={"Authorization": f"Bearer {token}"})
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise ConnectorError("unavailable", f"transport failure: {type(exc).__name__}")
    state = classify_http(resp.status_code)
    if state != "connected":
        raise ConnectorError(state, f"Gmail API returned HTTP {resp.status_code}")
    if resp.status_code >= 400:
        raise ConnectorError("unavailable", f"Gmail API returned HTTP {resp.status_code}")
    return resp.json()


async def run(operation: str, params: dict, instance: str | None) -> dict:
    if operation == "accounts":
        return {"accounts": INSTANCES}
    if instance is None:
        raise ConnectorError("unavailable", "instance (account) required: PETE | LEAN")
    if operation == "profile":
        data = await _api(instance, "GET", "/profile")
        return {"account": instance.upper(), "email": data.get("emailAddress"),
                "messages_total": data.get("messagesTotal")}
    if operation == "search":
        data = await _api(instance, "GET", "/messages", query={
            "q": str(params.get("q", "")), "maxResults": min(int(params.get("max_results", 10)), 50)})
        return {"account": instance.upper(),
                "messages": data.get("messages", []), "estimate": data.get("resultSizeEstimate")}
    if operation == "get_message":
        data = await _api(instance, "GET", f"/messages/{params['id']}", query={"format": "metadata"})
        return {"account": instance.upper(), "message": data}
    if operation == "send":
        to, subject, body_text = params.get("to"), params.get("subject"), params.get("body_text")
        if not all([to, subject, body_text]):
            raise ConnectorError("unavailable", "send requires to, subject, body_text")
        profile = await _api(instance, "GET", "/profile")
        msg = EmailMessage()
        msg["To"] = to
        msg["From"] = profile["emailAddress"]  # verified sender identity (spec)
        msg["Subject"] = subject
        msg.set_content(body_text)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        data = await _api(instance, "POST", "/messages/send", body={"raw": raw})
        return {"account": instance.upper(), "sent_message_id": data.get("id"),
                "thread_id": data.get("threadId"), "provider_evidence": True}
    raise ConnectorError("unavailable", f"unknown operation '{operation}'")


async def probe() -> ConnectorStatus:
    st = ConnectorStatus("gmail", "unconfigured")
    states = {}
    for acct in INSTANCES:
        try:
            await _access_token(acct)
            states[acct] = "connected"
        except ConnectorError as exc:
            states[acct] = exc.state
        except Exception:
            states[acct] = "unavailable"
    st.instances = states
    if any(s == "connected" for s in states.values()):
        st.state = "connected"
    elif any(s == "reauth_required" for s in states.values()):
        st.state = "reauth_required"
    return st
