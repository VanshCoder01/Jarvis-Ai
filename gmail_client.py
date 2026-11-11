"""
gmail_client.py — thin wrapper around the Gmail API for Jarvis's two Gmail
actions (list unread mail, draft a reply).

Scope is deliberately read + compose only (no gmail.send): Jarvis can see
your mail and write a draft sitting in your Drafts folder, but it can never
send anything itself. Same boundary as "Open in Terminal" never running the
code it writes — you review it, you're the one who sends it.

First use opens a real browser tab for Google's own consent screen
(InstalledAppFlow.run_local_server) — nothing silent, same as every other
first-time-auth flow in this app. After that, the refresh token is cached
in %APPDATA%\\Jarvis\\gmail_token.json and reused until you revoke access
from your Google account. See the Gmail section in README.md for the
one-time Google Cloud setup that produces gmail_credentials.json.
"""
import base64
import os
from email.mime.text import MIMEText

APPDATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Jarvis")


def _get_credentials_path():
    cand1 = os.path.join(APPDATA_DIR, "gmail_credentials.json")
    if os.path.exists(cand1):
        return cand1
    cand2 = os.path.join(APPDATA_DIR, "gmail_credentials.json.json")
    if os.path.exists(cand2):
        return cand2
    return cand1


CREDENTIALS_PATH = _get_credentials_path()
TOKEN_PATH = os.path.join(APPDATA_DIR, "gmail_token.json")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]

_service = None


def is_configured() -> bool:
    return os.path.exists(_get_credentials_path())



def _get_service():
    global _service
    if _service is not None:
        return _service

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    if not os.path.exists(CREDENTIALS_PATH):
        raise RuntimeError(
            "No Gmail credentials found. Follow the Gmail setup steps in README.md, "
            "then place credentials.json at " + CREDENTIALS_PATH
        )

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)  # opens a real browser tab for consent
        os.makedirs(APPDATA_DIR, exist_ok=True)
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    _service = build("gmail", "v1", credentials=creds)
    return _service


def _header(headers, name):
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def list_unread(max_results: int = 5):
    """Returns a list of dicts: id, threadId, sender, subject, snippet."""
    service = _get_service()
    resp = service.users().messages().list(
        userId="me", q="is:unread in:inbox", maxResults=max_results
    ).execute()
    out = []
    for m in resp.get("messages", []):
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject"],
        ).execute()
        headers = msg.get("payload", {}).get("headers", [])
        out.append({
            "id": msg["id"],
            "threadId": msg["threadId"],
            "sender": _header(headers, "From"),
            "subject": _header(headers, "Subject") or "(no subject)",
            "snippet": msg.get("snippet", ""),
        })
    return out


def find_message(query: str):
    """Best-matching message for a loose description ("the email from John
    about the deadline"). Falls back to the single most recent unread
    message if the query is blank or matches nothing."""
    service = _get_service()
    search_q = f"in:inbox {query}".strip() if query else "in:inbox is:unread"
    resp = service.users().messages().list(userId="me", q=search_q, maxResults=1).execute()
    ids = resp.get("messages", [])
    if not ids and query:
        resp = service.users().messages().list(userId="me", q="in:inbox is:unread", maxResults=1).execute()
        ids = resp.get("messages", [])
    if not ids:
        return None
    return service.users().messages().get(userId="me", id=ids[0]["id"], format="full").execute()


def _plain_text_body(payload) -> str:
    if payload.get("mimeType") == "text/plain" and "data" in payload.get("body", {}):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "ignore")
    for part in payload.get("parts", []) or []:
        text = _plain_text_body(part)
        if text:
            return text
    return ""


def message_summary(message: dict) -> dict:
    headers = message.get("payload", {}).get("headers", [])
    return {
        "id": message["id"],
        "threadId": message["threadId"],
        "sender": _header(headers, "From"),
        "subject": _header(headers, "Subject") or "(no subject)",
        "message_id_header": _header(headers, "Message-ID"),
        "body": _plain_text_body(message.get("payload", {})) or message.get("snippet", ""),
    }


def create_draft_reply(message: dict, reply_body: str) -> str:
    """Creates a draft reply in the same thread, addressed to the original
    sender and threaded via In-Reply-To/References. Returns the draft id."""
    service = _get_service()
    info = message_summary(message)
    reply = MIMEText(reply_body)
    reply["To"] = info["sender"]
    reply["Subject"] = info["subject"] if info["subject"].lower().startswith("re:") else f"Re: {info['subject']}"
    if info["message_id_header"]:
        reply["In-Reply-To"] = info["message_id_header"]
        reply["References"] = info["message_id_header"]
    raw = base64.urlsafe_b64encode(reply.as_bytes()).decode("ascii")
    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw, "threadId": info["threadId"]}}
    ).execute()
    return draft.get("id", "")
