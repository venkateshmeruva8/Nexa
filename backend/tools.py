import asyncio
import logging
import os
import sys
import base64
import smtplib
import socket
import json
import sqlite3
import subprocess
import re
import csv
import time
import threading
import hashlib
import secrets
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart  
from email.mime.text import MIMEText
from typing import Optional, Dict, Any, Tuple, List, Callable, Set
from pathlib import Path
from dotenv import load_dotenv

try:
    from backend.mcp.agent_tools import KOLKATA_TZ, normalize_to_kolkata_rfc3339
except ImportError:
    from mcp.agent_tools import KOLKATA_TZ, normalize_to_kolkata_rfc3339

# Safe console encoding for Windows to prevent UnicodeEncodeError on emojis/symbols
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="backslashreplace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(errors="backslashreplace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")
load_dotenv()

# Preload ML action module and model bundle to avoid event-loop stall on first desktop action
try:
    from actions import route_intent, get_model_bundle, _find_files_sync
except ImportError:
    try:
        from backend.actions import route_intent, get_model_bundle, _find_files_sync  # type: ignore
    except ImportError:
        route_intent = None  # type: ignore
        get_model_bundle = None  # type: ignore
        _find_files_sync = None  # type: ignore

if get_model_bundle is not None:
    try:
        get_model_bundle()
    except Exception:
        pass

from livekit.agents import function_tool, RunContext
import aiohttp


@function_tool()
async def get_weather(
    context: RunContext,  # type: ignore
    city: str) -> str:
    """
    Get the current weather for a given city.
    """
    try:
        url = f"https://wttr.in/{city}?format=3"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    text = (await response.text()).strip()
                    safe_log = text.encode("ascii", "backslashreplace").decode("ascii")
                    logging.info(f"Weather for {city}: {safe_log}")
                    return text
                else:
                    logging.error(f"Failed to get weather for {city}: {response.status}")
                    return f"Could not retrieve weather for {city}."
    except Exception as e:
        logging.error(f"Error retrieving weather for {city}: {e}")
        return f"An error occurred while retrieving weather for {city}." 
 

def _format_search_results(results: List[Dict[str, str]]) -> str:
    """Formats structured search results into a clean, numbered list."""
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "").strip()
        url = r.get("url", "").strip()
        snippet = r.get("snippet", "").strip()
        if snippet and url:
            lines.append(f"{i}. {title}: {snippet} ({url})")
        elif url:
            lines.append(f"{i}. {title} ({url})")
        elif snippet:
            lines.append(f"{i}. {title}: {snippet}")
        else:
            lines.append(f"{i}. {title}")
    return "\n".join(lines)


def _extract_ddg_html_results(page_html: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Extracts structured search results (title, destination URL, snippet) from DuckDuckGo HTML."""
    import html
    import urllib.parse

    raw_blocks = re.findall(
        r'<div[^>]*class="[^"]*result__body[^"]*"[^>]*>(.*?)(?=<div[^>]*class="[^"]*result__body|\Z)',
        page_html,
        re.DOTALL
    )
    if not raw_blocks:
        raw_blocks = re.findall(
            r'<div[^>]*class="[^"]*web-result[^"]*"[^>]*>(.*?)(?=<div[^>]*class="[^"]*web-result|\Z)',
            page_html,
            re.DOTALL
        )

    results: List[Dict[str, str]] = []
    for b in raw_blocks:
        title_m = re.search(r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', b, re.DOTALL)
        snippet_m = re.search(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', b, re.DOTALL)
        if not snippet_m:
            snippet_m = re.search(r'class="[^"]*snippet[^"]*"[^>]*>(.*?)</a>', b, re.DOTALL)

        if title_m:
            raw_href = title_m.group(1)
            raw_title = title_m.group(2)
            
            # Unwrap DuckDuckGo redirect to direct target URL
            if "uddg=" in raw_href:
                m = re.search(r'uddg=([^&]+)', raw_href)
                actual_url = urllib.parse.unquote(m.group(1)) if m else raw_href
            else:
                actual_url = raw_href
            if actual_url.startswith("//"):
                actual_url = "https:" + actual_url

            clean_title = html.unescape(re.sub(r'<[^>]+>', '', raw_title)).strip()
            clean_title = re.sub(r'\s+', ' ', clean_title)
            clean_snippet = ""
            if snippet_m:
                clean_snippet = html.unescape(re.sub(r'<[^>]+>', '', snippet_m.group(1))).strip()
                clean_snippet = re.sub(r'\s+', ' ', clean_snippet)

            if clean_title and actual_url:
                results.append({
                    "title": clean_title,
                    "url": actual_url,
                    "snippet": clean_snippet
                })
                if len(results) >= max_results:
                    break
    return results


def _fetch_ddg_html_sync(query: str) -> Optional[str]:
    """Synchronous fetcher for DuckDuckGo HTML/Lite search pages using browser-like headers."""
    import urllib.parse
    import urllib.request
    import ssl

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://duckduckgo.com/",
    }
    ctx = ssl.create_default_context()
    
    # 1. Try html.duckduckgo.com/html/
    try:
        encoded = urllib.parse.quote(query.strip())
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=6, context=ctx) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8", errors="ignore")
                if "anomaly" not in body and ("result__a" in body or "result__body" in body):
                    return body
    except Exception:
        pass

    # 2. Try lite.duckduckgo.com/lite/
    try:
        data = urllib.parse.urlencode({"q": query.strip()}).encode("utf-8")
        req_lite = urllib.request.Request("https://lite.duckduckgo.com/lite/", data=data, headers=headers)
        with urllib.request.urlopen(req_lite, timeout=5, context=ctx) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8", errors="ignore")
                if "anomaly" not in body and "result-link" in body:
                    return body
    except Exception:
        pass

    return None


def _fetch_ddg_instant_sync(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Synchronous fallback to DuckDuckGo Instant Answer API."""
    import urllib.parse
    import urllib.request
    import ssl
    import json

    results: List[Dict[str, str]] = []
    try:
        encoded = urllib.parse.quote(query.strip())
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
        req = urllib.request.Request(url, headers=headers)
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                abstract = data.get("AbstractText", "").strip()
                heading = data.get("Heading", "").strip()
                abs_url = data.get("AbstractURL", "").strip()
                if abstract:
                    results.append({
                        "title": heading or query,
                        "url": abs_url,
                        "snippet": abstract
                    })

                topics = data.get("RelatedTopics", [])
                for t in topics:
                    if isinstance(t, dict):
                        text = t.get("Text", "").strip()
                        first_url = t.get("FirstURL", "").strip()
                        if text:
                            parts = text.split(" - ", 1)
                            t_title = parts[0] if len(parts) > 1 else heading or query
                            t_snippet = parts[1] if len(parts) > 1 else text
                            results.append({
                                "title": t_title,
                                "url": first_url,
                                "snippet": t_snippet
                            })
                            if len(results) >= max_results:
                                break
    except Exception:
        pass
    return results


async def _duckduckgo_web_search(query: str, max_results: int = 5, dry_run: bool = False) -> Tuple[str, str]:
    """
    Performs a DuckDuckGo search. Returns (status, message).
    status is one of: 'programmatic', 'browser_fallback', or 'failed'.
    """
    import urllib.parse
    import webbrowser
    cleaned = query.strip()
    
    # 1. Programmatic DDG HTML
    html_page = await asyncio.to_thread(_fetch_ddg_html_sync, cleaned)
    if html_page:
        items = _extract_ddg_html_results(html_page, max_results=max_results)
        if items:
            return ("programmatic", _format_search_results(items))

    # 2. Programmatic DDG Instant Answer
    instant_items = await asyncio.to_thread(_fetch_ddg_instant_sync, cleaned, max_results=max_results)
    if instant_items:
        return ("programmatic", _format_search_results(instant_items))

    # 3. Final Fallback: Default Browser
    try:
        encoded = urllib.parse.quote(cleaned)
        url = f"https://duckduckgo.com/?q={encoded}"
        if not dry_run:
            webbrowser.open(url)
        return ("browser_fallback", "I couldn't retrieve the results directly, so I've opened the web search for you.")
    except Exception as e:
        logging.error(f"Error opening browser fallback for search '{cleaned}': {e}")
        return ("failed", f"Could not perform web search for '{cleaned}'.")


@function_tool()
async def search_web(
    context: RunContext,  # type: ignore
    query: str,
    dry_run: bool = False) -> str:
    """
    Search the web using DuckDuckGo HTML search and optional Google Custom Search with graceful browser fallback.
    """
    if not query or not query.strip():
        return "Please provide a search term."

    cleaned_query = query.strip()

    # Optional Google Custom Search if valid credentials exist
    api_key = os.getenv("GOOGLE_SEARCH_API_KEY") or os.getenv("GOOGLE_API_KEY")
    cse_id = os.getenv("GOOGLE_CSE_ID")

    if api_key and cse_id and cse_id != "YOUR_GOOGLE_CSE_ID":
        try:
            url = "https://www.googleapis.com/customsearch/v1"
            params = {
                "key": api_key,
                "cx": cse_id,
                "q": cleaned_query,
                "num": 5
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        items = data.get("items", [])
                        if items:
                            results = []
                            for item in items[:5]:
                                title = item.get("title", "").strip()
                                snippet = item.get("snippet", "").replace("\n", " ").strip()
                                link = item.get("link", "").strip()
                                results.append({"title": title, "url": link, "snippet": snippet})
                            formatted = _format_search_results(results)
                            logging.info(f"Google search results for '{cleaned_query}': {formatted}")
                            return formatted
                    else:
                        logging.warning(f"Google Search returned status {response.status}, falling back automatically to DuckDuckGo.")
        except Exception as e:
            logging.warning(f"Google search error for '{cleaned_query}': {e}, falling back automatically to DuckDuckGo.")

    # DuckDuckGo programmatic search with browser fallback
    status, result_text = await _duckduckgo_web_search(cleaned_query, max_results=5, dry_run=dry_run)
    return result_text



# Shared in-memory email dispatch tracker for duplicate suppression
_RECENT_EMAIL_DISPATCHES: List[Tuple[str, str, float]] = []
_EMAIL_DEBOUNCE_SECONDS = 10.0
_EMAIL_CONFIRMATION_TIMEOUT_SECONDS = 300.0  # 5-minute confirmation timeout

# Session-isolated pending email staging store: session_id -> pending_dict
_PENDING_EMAIL_SESSIONS: Dict[str, Dict[str, Any]] = {}

# Session-isolated pending recipient verification store: session_id -> candidate_dict
_PENDING_RECIPIENT_VERIFICATIONS: Dict[str, Dict[str, Any]] = {}
_RECIPIENT_VERIFICATION_TIMEOUT_SECONDS = 300.0  # 5-minute timeout matching draft staging
_ENFORCE_RECIPIENT_VERIFICATION_SESSIONS: Set[str] = set()


_CURRENT_ACTIVE_SESSION_ID: str = "default_session"


def set_current_active_session_id(session_id: str) -> None:
    """Sets the active session ID for the worker process."""
    global _CURRENT_ACTIVE_SESSION_ID
    if session_id and str(session_id).strip():
        _CURRENT_ACTIVE_SESSION_ID = str(session_id).strip()


def get_current_active_session_id() -> str:
    """Returns the current active session ID."""
    return _CURRENT_ACTIVE_SESSION_ID


def _extract_session_id(context: Any) -> str:
    """Extracts a reliable, isolated session identifier from RunContext, room, or agent."""
    if context is not None:
        try:
            sess = getattr(context, "session", None) or getattr(context, "_session", None)
            if sess is not None:
                try:
                    room_io = getattr(sess, "room_io", None) or getattr(sess, "_room_io", None)
                    if room_io:
                        room = getattr(room_io, "room", None) or getattr(room_io, "_room", None)
                        if room:
                            rname = getattr(room, "name", None)
                            if isinstance(rname, str) and rname.strip():
                                return rname.strip()
                except Exception:
                    pass
                sid = getattr(sess, "id", None) or getattr(sess, "session_id", None)
                if isinstance(sid, str) and sid.strip():
                    return sid.strip()
        except Exception:
            pass
        room = getattr(context, "room", None)
        if room is not None:
            rname = getattr(room, "name", None)
            if isinstance(rname, str) and rname.strip():
                return rname.strip()
        agent = getattr(context, "agent", None)
        if agent is not None:
            aid = getattr(agent, "session_id", None) or getattr(agent, "id", None)
            if isinstance(aid, str) and aid.strip():
                return aid.strip()
        if isinstance(context, str) and context.strip():
            return context.strip()
    return get_current_active_session_id()


def _resolve_pending_session_key(session_id: str) -> Optional[str]:
    """Resolves the session key for pending email lookups while preserving cross-session isolation."""
    if not session_id or not str(session_id).strip():
        clean_id = get_current_active_session_id().strip()
    else:
        clean_id = str(session_id).strip()

    if clean_id in _PENDING_EMAIL_SESSIONS:
        return clean_id

    # Fallback only for generic default_session or current active session ID
    active_id = get_current_active_session_id().strip()
    if clean_id == "default_session" and active_id in _PENDING_EMAIL_SESSIONS:
        return active_id
    if clean_id == active_id and "default_session" in _PENDING_EMAIL_SESSIONS:
        return "default_session"

    return None


def has_pending_email_for_session(session_id: str = "default_session") -> bool:
    """Returns True if an unexpired email draft is awaiting user approval for this session."""
    key = _resolve_pending_session_key(session_id)
    if not key:
        return False
    staged = _PENDING_EMAIL_SESSIONS.get(key)
    if not staged:
        return False
    now = time.time()
    staged_at = staged.get("staged_at", 0.0)
    if (now - staged_at) > _EMAIL_CONFIRMATION_TIMEOUT_SECONDS:
        clear_pending_email_for_session(key)
        return False
    return True


def get_pending_email_for_session(session_id: str = "default_session") -> Optional[Dict[str, Any]]:
    """Returns the staged email awaiting user approval for the given session, if any."""
    key = _resolve_pending_session_key(session_id)
    if not key:
        return None
    return _PENDING_EMAIL_SESSIONS.get(key)


def clear_pending_email_for_session(session_id: str = "default_session") -> bool:
    """Clears any pending email confirmation state for the specified session."""
    key = _resolve_pending_session_key(session_id)
    if key and key in _PENDING_EMAIL_SESSIONS:
        del _PENDING_EMAIL_SESSIONS[key]
        return True
    return False


def cancel_staged_email(session_id: str = "default_session") -> str:
    """Cancels any staged email draft for the specified session."""
    if clear_pending_email_for_session(session_id):
        return "Staged email draft has been cancelled."
    return "There is no pending email draft to cancel."


def get_pending_email_confirmation() -> Optional[Dict[str, Any]]:
    """Compatibility helper returning staged email for default session."""
    return get_pending_email_for_session("default_session")


def clear_pending_email_confirmation() -> None:
    """Clears pending email state across all sessions."""
    global _PENDING_EMAIL_SESSIONS
    _PENDING_EMAIL_SESSIONS.clear()


def _is_live_agent_context(context: Any) -> bool:
    """
    Returns True if context originates from a live LiveKit Agent session
    (e.g. RunContext containing room, session, or agent objects).
    """
    if context is None or isinstance(context, str):
        return False
    return bool(
        hasattr(context, "session")
        or hasattr(context, "room")
        or hasattr(context, "agent")
        or hasattr(context, "_session")
    )


def set_enforce_recipient_verification_for_session(session_id: str, enforce: bool = True) -> None:
    """Enforces recipient verification for the specified session (used for testing or explicit sessions)."""
    clean_id = (session_id or "").strip() or get_current_active_session_id().strip()
    if enforce:
        _ENFORCE_RECIPIENT_VERIFICATION_SESSIONS.add(clean_id)
    else:
        _ENFORCE_RECIPIENT_VERIFICATION_SESSIONS.discard(clean_id)


def _resolve_recipient_verification_session_key(session_id: str) -> Optional[str]:
    """Resolves the session key for pending recipient verification lookups while preserving isolation."""
    if not session_id or not str(session_id).strip():
        clean_id = get_current_active_session_id().strip()
    else:
        clean_id = str(session_id).strip()

    if clean_id in _PENDING_RECIPIENT_VERIFICATIONS:
        return clean_id

    active_id = get_current_active_session_id().strip()
    if clean_id == "default_session" and active_id in _PENDING_RECIPIENT_VERIFICATIONS:
        return active_id
    if clean_id == active_id and "default_session" in _PENDING_RECIPIENT_VERIFICATIONS:
        return "default_session"

    return None


def has_pending_recipient_verification_for_session(session_id: str = "default_session") -> bool:
    """Returns True if an unexpired candidate recipient verification is pending for this session."""
    key = _resolve_recipient_verification_session_key(session_id)
    if not key:
        return False
    pending = _PENDING_RECIPIENT_VERIFICATIONS.get(key)
    if not pending:
        return False
    now = time.time()
    created_at = pending.get("created_at", 0.0)
    if (now - created_at) > _RECIPIENT_VERIFICATION_TIMEOUT_SECONDS:
        clear_pending_recipient_verification_for_session(key)
        return False
    return True


def get_pending_recipient_verification_for_session(session_id: str = "default_session") -> Optional[Dict[str, Any]]:
    """Returns the pending recipient verification record for session if valid and unexpired."""
    key = _resolve_recipient_verification_session_key(session_id)
    if not key:
        return None
    pending = _PENDING_RECIPIENT_VERIFICATIONS.get(key)
    if not pending:
        return None
    now = time.time()
    if (now - pending.get("created_at", 0.0)) > _RECIPIENT_VERIFICATION_TIMEOUT_SECONDS:
        clear_pending_recipient_verification_for_session(key)
        return None
    return pending


def set_pending_recipient_verification_for_session(
    session_id: str,
    candidate_to: str,
    subject: str,
    message: str,
    cc_email: Optional[str] = None
) -> Dict[str, Any]:
    """Registers an unverified candidate recipient draft for the specified session."""
    clean_session = str(session_id).strip() if (session_id and str(session_id).strip()) else get_current_active_session_id().strip()
    now = time.time()
    record = {
        "session_id": clean_session,
        "candidate_to": candidate_to.strip(),
        "subject": (subject or "").strip(),
        "message": (message or "").strip(),
        "cc_email": (cc_email or "").strip() or None,
        "verified": False,
        "created_at": now,
    }
    _PENDING_RECIPIENT_VERIFICATIONS[clean_session] = record
    return record


def update_pending_recipient_for_session(session_id: str, new_candidate_to: str) -> Tuple[bool, str]:
    """
    Updates the candidate recipient address upon user correction.
    Resets verification to False and created_at to now.
    """
    key = _resolve_recipient_verification_session_key(session_id)
    if not key or key not in _PENDING_RECIPIENT_VERIFICATIONS:
        return False, "There is no pending email recipient to update."

    clean_new = (new_candidate_to or "").strip()
    if not clean_new or not re.match(r"^[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}$", clean_new):
        return False, f"Invalid recipient email address: '{new_candidate_to}'. Please provide a valid email address (e.g., user@example.com)."

    pending = _PENDING_RECIPIENT_VERIFICATIONS[key]
    pending["candidate_to"] = clean_new
    pending["verified"] = False
    pending["created_at"] = time.time()

    return True, _format_recipient_verification_prompt(clean_new)


def confirm_pending_recipient_for_session(
    session_id: str,
    user_authorized: bool = False
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Validates user authorization, marks the candidate recipient verified,
    clears pending verification, and stages the draft into _PENDING_EMAIL_SESSIONS.
    
    SECURITY GUARANTEE:
    1. Must verify user_authorized is True (originating from a trusted local user event).
    2. Recipient confirmation stages the draft for review, but NEVER authorizes SMTP dispatch.
    """
    if not user_authorized:
        return False, None, "Access denied: Recipient verification requires explicit authorization from a genuine user-originated event."

    key = _resolve_recipient_verification_session_key(session_id)
    if not key or key not in _PENDING_RECIPIENT_VERIFICATIONS:
        return False, None, "Cannot confirm recipient: No pending recipient verification was found for this session."

    pending = _PENDING_RECIPIENT_VERIFICATIONS[key]
    now = time.time()
    if (now - pending.get("created_at", 0.0)) > _RECIPIENT_VERIFICATION_TIMEOUT_SECONDS:
        clear_pending_recipient_verification_for_session(key)
        return False, None, "The pending recipient verification request has expired (5-minute timeout). Please provide the email details again."

    clean_to = pending["candidate_to"]
    clean_sub = pending["subject"]
    clean_msg = pending["message"]
    clean_cc = pending.get("cc_email")

    # Remove from pending recipient verification store
    del _PENDING_RECIPIENT_VERIFICATIONS[key]

    # Stage pending email draft isolated strictly to this session
    current_fp = _email_fingerprint(clean_to, clean_sub, clean_msg, clean_cc)
    token = secrets.token_hex(16)
    _PENDING_EMAIL_SESSIONS[key] = {
        "session_id": key,
        "to_email": clean_to,
        "subject": clean_sub,
        "message": clean_msg,
        "cc_email": clean_cc,
        "fingerprint": current_fp,
        "token": token,
        "staged_at": now,
    }

    logging.info(
        "RECIPIENT_VERIFICATION_CONFIRMED: session_id=%s, verified_to=%s",
        key,
        clean_to,
    )
    logging.info(
        "EMAIL_DRAFT_PENDING: session_id=%s, to=%s, subject='%s'",
        key,
        clean_to,
        clean_sub,
    )

    summary = _format_pending_email_summary(clean_to, clean_sub, clean_msg, clean_cc)
    return True, _PENDING_EMAIL_SESSIONS[key], summary


def cancel_pending_recipient_verification_for_session(session_id: str = "default_session") -> str:
    """Cancels any pending recipient verification candidate for the specified session."""
    key = _resolve_recipient_verification_session_key(session_id)
    if key and key in _PENDING_RECIPIENT_VERIFICATIONS:
        del _PENDING_RECIPIENT_VERIFICATIONS[key]
        logging.info("RECIPIENT_VERIFICATION_CANCELLED: session_id=%s", key)
        return "Recipient verification cancelled. Email draft discarded."
    return "There is no pending recipient verification to cancel."


def clear_pending_recipient_verification_for_session(session_id: str = "default_session") -> bool:
    """Clears pending recipient verification state for session."""
    key = _resolve_recipient_verification_session_key(session_id)
    if key and key in _PENDING_RECIPIENT_VERIFICATIONS:
        del _PENDING_RECIPIENT_VERIFICATIONS[key]
        return True
    return False


def clear_all_pending_recipient_verifications() -> None:
    """Clears pending recipient verification state across all sessions."""
    global _PENDING_RECIPIENT_VERIFICATIONS, _ENFORCE_RECIPIENT_VERIFICATION_SESSIONS
    _PENDING_RECIPIENT_VERIFICATIONS.clear()
    _ENFORCE_RECIPIENT_VERIFICATION_SESSIONS.clear()


def _format_recipient_verification_prompt(candidate_to: str) -> str:
    """Formats an explicit, unambiguous recipient verification prompt."""
    lines = [
        "Recipient Verification Required (Email NOT drafted yet):",
        f"• Candidate Recipient: {candidate_to.strip()}",
        "",
        f"I have the recipient address as '{candidate_to.strip()}'.",
        "Please confirm if this address is correct before I prepare the email draft.",
        "• If correct, please answer YES.",
        "• If incorrect or unclear, please provide or spell out the correct address.",
        "• To cancel, say CANCEL.",
    ]
    return "\n".join(lines)


def _email_fingerprint(to_email: str, subject: str, message: str, cc_email: Optional[str] = None) -> str:
    """Generates a SHA-256 fingerprint binding approval to the exact email contents."""
    norm_to = to_email.strip().lower()
    norm_cc = (cc_email or "").strip().lower()
    norm_sub = subject.strip()
    norm_msg = message.strip()
    payload = f"{norm_to}|{norm_cc}|{norm_sub}|{norm_msg}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _format_pending_email_summary(to_email: str, subject: str, message: str, cc_email: Optional[str] = None) -> str:
    """Formats a safe pending-send summary without exposing credentials."""
    lines = [
        "Email Draft Prepared & Staged (NOT sent yet):",
        f"• To: {to_email.strip()}",
    ]
    if cc_email and cc_email.strip():
        lines.append(f"• CC: {cc_email.strip()}")
    lines.extend([
        f"• Subject: {subject.strip()}",
        f"• Body: {message.strip()}",
        "",
        "Notice: Direct automated email dispatch is disabled to prevent unauthorized transmission.",
        "This email has been drafted and staged for your review. It will not be sent without a verified user approval event.",
        "Please review the recipient, subject, and message above. Would you like me to send this email? Please answer YES to send or NO to cancel."
    ])
    return "\n".join(lines)


def check_and_record_email_dispatch(to_email: str, subject: str) -> bool:
    """
    Prevents duplicate email sends within a 10-second debounce window.
    Returns True if dispatch should proceed, False if duplicate detected.
    """
    global _RECENT_EMAIL_DISPATCHES
    now = time.time()
    _RECENT_EMAIL_DISPATCHES = [
        (to, sub, t) for to, sub, t in _RECENT_EMAIL_DISPATCHES if now - t < 60.0
    ]
    norm_to = to_email.strip().lower()
    norm_sub = subject.strip().lower()
    for to, sub, t in _RECENT_EMAIL_DISPATCHES:
        if to == norm_to and sub == norm_sub and (now - t) < _EMAIL_DEBOUNCE_SECONDS:
            return False
    _RECENT_EMAIL_DISPATCHES.append((norm_to, norm_sub, now))
    return True


@function_tool()    
async def send_email(
    context: RunContext,  # type: ignore
    to_email: str,
    subject: str,
    message: str,
    cc_email: Optional[str] = None,
    require_recipient_verification: Optional[bool] = None,
) -> str:
    """
    Draft and stage an email through Gmail for user review and approval.
    
    CRITICAL SECURITY GUARANTEE:
    This tool prepares and stages an email draft for the user to inspect.
    It does NOT transmit the email. Autonomous model dispatch is strictly disabled.
    Transmission requires explicit authorization from a trusted user confirmation event.
    
    Args:
        to_email: Recipient email address
        subject: Email subject line
        message: Email body content
        cc_email: Optional CC email address
        require_recipient_verification: Optional override for test environments. In live agent contexts, verification is always enforced.
    """
    clean_to = (to_email or "").strip()
    if not clean_to or not re.match(r"^[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}$", clean_to):
        return f"Invalid recipient email address: '{to_email}'. Please provide a valid email address (e.g., user@example.com)."

    clean_cc = (cc_email or "").strip() or None
    if clean_cc and not re.match(r"^[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}$", clean_cc):
        return f"Invalid CC email address: '{cc_email}'. Please provide a valid email address (e.g., user@example.com)."

    clean_subject = (subject or "").strip()
    if not clean_subject:
        return "Email subject cannot be empty. Please provide a subject line."

    clean_message = (message or "").strip()
    if not clean_message:
        return "Email body cannot be empty. Please provide message content."

    gmail_user = os.getenv("GMAIL_USER")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    if not gmail_user or not gmail_password:
        logging.error("Gmail credentials not found in environment variables")
        return "Email could not be prepared because the email account configuration is unavailable or invalid."

    session_id = _extract_session_id(context)
    now = time.time()

    # Determine whether recipient verification is required:
    # Live LiveKit Agent sessions (RunContext) ALWAYS enforce recipient verification.
    # LLM tool call arguments CANNOT disable verification in a live agent context.
    is_live = _is_live_agent_context(context)
    if is_live:
        should_verify = True
    elif require_recipient_verification is not None:
        should_verify = bool(require_recipient_verification)
    else:
        resolved_key = _resolve_recipient_verification_session_key(session_id) or session_id
        should_verify = resolved_key in _ENFORCE_RECIPIENT_VERIFICATION_SESSIONS

    if should_verify:
        set_pending_recipient_verification_for_session(
            session_id=session_id,
            candidate_to=clean_to,
            subject=clean_subject,
            message=clean_message,
            cc_email=clean_cc,
        )
        logging.info(
            "RECIPIENT_VERIFICATION_PENDING: session_id=%s, candidate_to=%s, subject='%s'",
            session_id,
            clean_to,
            clean_subject,
        )
        return _format_recipient_verification_prompt(clean_to)

    current_fp = _email_fingerprint(clean_to, clean_subject, clean_message, clean_cc)
    token = secrets.token_hex(16)

    # Stage pending email isolated strictly to this session
    _PENDING_EMAIL_SESSIONS[session_id] = {
        "session_id": session_id,
        "to_email": clean_to,
        "subject": clean_subject,
        "message": clean_message,
        "cc_email": clean_cc,
        "fingerprint": current_fp,
        "token": token,
        "staged_at": now,
    }

    logging.info(
        "EMAIL_DRAFT_PENDING: session_id=%s, to=%s, subject='%s'",
        session_id,
        clean_to,
        clean_subject,
    )

    return _format_pending_email_summary(clean_to, clean_subject, clean_message, clean_cc)


async def dispatch_staged_email(
    session_id: str,
    confirmation_token: str,
    user_authorized: bool = False
) -> str:
    """
    Secure execution endpoint to transmit a previously staged email.
    
    SECURITY REQUIREMENTS:
    1. Must verify user_authorized is True (originating from a trusted user-input event,
       never from model tool calls or autonomous agent execution).
    2. Must match session_id and the unguessable confirmation_token bound to that session.
    3. Staged email must not be expired (>300 seconds).
    4. Staged record is immediately consumed upon execution (single-use, no replay).
    5. SMTP credentials are never exposed in return values or exceptions.
    """
    if not user_authorized:
        return "Access denied: Email dispatch requires explicit authorization from a genuine user-originated event."

    resolved_key = _resolve_pending_session_key(session_id)
    if not resolved_key or resolved_key not in _PENDING_EMAIL_SESSIONS:
        return "Cannot dispatch email: No pending email was found for this session."

    clean_session = resolved_key
    staged = _PENDING_EMAIL_SESSIONS[clean_session]
    now = time.time()

    # 1. Verify expiration
    staged_at = staged.get("staged_at", 0.0)
    if (now - staged_at) > _EMAIL_CONFIRMATION_TIMEOUT_SECONDS:
        clear_pending_email_for_session(clean_session)
        return "The pending email confirmation request has expired (5-minute timeout). Please review and draft the email again."

    # 2. Verify unguessable token
    expected_token = staged.get("token", "")
    if not confirmation_token or not secrets.compare_digest(confirmation_token.strip(), expected_token):
        return "Access denied: Invalid confirmation token. Dispatch rejected."

    # 3. Consume immediately before network I/O to guarantee single-use and prevent replay
    del _PENDING_EMAIL_SESSIONS[clean_session]

    clean_to = staged["to_email"]
    clean_subject = staged["subject"]
    clean_message = staged["message"]
    clean_cc = staged.get("cc_email")

    logging.info(
        "EMAIL_DISPATCH_AUTHORIZED: session_id=%s, to=%s, subject='%s'",
        clean_session,
        clean_to,
        clean_subject,
    )

    # 4. Duplicate dispatch debounce window
    if not check_and_record_email_dispatch(clean_to, clean_subject):
        logging.warning(f"Duplicate email dispatch blocked for {clean_to} (subject: '{clean_subject}')")
        return f"Notice: Duplicate email dispatch prevented. An email to {clean_to} with subject '{clean_subject}' was already sent moments ago."

    gmail_user = os.getenv("GMAIL_USER")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    if not gmail_user or not gmail_password:
        logging.error("Gmail credentials not found in environment variables")
        return "Email could not be sent because the email account configuration is unavailable or invalid."

    # 5. Connect to SMTP and transmit email via TLS
    smtp_start_mono = time.monotonic()
    logging.info(f"EMAIL_SMTP_DISPATCH_START: to={clean_to}, subject='{clean_subject}'")
    sendmail_started = False
    sendmail_completed = False

    try:
        smtp_server = "smtp.gmail.com"
        smtp_port = 587
        
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = clean_to
        msg['Subject'] = clean_subject
        
        recipients = [clean_to]
        if clean_cc:
            msg['Cc'] = clean_cc
            recipients.append(clean_cc)
        
        msg.attach(MIMEText(clean_message, 'plain'))
        text = msg.as_string()

        def _send_sync() -> None:
            nonlocal sendmail_started, sendmail_completed
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
            server.starttls()
            server.login(gmail_user, gmail_password)
            sendmail_started = True
            server.sendmail(gmail_user, recipients, text)
            sendmail_completed = True
            server.quit()

        await asyncio.to_thread(_send_sync)
        
        elapsed_smtp = time.monotonic() - smtp_start_mono
        logging.info(f"EMAIL_SMTP_DISPATCH_DONE: duration={elapsed_smtp:.3f}s, status=SUCCESS, to={clean_to}")
        return f"Email sent successfully to {clean_to}"
        
    except smtplib.SMTPAuthenticationError as e:
        elapsed_smtp = time.monotonic() - smtp_start_mono
        logging.error(f"EMAIL_SMTP_DISPATCH_DONE: duration={elapsed_smtp:.3f}s, status=FAILED, auth_error={type(e).__name__}")
        return "Email could not be sent because the email account configuration is unavailable or invalid."
    except (socket.error, TimeoutError, ConnectionError, smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected) as e:
        elapsed_smtp = time.monotonic() - smtp_start_mono
        if sendmail_started and not sendmail_completed:
            logging.error(f"EMAIL_SMTP_DISPATCH_DONE: duration={elapsed_smtp:.3f}s, status=UNCERTAIN, network_error={type(e).__name__}")
            return "Warning: Connection dropped during transmission. Delivery status is uncertain; the email may or may not have been delivered. To prevent duplicate messages, it will not be resent automatically. Please check your Sent Mail."
        logging.error(f"EMAIL_SMTP_DISPATCH_DONE: duration={elapsed_smtp:.3f}s, status=FAILED, network_error={type(e).__name__}")
        return "Email sending failed due to a network connection issue. Please verify your internet connection."
    except smtplib.SMTPException as e:
        elapsed_smtp = time.monotonic() - smtp_start_mono
        logging.error(f"EMAIL_SMTP_DISPATCH_DONE: duration={elapsed_smtp:.3f}s, status=FAILED, smtp_error={type(e).__name__}")
        return "Email sending failed due to an email server error. Please try again later."
    except Exception as e:
        elapsed_smtp = time.monotonic() - smtp_start_mono
        logging.error(f"EMAIL_SMTP_DISPATCH_DONE: duration={elapsed_smtp:.3f}s, status=FAILED, error={type(e).__name__}")
        return "Email could not be sent right now. Please try again."

@function_tool()
async def execute_desktop_action(
    context: RunContext,  # type: ignore
    command: str,
    confirmed: bool = False,
    dry_run: bool = False
) -> str:
    """
    Execute local Windows desktop actions using NEXA's machine learning intent engine.
    Controls applications (e.g., Chrome, VS Code, Calculator, Notepad), opens websites in Google Chrome
    (e.g., 'Open YouTube', 'Open Udemy in Chrome', 'Launch Spotify', 'Go to Instagram', 'Open GitHub', 'Open stackoverflow.com'),
    system volume, display brightness,
    Windows settings panels (Wi-Fi, Bluetooth, Sound, Display), system resources and hardware health
    (CPU usage, RAM/memory, Battery level and charging status, Storage drive space, Drive health/low storage warning, System load),
    network connectivity and internet health (internet connection status, Wi-Fi network and signal strength, local IP address,
    public IP address, connection stability, ping/latency, data uploaded/downloaded, network status summary),
    audio & device awareness (volume level, microphone availability and status, camera/webcam availability, active audio devices,
    audio status summary, mute/unmute system volume, mute/unmute microphone),
    folders and files, or system restart/shutdown.
    
    Args:
        command: The user command or request (e.g., 'how much RAM am I using', 'what is my CPU usage', 'how much battery is left', 'is my battery charging', 'how much storage space do I have', 'which drive is running low', 'system status', 'is my laptop under heavy load', 'am I connected to the internet', 'what Wi-Fi network am I connected to', 'what is my local IP address', 'what is my public IP address', 'is my internet connection stable', 'what is my ping', 'how much data have I uploaded', 'give me my network status', 'what is my volume level', 'is my microphone working', 'is my camera available', 'what audio device am I using', 'give me my audio status', 'mute volume', 'unmute volume', 'mute microphone', 'unmute microphone', 'increase volume', 'open downloads folder').
        confirmed: Set to True ONLY if the user has explicitly confirmed a critical action like restart or shutdown. Defaults to False.
        dry_run: If True, simulates destructive actions like restart/shutdown without executing OS power commands. Defaults to False.
    """
    global route_intent
    if route_intent is None:
        try:
            from actions import route_intent
        except ImportError:
            from backend.actions import route_intent  # type: ignore

    logging.info("COMMAND SUBMITTED: %s", command)
    result = await route_intent(text=command, confirmed=confirmed, run_context=context, dry_run=dry_run)
    logging.info("RESPONSE GENERATED")
    return result["result"]


@function_tool()
async def trigger_n8n_workflow(
    context: RunContext,  # type: ignore
    workflow_name: str,
    payload: Optional[str] = None
) -> str:
    """
    Trigger a specific custom automated workflow in n8n via webhook.
    Do NOT use this tool for Google Calendar scheduling, meeting appointments, or email dispatch.
    
    Args:
        workflow_name: The name or path identifier of the custom workflow to trigger.
        payload: Optional JSON string or message text to send to the workflow.
    """
    # Guard against misuse for calendar/meeting scheduling or email dispatch
    cal_and_email_keywords = ("calendar", "event", "schedule", "meeting", "email", "mail")
    clean_wf = workflow_name.lower().replace("-", "_")
    if any(k in clean_wf for k in cal_and_email_keywords):
        return (
            "Notice: trigger_n8n_workflow cannot be used for calendar scheduling or email dispatch. "
            "Please use dedicated calendar or email tools instead."
        )

    try:
        base_url = os.getenv("N8N_WEBHOOK_URL")
        if not base_url or not base_url.strip():
            return "n8n integration is not configured. Please set N8N_WEBHOOK_URL in environment variables."
        
        target_url = base_url.strip()
        if not target_url.endswith("/") and not target_url.endswith(workflow_name):
            target_url = f"{target_url}/{workflow_name}"
            
        data: Dict[str, Any] = {"workflow": workflow_name}
        if payload:
            try:
                data["data"] = json.loads(payload)
            except Exception:
                data["message"] = payload
                
        async with aiohttp.ClientSession() as session:
            async with session.post(
                target_url,
                json=data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status in (200, 201, 204):
                    text = (await response.text()).strip()
                    logging.info(f"Triggered n8n workflow '{workflow_name}' successfully: {text[:100]}")
                    return f"Workflow '{workflow_name}' triggered successfully. Response: {text[:200]}"
                else:
                    logging.warning(f"n8n webhook returned status {response.status} for workflow '{workflow_name}'")
                    return f"Triggered workflow '{workflow_name}', but received HTTP status {response.status}."
    except Exception as e:
        logging.error(f"Error triggering n8n workflow '{workflow_name}': {e}")
        return f"Failed to trigger n8n workflow '{workflow_name}': n8n service is offline or unreachable ({type(e).__name__})."


# ---------------------------------------------------------------------------
# Local Reminders & Timers Implementation
# ---------------------------------------------------------------------------

REMINDERS_DB_PATH = Path(__file__).resolve().parent / "data" / "reminders.db"
_ACTIVE_REMINDERS: Dict[int, asyncio.Task] = {}
_REMINDER_DEDUP_LOCK = threading.Lock()
_RECENT_REMINDER_EXECUTIONS: List[Dict[str, Any]] = []
_RECENT_CANCELLATIONS: List[Dict[str, Any]] = []
_REMINDER_DEDUP_WINDOW_SECONDS = 15.0


def _normalize_reminder_text_for_dedup(text: str) -> str:
    """Normalize reminder text for single-execution deduplication matching."""
    norm = text.lower().strip()
    norm = re.sub(
        r"^(?:please\s+)?(?:remind\s+me\s+to|set\s+a\s+reminder\s+to|set\s+timer\s+for|set\s+a\s+timer\s+for)\s+",
        "",
        norm,
    )
    norm = re.sub(r"[^\w\s]", "", norm)
    return " ".join(norm.split())


def _init_reminders_db() -> None:
    """Initialize SQLite database table for persistent reminders."""
    REMINDERS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(REMINDERS_DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                target_time TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )
        """)
        conn.commit()


def _save_reminder(text: str, target_time_str: str) -> int:
    """Persist a new reminder record in SQLite."""
    _init_reminders_db()
    now_str = datetime.now(KOLKATA_TZ).isoformat()
    with sqlite3.connect(str(REMINDERS_DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reminders (text, target_time, created_at, status) VALUES (?, ?, ?, 'pending')",
            (text, target_time_str, now_str)
        )
        conn.commit()
        return cursor.lastrowid or 0


def _update_reminder_status(reminder_id: int, status: str) -> None:
    """Update status of a reminder (e.g. 'fired', 'cancelled')."""
    try:
        with sqlite3.connect(str(REMINDERS_DB_PATH)) as conn:
            conn.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id))
            conn.commit()
    except Exception as e:
        logging.warning(f"Failed to update reminder #{reminder_id} status: {e}")


def check_and_claim_due_reminders(grace_period_minutes: int = 5) -> List[Tuple[int, str]]:
    """
    Atomically checks for pending reminders in SQLite whose target_time <= now.

    1. If target_time <= now and overdue by <= grace_period_minutes (or due now):
       Atomically transitions status from 'pending' to 'fired' and claims for immediate delivery.
    2. If target_time <= now and overdue by > grace_period_minutes (stale from an offline period hours/days ago):
       Atomically transitions status from 'pending' to 'expired' so the user is not flooded upon startup.

    Guarantees idempotence: only the transaction that successfully changes row count claims the reminder.
    """
    _init_reminders_db()
    now = datetime.now(KOLKATA_TZ)
    claimed: List[Tuple[int, str]] = []

    try:
        with sqlite3.connect(str(REMINDERS_DB_PATH), timeout=15.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, text, target_time FROM reminders WHERE status = 'pending' ORDER BY id ASC")
            rows = cursor.fetchall()
            if not rows:
                return []

            for rem_id, text, target_str in rows:
                target_dt = parse_stored_target_time(target_str)
                if not target_dt:
                    continue

                if target_dt <= now:
                    overdue_seconds = (now - target_dt).total_seconds()
                    if overdue_seconds > (grace_period_minutes * 60):
                        # Expire stale reminders from old offline periods without spamming
                        cursor.execute(
                            "UPDATE reminders SET status = 'expired' WHERE id = ? AND status = 'pending'",
                            (rem_id,)
                        )
                        logging.info(f"Marked stale reminder #{rem_id} ('{text}') as expired (overdue by {overdue_seconds/60:.1f}m).")
                    else:
                        # Atomically claim for immediate delivery
                        cursor.execute(
                            "UPDATE reminders SET status = 'fired' WHERE id = ? AND status = 'pending'",
                            (rem_id,)
                        )
                        if cursor.rowcount > 0:
                            claimed.append((rem_id, text))
            conn.commit()
    except Exception as e:
        logging.warning(f"Error checking due reminders: {e}")

    return claimed


_SCHEDULER_THREAD: Optional[threading.Thread] = None
_SCHEDULER_STOP_EVENT = threading.Event()
_REMINDER_DELIVERY_CALLBACK = None


def register_reminder_callback(callback: Optional[Callable[[int, str], None]]) -> None:
    """Register a callback to receive claimed reminders (used by tests or external observers)."""
    global _REMINDER_DELIVERY_CALLBACK
    _REMINDER_DELIVERY_CALLBACK = callback


def start_reminder_scheduler(interval: float = 1.0) -> None:
    """Start background reminder scheduler thread if not running (for test/standalone runs)."""
    global _SCHEDULER_THREAD
    if _SCHEDULER_THREAD is not None and _SCHEDULER_THREAD.is_alive():
        return
    _SCHEDULER_STOP_EVENT.clear()

    def _worker():
        while not _SCHEDULER_STOP_EVENT.wait(interval):
            try:
                claimed = check_and_claim_due_reminders()
                for rem_id, text in claimed:
                    # 1. UI / TTS / test callback immediately without delay
                    if _REMINDER_DELIVERY_CALLBACK:
                        try:
                            _REMINDER_DELIVERY_CALLBACK(rem_id, text)
                        except Exception as cb_e:
                            logging.warning(f"Reminder delivery callback failed: {cb_e}")

                    # 2. Desktop notification toast in non-blocking background thread
                    try:
                        threading.Thread(
                            target=_show_windows_toast_sync,
                            args=("NEXA Reminder", text),
                            daemon=True
                        ).start()
                    except Exception as toast_e:
                        logging.warning(f"Toast notification failed: {toast_e}")
            except Exception as loop_e:
                logging.warning(f"Scheduler worker error: {loop_e}")

    _SCHEDULER_THREAD = threading.Thread(target=_worker, daemon=True)
    _SCHEDULER_THREAD.start()


def stop_reminder_scheduler() -> None:
    """Stop the background reminder scheduler thread."""
    global _SCHEDULER_THREAD
    _SCHEDULER_STOP_EVENT.set()
    if _SCHEDULER_THREAD is not None and _SCHEDULER_THREAD.is_alive():
        _SCHEDULER_THREAD.join(timeout=1.0)
    _SCHEDULER_THREAD = None


def _show_windows_toast_sync(title: str, message: str) -> None:
    """
    Display a reliable native Windows notification on the user's desktop.
    Combines Action Center toast integration with a native topmost desktop notification banner.
    Safely encodes title and message to prevent any PowerShell or XML script injection.
    """
    # Base64 encode title and message as UTF-8 so they are delivered strictly as data
    b64_title = base64.b64encode((title or "").encode("utf-8")).decode("ascii")
    b64_msg = base64.b64encode((message or "").encode("utf-8")).decode("ascii")

    env = os.environ.copy()
    env["NEXA_TOAST_TITLE_B64"] = b64_title
    env["NEXA_TOAST_MSG_B64"] = b64_msg

    # Fixed static PowerShell script: no runtime string interpolation of user data
    ps_script = """
$ErrorActionPreference = 'Continue'

# 1. Decode pure string data from environment variables
$b64Title = $env:NEXA_TOAST_TITLE_B64
$b64Msg = $env:NEXA_TOAST_MSG_B64

$title = ""
if ($b64Title) {
    try {
        $title = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b64Title))
    } catch {
        $title = ""
    }
}

$message = ""
if ($b64Msg) {
    try {
        $message = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b64Msg))
    } catch {
        $message = ""
    }
}

# 2. Correct XML escaping for toast notification elements
$xmlTitle = if ($title) { [System.Security.SecurityElement]::Escape($title) } else { "" }
$xmlMessage = if ($message) { [System.Security.SecurityElement]::Escape($message) } else { "" }

# 3. Attempt Action Center Toast Notification using valid Windows AUMID
try {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
    $template = "<toast scenario=`"reminder`"><visual><binding template=`"ToastGeneric`"><text>$xmlTitle</text><text>$xmlMessage</text></binding></visual></toast>"
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml($template)
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("windows.immersivecontrolpanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel")
    $notifier.Show($toast)
} catch {
    Write-Warning "Action Center toast error: $_"
}

# 4. Display native desktop floating notification banner
try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $form = New-Object System.Windows.Forms.Form
    $form.Text = $title
    $form.Size = New-Object System.Drawing.Size(380, 105)
    $form.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
    $form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
    $form.TopMost = $true
    $form.ShowInTaskbar = $false
    $form.BackColor = [System.Drawing.Color]::FromArgb(30, 30, 30)

    $workingArea = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $form.Location = New-Object System.Drawing.Point(($workingArea.Right - 400), ($workingArea.Bottom - 125))

    # Accent bar
    $accent = New-Object System.Windows.Forms.Panel
    $accent.BackColor = [System.Drawing.Color]::FromArgb(0, 120, 215)
    $accent.Location = New-Object System.Drawing.Point(0, 0)
    $accent.Size = New-Object System.Drawing.Size(5, 105)
    $form.Controls.Add($accent)

    # Title label
    $titleLabel = New-Object System.Windows.Forms.Label
    $titleLabel.UseMnemonic = $false
    $titleLabel.Text = $title
    $titleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 11, [System.Drawing.FontStyle]::Bold)
    $titleLabel.ForeColor = [System.Drawing.Color]::White
    $titleLabel.Location = New-Object System.Drawing.Point(18, 12)
    $titleLabel.Size = New-Object System.Drawing.Size(340, 24)
    $form.Controls.Add($titleLabel)

    # Message label
    $msgLabel = New-Object System.Windows.Forms.Label
    $msgLabel.UseMnemonic = $false
    $msgLabel.Text = $message
    $msgLabel.Font = New-Object System.Drawing.Font("Segoe UI", 10)
    $msgLabel.ForeColor = [System.Drawing.Color]::FromArgb(220, 220, 220)
    $msgLabel.Location = New-Object System.Drawing.Point(18, 38)
    $msgLabel.Size = New-Object System.Drawing.Size(340, 55)
    $form.Controls.Add($msgLabel)

    # Click to dismiss
    $dismiss = { $form.Close() }
    $form.Add_Click($dismiss)
    $titleLabel.Add_Click($dismiss)
    $msgLabel.Add_Click($dismiss)

    # Auto close timer (5 seconds)
    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 5000
    $timer.Add_Tick({ $form.Close() })
    $timer.Start()

    [System.Media.SystemSounds]::Asterisk.Play()
    $form.ShowDialog() | Out-Null
} catch {
    Write-Error "Banner display error: $_"
    exit 1
}
"""
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            env=env,
            capture_output=True,
            text=True,
            timeout=10
        )
        if res.returncode != 0:
            logging.error(f"Failed to display Windows notification: returncode={res.returncode}, stderr={res.stderr.strip()}")
        else:
            logging.info("Windows reminder notification displayed successfully.")
    except Exception as e:
        logging.error(f"Exception displaying Windows notification: {e}")


async def _reminder_task(delay_secs: float, text: str, reminder_id: int) -> None:
    """Background async worker that awaits the timer and fires the native notification."""
    try:
        await asyncio.sleep(delay_secs)
        # Atomically mark as fired to prevent duplicate execution
        with sqlite3.connect(str(REMINDERS_DB_PATH), timeout=15.0) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE reminders SET status = 'fired' WHERE id = ? AND status = 'pending'", (reminder_id,))
            conn.commit()
            if cursor.rowcount > 0:
                logging.info(f"Reminder #{reminder_id} fired: '{text}'")
                if _REMINDER_DELIVERY_CALLBACK:
                    try:
                        _REMINDER_DELIVERY_CALLBACK(reminder_id, text)
                    except Exception as cb_e:
                        logging.warning(f"Reminder callback failed: {cb_e}")
                await asyncio.to_thread(_show_windows_toast_sync, "NEXA Reminder", text)
    except asyncio.CancelledError:
        # Keep status as 'pending' in SQLite so it can be resumed upon NEXA restart
        logging.debug(f"Reminder #{reminder_id} paused due to session shutdown.")
    except Exception as e:
        logging.error(f"Error executing reminder #{reminder_id}: {e}")
    finally:
        _ACTIVE_REMINDERS.pop(reminder_id, None)


def parse_stored_target_time(target_str: str) -> Optional[datetime]:
    """Parse stored target time string back into a timezone-aware datetime in Asia/Kolkata."""
    if not target_str or not isinstance(target_str, str):
        return None
    clean = target_str.strip()
    clean_no_tz = re.sub(
        r"\s+(?:Asia/Kolkata|IST|UTC\+05:30|\+05:30)$",
        "",
        clean,
        flags=re.I
    ).strip()
    for fmt in (
        "%Y-%m-%d %I:%M:%S %p",
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(clean_no_tz, fmt).replace(tzinfo=KOLKATA_TZ)
        except ValueError:
            pass
    try:
        norm = normalize_to_kolkata_rfc3339(clean)
        dt = datetime.fromisoformat(norm)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KOLKATA_TZ)
        return dt
    except Exception:
        pass
    return None


_RECOVERY_LOCK = asyncio.Lock()


async def recover_pending_reminders() -> int:
    """
    Recover and reschedule all reminders with status='pending' upon startup.
    Ensures non-blocking execution, prevents duplicates, and preserves Asia/Kolkata timezone.
    """
    async with _RECOVERY_LOCK:
        def _load_pending():
            _init_reminders_db()
            with sqlite3.connect(str(REMINDERS_DB_PATH), timeout=15.0) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, text, target_time FROM reminders WHERE status = 'pending'")
                return cursor.fetchall()

        try:
            pending_rows = await asyncio.to_thread(_load_pending)
        except Exception as e:
            logging.error(f"Failed to query pending reminders from SQLite: {e}")
            return 0

    if not pending_rows:
        return 0

    now = datetime.now(KOLKATA_TZ)
    rescheduled_count = 0

    for rem_id, text, target_str in pending_rows:
        if rem_id in _ACTIVE_REMINDERS and not _ACTIVE_REMINDERS[rem_id].done():
            continue

        target_dt = parse_stored_target_time(target_str)
        if not target_dt:
            logging.warning(f"Could not parse target time '{target_str}' for reminder #{rem_id}")
            continue

        remaining_secs = (target_dt - now).total_seconds()
        if remaining_secs > 0:
            logging.info(
                f"Rescheduling pending reminder #{rem_id} ('{text}') with {remaining_secs:.1f}s remaining (due at {target_str})."
            )
            task = asyncio.create_task(_reminder_task(remaining_secs, text, rem_id))
            _ACTIVE_REMINDERS[rem_id] = task
            rescheduled_count += 1
        else:
            logging.info(
                f"Pending reminder #{rem_id} ('{text}') expired while NEXA was offline (was due at {target_str}). Firing now."
            )
            task = asyncio.create_task(_reminder_task(0.0, text, rem_id))
            _ACTIVE_REMINDERS[rem_id] = task
            rescheduled_count += 1

    logging.info(f"Startup recovery completed: {rescheduled_count} pending reminder(s) active.")
    return rescheduled_count


def parse_reminder_timing(
    target_time: Optional[str] = None,
    delay_seconds: Optional[int] = None,
    delay_minutes: Optional[int] = None
) -> Tuple[Optional[float], Optional[datetime]]:
    """
    Parse relative delay or clock time into duration in seconds and target datetime in Asia/Kolkata.
    """
    now = datetime.now(KOLKATA_TZ)

    # 1. Direct delay parameter (seconds)
    if delay_seconds is not None and delay_seconds > 0:
        target_dt = now + timedelta(seconds=delay_seconds)
        return float(delay_seconds), target_dt

    # 2. Direct delay parameter (minutes)
    if delay_minutes is not None and delay_minutes > 0:
        secs = float(delay_minutes * 60)
        target_dt = now + timedelta(seconds=secs)
        return secs, target_dt

    if not target_time or not isinstance(target_time, str):
        return None, None

    clean_target = target_time.strip()

    # 3. Relative text phrases (e.g. 'in 10 minutes', '10 seconds', 'in 1 hour')
    rel_match = re.search(
        r"(?:in\s+)?(\d+)\s*(s(?:ec(?:ond)?s?)?|m(?:in(?:ute)?s?)?|h(?:(?:ou)?rs?)?)\b",
        clean_target,
        re.I
    )
    if rel_match:
        val = int(rel_match.group(1))
        unit = rel_match.group(2).lower()
        if unit.startswith("s"):
            secs = float(val)
        elif unit.startswith("h"):
            secs = float(val * 3600)
        else:
            secs = float(val * 60)
        target_dt = now + timedelta(seconds=secs)
        return secs, target_dt

    # 4. Check for 'tomorrow' / 'today' markers and strip leading prepositions
    is_tomorrow = bool(re.search(r"\btomorrow\b", clean_target, re.I))
    cleaned_time = re.sub(r"\b(tomorrow|today)(?:\s+at)?\b", "", clean_target, flags=re.I).strip()
    cleaned_time = re.sub(r"^(?:at|by)\s+", "", cleaned_time, flags=re.I).strip()

    # 5. Clock time format (e.g. '7:00 PM', '7 PM', '19:00', '07:30 AM')
    for fmt in ("%I:%M %p", "%I %p", "%I:%M%p", "%I%p", "%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(cleaned_time, fmt).time()
            target_dt = now.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)
            if is_tomorrow or target_dt <= now:
                target_dt += timedelta(days=1)
            secs = max(1.0, (target_dt - now).total_seconds())
            return secs, target_dt
        except ValueError:
            continue

    # 6. Full ISO / RFC3339 datetime
    norm_rfc = normalize_to_kolkata_rfc3339(clean_target)
    try:
        dt = datetime.fromisoformat(norm_rfc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KOLKATA_TZ)
        if dt <= now:
            dt += timedelta(days=1)
        secs = max(1.0, (dt - now).total_seconds())
        return secs, dt
    except Exception:
        pass

    return None, None


@function_tool()
async def set_reminder(
    context: RunContext,  # type: ignore
    reminder_text: str,
    target_time: Optional[str] = None,
    delay_seconds: Optional[int] = None,
    delay_minutes: Optional[int] = None
) -> str:
    """
    Set a local reminder or timer that alerts the user with a native Windows notification.
    Use this tool when the user asks to be reminded or alerted (e.g. 'remind me in 10 minutes to...', 'remind me at 7 PM to...', 'set a timer for 10 seconds').
    Do NOT use this tool for formal calendar meetings or appointments with other people; use Create_an_event_in_Google_Calendar instead.

    Args:
        reminder_text: What the user wants to be reminded about (e.g., 'drink water', 'call mom').
        target_time: Clock time or relative string in Asia/Kolkata timezone (e.g., '7:00 PM', '19:00', 'in 10 minutes').
        delay_seconds: Optional relative delay in seconds (e.g., 10 for 'in 10 seconds').
        delay_minutes: Optional relative delay in minutes (e.g., 10 for 'in 10 minutes').
    """
    try:
        delay_secs, target_dt = parse_reminder_timing(
            target_time=target_time,
            delay_seconds=delay_seconds,
            delay_minutes=delay_minutes
        )

        if delay_secs is None or target_dt is None:
            return f"Could not determine the reminder time from '{target_time}'. Please provide a valid time or duration."

        norm_text = _normalize_reminder_text_for_dedup(reminder_text)
        target_ts = target_dt.timestamp()
        now_mono = time.monotonic()

        # Check for duplicate execution within the deduplication window
        with _REMINDER_DEDUP_LOCK:
            cutoff = now_mono - _REMINDER_DEDUP_WINDOW_SECONDS
            _RECENT_REMINDER_EXECUTIONS[:] = [
                entry for entry in _RECENT_REMINDER_EXECUTIONS if entry["timestamp"] >= cutoff
            ]
            for entry in _RECENT_REMINDER_EXECUTIONS:
                text_match = (
                    norm_text == entry["normalized_text"]
                    or (norm_text and norm_text in entry["normalized_text"])
                    or (entry["normalized_text"] and entry["normalized_text"] in norm_text)
                )
                time_match = abs(target_ts - entry["target_ts"]) <= 5.0
                if text_match and time_match:
                    logging.info(
                        "Deduplicated reminder execution for '%s' (reusing reminder #%s)",
                        reminder_text,
                        entry["reminder_id"],
                    )
                    return entry["confirmation"]

        target_time_str = target_dt.strftime("%Y-%m-%d %I:%M:%S %p %Z")
        reminder_id = await asyncio.to_thread(_save_reminder, reminder_text, target_time_str)

        if not reminder_id:
            return "Failed to set reminder: database storage unavailable."

        task = asyncio.create_task(_reminder_task(delay_secs, reminder_text, reminder_id))
        _ACTIVE_REMINDERS[reminder_id] = task

        if delay_secs < 60:
            duration_str = f"in {int(delay_secs)} seconds"
        elif delay_secs < 3600:
            duration_str = f"in {int(delay_secs // 60)} minutes"
        else:
            duration_str = f"at {target_dt.strftime('%I:%M %p')}"

        time_display = target_dt.strftime("%I:%M %p")
        logging.info(f"Scheduled reminder #{reminder_id} for '{reminder_text}' {duration_str} ({target_time_str})")
        confirmation = f"Reminder set: '{reminder_text}' {duration_str} ({time_display} IST)."

        # Record in dedup registry
        with _REMINDER_DEDUP_LOCK:
            _RECENT_REMINDER_EXECUTIONS.append({
                "timestamp": now_mono,
                "normalized_text": norm_text,
                "target_ts": target_ts,
                "reminder_id": reminder_id,
                "confirmation": confirmation,
            })

        return confirmation
    except Exception as e:
        logging.error(f"Error setting reminder: {e}")
        return "I couldn't set that reminder right now."


@function_tool()
async def show_reminders(
    context: RunContext,  # type: ignore
) -> str:
    """
    Retrieve and list all pending reminders and timers scheduled for the user.
    Use this tool when the user asks to see, check, view, or show their pending reminders (e.g. 'show my pending reminders', 'what reminders do I have?', 'list my reminders', 'check my timers').
    """
    def _query_pending():
        _init_reminders_db()
        with sqlite3.connect(str(REMINDERS_DB_PATH), timeout=15.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, text, target_time FROM reminders WHERE status = 'pending' ORDER BY id ASC"
            )
            return cursor.fetchall()

    try:
        pending_rows = await asyncio.to_thread(_query_pending)
        if not pending_rows:
            return "You have no pending reminders."

        lines = ["You have the following pending reminder(s):"]
        for rem_id, text, target_str in pending_rows:
            target_dt = parse_stored_target_time(target_str)
            if target_dt:
                time_str = target_dt.strftime("%I:%M %p IST on %d %B %Y")
            else:
                time_str = target_str
            lines.append(f"- ID {rem_id}: '{text}' scheduled for {time_str}")

        return "\n".join(lines)
    except Exception as e:
        logging.error(f"Error querying pending reminders: {e}")
        return f"Failed to retrieve reminders: {type(e).__name__}"


@function_tool()
async def cancel_reminder(
    context: RunContext,  # type: ignore
    reminder_id: Optional[int] = None,
    reminder_text: Optional[str] = None
) -> str:
    """
    Cancel a specific pending reminder or timer.
    Use this tool when the user asks to cancel, delete, or remove a specific reminder (e.g. 'cancel my reminder to check my project', 'cancel reminder 5', 'delete the drink water timer').

    Args:
        reminder_id: The numeric ID of the reminder to cancel, if mentioned by the user.
        reminder_text: The subject, text, or keyword of the reminder to cancel (e.g. 'check my project', 'drink water').
    """
    target_id: Optional[int] = None
    if reminder_id is not None:
        try:
            target_id = int(str(reminder_id).strip())
        except (ValueError, TypeError):
            target_id = None

    now_mono = time.monotonic()
    with _REMINDER_DEDUP_LOCK:
        cutoff = now_mono - _REMINDER_DEDUP_WINDOW_SECONDS
        _RECENT_CANCELLATIONS[:] = [
            c for c in _RECENT_CANCELLATIONS if c["timestamp"] >= cutoff
        ]
        for c in _RECENT_CANCELLATIONS:
            if target_id is not None and c.get("reminder_id") == target_id:
                logging.info(
                    "Deduplicated cancellation for reminder #%s (recently cancelled)",
                    target_id,
                )
                return c["confirmation"]
            if reminder_text and c.get("reminder_text"):
                norm_c = _normalize_reminder_text_for_dedup(c["reminder_text"])
                norm_q = _normalize_reminder_text_for_dedup(reminder_text)
                if norm_q and (norm_q == norm_c or norm_q in norm_c or norm_c in norm_q):
                    logging.info(
                        "Deduplicated cancellation for '%s' (recently cancelled)",
                        reminder_text,
                    )
                    return c["confirmation"]

    def _find_and_cancel_in_db():
        _init_reminders_db()
        with sqlite3.connect(str(REMINDERS_DB_PATH), timeout=15.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, text, target_time FROM reminders WHERE status = 'pending' ORDER BY id DESC"
            )
            rows = cursor.fetchall()
            if not rows:
                return None, "You have no pending reminders to cancel."

            matched_id = None
            matched_text = None

            if target_id is not None:
                for r_id, r_text, _ in rows:
                    if r_id == target_id:
                        matched_id = r_id
                        matched_text = r_text
                        break
            elif reminder_text:
                norm_query = reminder_text.strip().lower()
                for prefix in ("to ", "my ", "the ", "reminder to ", "reminder for "):
                    if norm_query.startswith(prefix):
                        norm_query = norm_query[len(prefix):].strip()

                # 1. Exact match
                for r_id, r_text, _ in rows:
                    if norm_query == r_text.strip().lower():
                        matched_id = r_id
                        matched_text = r_text
                        break
                # 2. Substring match
                if matched_id is None:
                    for r_id, r_text, _ in rows:
                        clean_r_text = r_text.strip().lower()
                        if norm_query in clean_r_text or clean_r_text in norm_query:
                            matched_id = r_id
                            matched_text = r_text
                            break

            if matched_id is None:
                return None, f"Could not find a pending reminder matching '{reminder_text or reminder_id}'."

            cursor.execute("UPDATE reminders SET status = 'cancelled' WHERE id = ?", (matched_id,))
            conn.commit()
            return (matched_id, matched_text), None

    try:
        matched_info, err = await asyncio.to_thread(_find_and_cancel_in_db)
        if err or not matched_info:
            return err or "Failed to find matching reminder."

        match_id, match_text = matched_info

        # Stop active asyncio task if it exists
        task = _ACTIVE_REMINDERS.pop(match_id, None)
        if task and not task.done():
            task.cancel()
            logging.info(f"Cancelled active task for reminder #{match_id}")

        logging.info(f"Reminder #{match_id} ('{match_text}') marked as cancelled.")
        confirmation = f"Reminder #{match_id} ('{match_text}') has been cancelled."
        with _REMINDER_DEDUP_LOCK:
            _RECENT_CANCELLATIONS.append({
                "timestamp": now_mono,
                "reminder_id": match_id,
                "reminder_text": match_text,
                "confirmation": confirmation,
            })
        return confirmation
    except Exception as e:
        logging.error(f"Error cancelling reminder: {e}")
        return f"Failed to cancel reminder: {type(e).__name__}"


@function_tool()
async def cancel_all_reminders(
    context: RunContext,  # type: ignore
) -> str:
    """
    Cancel all pending reminders and timers.
    Use this tool when the user asks to cancel, clear, stop, or delete all of their reminders (e.g. 'cancel all my reminders', 'clear all reminders', 'stop all timers', 'delete all reminders').
    """
    def _cancel_all_in_db():
        _init_reminders_db()
        with sqlite3.connect(str(REMINDERS_DB_PATH), timeout=15.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, text FROM reminders WHERE status = 'pending'")
            rows = cursor.fetchall()
            if not rows:
                return []
            cursor.execute("UPDATE reminders SET status = 'cancelled' WHERE status = 'pending'")
            conn.commit()
            return rows

    try:
        cancelled_rows = await asyncio.to_thread(_cancel_all_in_db)
        if not cancelled_rows:
            return "You have no pending reminders to cancel."

        # Stop all active asyncio tasks
        for rem_id, _ in cancelled_rows:
            task = _ACTIVE_REMINDERS.pop(rem_id, None)
            if task and not task.done():
                task.cancel()

        count = len(cancelled_rows)
        logging.info(f"Cancelled all ({count}) pending reminders.")
        return f"Successfully cancelled all {count} pending reminder(s)."
    except Exception as e:
        logging.error(f"Error cancelling all reminders: {e}")
        return f"Failed to cancel all reminders: {type(e).__name__}"


@function_tool()
async def remember_fact(
    context: RunContext,  # type: ignore
    fact: str
) -> str:
    """
    Explicitly save or record a personal fact, preference, or detail about the user into persistent long-term memory.
    Use this tool when the user explicitly instructs you to remember, save, or store information (e.g., 'remember that...', 'remember this...', 'save this in your memory...').

    Args:
        fact: The specific fact, preference, or detail the user wants to remember.
    """
    try:
        from backend.memory import remember_fact as _remember_fact_impl, get_user_name
    except ImportError:
        from memory import remember_fact as _remember_fact_impl, get_user_name

    user_name = get_user_name()
    return await _remember_fact_impl(fact=fact, user_id=user_name)


@function_tool()
async def search_memories(
    context: RunContext,  # type: ignore
    query: str
) -> str:
    """
    Search or query the user's long-term memory for past facts, preferences, or details they previously shared.
    Use this tool when the user explicitly asks what you remember about them, about their preferences, or about a specific topic (e.g. 'what do you remember about me?', 'what do you remember about my preferences?', 'what did I tell you about my project?').

    Args:
        query: Search term, topic, or question to look up in memory (e.g., 'preferences', 'project', 'user information').
    """
    try:
        from backend.memory import search_memories as _search_memories_impl, get_user_name
    except ImportError:
        from memory import search_memories as _search_memories_impl, get_user_name

    user_name = get_user_name()
    clean_query = query.strip() if query and query.strip() else user_name
    # Map common generic phrases to user name for comprehensive retrieval
    if clean_query.lower() in ("me", "myself", "about me", "everything", "all"):
        clean_query = user_name

    results = await _search_memories_impl(query=clean_query, user_id=user_name, top_k=5)
    if not results:
        return f"I don't have any memories stored about '{query}' for {user_name}."

    lines = []
    for item in results:
        mem_text = item.get("memory") if isinstance(item, dict) else str(item)
        if mem_text and isinstance(mem_text, str) and mem_text.strip():
            lines.append(f"- {mem_text.strip()}")

    if not lines:
        return f"I don't have any memories stored about '{query}' for {user_name}."

    return "Here is what I remember:\n" + "\n".join(lines)


@function_tool()
async def forget_memory(
    context: RunContext,  # type: ignore
    query: str
) -> str:
    """
    Remove or forget a specific stored fact, preference, or detail from long-term memory.
    Use this tool when the user asks you to forget, delete, or remove a remembered piece of information (e.g., 'forget that my favorite programming language is Python', 'forget what you remember about my project', 'delete that memory').
    Do NOT delete all memories if the request is ambiguous or vague; ask the user to clarify.

    Args:
        query: What specific memory, fact, or topic to forget.
    """
    try:
        from backend.memory import (
            search_memories as _search_memories_impl,
            get_user_memories,
            delete_memory as _delete_memory_impl,
            get_user_name,
        )
    except ImportError:
        from memory import (
            search_memories as _search_memories_impl,
            get_user_memories,
            delete_memory as _delete_memory_impl,
            get_user_name,
        )

    user_name = get_user_name()
    raw_query = query.strip() if query else ""

    # Clean query prefixes
    clean_query = raw_query
    for prefix in (
        "forget that ",
        "forget about ",
        "forget what you remember about ",
        "forget what you know about ",
        "forget ",
        "delete that memory about ",
        "delete the memory about ",
        "delete memory about ",
        "delete that memory",
        "delete this memory",
        "delete ",
        "remove ",
    ):
        if clean_query.lower().startswith(prefix):
            clean_query = clean_query[len(prefix):].strip()
            break

    # 1. Ambiguous / Vague queries (e.g. "delete that memory", "forget everything", "forget all")
    ambiguous_terms = (
        "that", "this", "it", "that memory", "this memory", "the memory", "a memory",
        "my memory", "memory", "memories", "everything", "all", "all memories",
        "me", "myself", "something", "anything"
    )
    is_ambiguous = (
        not clean_query
        or clean_query.lower() in ambiguous_terms
    )

    if is_ambiguous:
        all_mems = await get_user_memories(user_name)
        if not all_mems:
            return "You don't have any memories stored to forget."
        options = "\n".join(f"- {m.get('memory', '').strip()}" for m in all_mems[:5] if m.get("memory"))
        return f"Which memory would you like me to forget? Here are your current memories:\n{options}"

    # 2. Lookup matching memories via semantic search and keyword match
    search_results = await _search_memories_impl(query=clean_query, user_id=user_name, top_k=5)
    all_user_mems = await get_user_memories(user_name)

    # Find candidates
    candidates = []
    seen_ids = set()

    for r in search_results:
        r_id = r.get("id")
        if r_id and r_id not in seen_ids:
            seen_ids.add(r_id)
            candidates.append(r)

    norm_q = clean_query.lower()
    for m in all_user_mems:
        m_id = m.get("id")
        m_text = m.get("memory", "").lower()
        if m_id and m_id not in seen_ids:
            words = [w for w in re.split(r"\W+", norm_q) if len(w) > 2]
            if any(w in m_text for w in words):
                seen_ids.add(m_id)
                candidates.append(m)

    if not candidates:
        return f"I couldn't find any memory matching '{query}' to forget."

    # Identify strong matches based on content keywords
    significant_words = [w for w in re.split(r"\W+", norm_q) if len(w) > 3 and w not in ("user", "that", "about", "your", "remember", "favorite")]
    strong_matches = []
    for c in candidates:
        c_text = c.get("memory", "").lower()
        if any(w in c_text for w in significant_words):
            strong_matches.append(c)

    if len(strong_matches) == 1:
        target_mem = strong_matches[0]
    elif len(candidates) == 1:
        target_mem = candidates[0]
    elif len(strong_matches) > 1:
        options = "\n".join(f"- {m.get('memory', '').strip()}" for m in strong_matches[:5])
        return f"Which memory would you like me to forget? I found multiple memories related to '{clean_query}':\n{options}"
    else:
        top_cand = candidates[0]
        score = top_cand.get("score", 0.0)
        if score >= 0.25:
            target_mem = top_cand
        else:
            options = "\n".join(f"- {m.get('memory', '').strip()}" for m in candidates[:3])
            return f"Which memory would you like me to forget? I found a few possible memories related to '{clean_query}':\n{options}"

    target_id = target_mem.get("id")
    target_text = target_mem.get("memory", "").strip()

    success = await _delete_memory_impl(target_id)
    if success:
        logging.info(f"Successfully deleted memory #{target_id}: '{target_text}' for user '{user_name}'")
        return f"I have forgotten: '{target_text}'"
    else:
        return f"Failed to delete the memory '{target_text}'."


# ---------------------------------------------------------
# Local File Content Reading & Inspection Subsystem
# ---------------------------------------------------------

SUPPORTED_FILE_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".json",
    ".yaml", ".yml", ".csv", ".log", ".html", ".css", ".sql"
}
MAX_FILE_SIZE_BYTES = 50 * 1024  # 50 KB threshold for large file warning

PERMITTED_FILE_ROOTS: Optional[List[Path]] = None

SENSITIVE_FILENAMES = {
    ".env", ".env.local", ".env.production", ".env.development", ".env.test",
    ".env.staging", ".env.vault", ".env.example", "id_rsa", "id_ecdsa",
    "id_ed25519", "id_dsa", "known_hosts", "authorized_keys", "master.key",
    "credentials.json", "client_secret.json", "token.json", "tokens.json",
    "reminders.db", "shadow", "passwd", "secrets.json", "secret.json",
    "settings.json", "web.config", "sam", "system", "security", "ntuser.dat"
}

SENSITIVE_DIR_NAMES = {
    ".ssh", ".gnupg", ".aws", ".azure", ".gcp", ".gcloud",
    ".git", ".svn", ".hg", ".gemini", ".antigravity",
    "system32", "syswow64", "windows", "security",
    "user data", "profiles"
}

SENSITIVE_FILE_PATTERNS = [
    re.compile(r"^\.?env(\..+)?$", re.IGNORECASE),
    re.compile(r".*\.env$", re.IGNORECASE),
    re.compile(r".*password.*", re.IGNORECASE),
    re.compile(r".*secret.*", re.IGNORECASE),
    re.compile(r".*credential.*", re.IGNORECASE),
    re.compile(r".*api[_-]?key.*", re.IGNORECASE),
    re.compile(r".*(?:auth|access|refresh)[_-]?token.*", re.IGNORECASE),
    re.compile(r".*private[_-]?key.*", re.IGNORECASE),
    re.compile(r".*id_(rsa|dsa|ecdsa|ed25519).*", re.IGNORECASE),
]


def get_permitted_file_roots() -> List[Path]:
    """Returns the list of canonical approved root directories for local file reading."""
    if PERMITTED_FILE_ROOTS is not None:
        return [r.resolve() for r in PERMITTED_FILE_ROOTS]

    roots = [ROOT_DIR.resolve()]
    try:
        home = Path.home().resolve()
        for folder_name in ("Documents", "Desktop", "Downloads"):
            candidate = (home / folder_name).resolve()
            if candidate.is_dir() and candidate not in roots:
                roots.append(candidate)
    except Exception:
        pass
    return roots


def is_within_permitted_roots(path: Path, permitted_roots: Optional[List[Path]] = None) -> bool:
    """Verifies that a canonical path is strictly contained within at least one permitted root."""
    if permitted_roots is None:
        permitted_roots = get_permitted_file_roots()
    try:
        canonical = path.resolve()
    except (OSError, RuntimeError, ValueError):
        return False

    for root in permitted_roots:
        try:
            canonical_root = root.resolve()
            if canonical == canonical_root or canonical.is_relative_to(canonical_root):
                return True
        except (OSError, ValueError):
            continue
    return False


def is_sensitive_path(path: Path) -> bool:
    """
    Case-insensitive security policy denying sensitive files, secrets,
    private keys, tokens, browser profiles, and configuration stores.
    """
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError, ValueError):
        return True

    # 1. Reject any path containing dot-directories or dot-files (.env, .ssh, .git, etc.)
    for part in resolved.parts:
        if part in ("/", "\\") or part.endswith(":\\"):
            continue
        if part.startswith("."):
            return True

    # 2. Case-insensitive basename and stem checks
    name_lower = resolved.name.lower()
    stem_lower = resolved.stem.lower()
    ext_lower = resolved.suffix.lower()

    if name_lower in SENSITIVE_FILENAMES or stem_lower in SENSITIVE_FILENAMES:
        return True

    DENIED_EXTENSIONS = {
        ".key", ".pem", ".pfx", ".p12", ".pkcs12", ".cer", ".crt", ".der",
        ".kdbx", ".env", ".db", ".sqlite", ".sqlite3"
    }
    if ext_lower in DENIED_EXTENSIONS:
        return True

    for pattern in SENSITIVE_FILE_PATTERNS:
        if pattern.search(name_lower) or pattern.search(stem_lower):
            return True

    # 3. Check for sensitive parent directories in the resolved path
    for part in resolved.parts:
        part_lower = part.lower()
        if part_lower in SENSITIVE_DIR_NAMES:
            return True

    return False



def _format_size_bytes(bytes_count: int) -> str:
    """Formats raw byte counts into human-readable strings."""
    if bytes_count < 1024:
        return f"{bytes_count} bytes"
    elif bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f} KB"
    else:
        return f"{bytes_count / (1024 * 1024):.2f} MB"


def _read_csv_preview_sync(path: Path, max_rows: int = 10) -> Tuple[List[List[str]], int, str]:
    """Reads the first max_rows of a CSV file safely without loading the full file."""
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
    rows: List[List[str]] = []
    used_enc = "utf-8"

    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                reader = csv.reader(f)
                for idx, row in enumerate(reader):
                    if idx >= max_rows:
                        break
                    truncated_row = [cell[:100] + ("..." if len(cell) > 100 else "") for cell in row[:15]]
                    if len(row) > 15:
                        truncated_row.append(f"... (+{len(row)-15} more columns)")
                    rows.append(truncated_row)
            used_enc = enc
            break
        except (UnicodeDecodeError, LookupError):
            rows.clear()
            continue

    if not rows:
        try:
            with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
                reader = csv.reader(f)
                for idx, row in enumerate(reader):
                    if idx >= max_rows:
                        break
                    truncated_row = [cell[:100] + ("..." if len(cell) > 100 else "") for cell in row[:15]]
                    if len(row) > 15:
                        truncated_row.append(f"... (+{len(row)-15} more columns)")
                    rows.append(truncated_row)
            used_enc = "utf-8 (lossy)"
        except Exception:
            pass

    return rows, path.stat().st_size, used_enc


def _read_text_lines_sync(
    path: Path,
    start_line: int = 1,
    max_lines: int = 100
) -> Tuple[List[str], int, str]:
    """Reads a range of lines from a text-based file using multi-encoding fallback."""
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
    content_lines: Optional[List[str]] = None
    used_enc = "utf-8"

    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as f:
                content_lines = f.readlines()
            used_enc = enc
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if content_lines is None:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content_lines = f.readlines()
        used_enc = "utf-8 (lossy)"

    total_lines = len(content_lines)
    s_idx = max(0, start_line - 1)
    e_idx = min(total_lines, s_idx + max(1, min(max_lines, 200)))
    subset = content_lines[s_idx:e_idx]
    return subset, total_lines, used_enc


async def _resolve_local_file_path(file_path: str) -> Tuple[Optional[Path], Optional[str]]:
    """
    Safely resolves a file path or filename to an existing local Path.
    Enforces containment within approved root directories and denies sensitive files.
    Returns (resolved_path, error_message_or_options).
    """
    clean_name = file_path.strip().strip("'\"")
    if not clean_name:
        return None, "Please specify a valid file name or path."

    permitted_roots = get_permitted_file_roots()

    def _validate_path_security(p: Path) -> Tuple[bool, Optional[str]]:
        try:
            canonical = p.resolve()
        except (OSError, RuntimeError, ValueError):
            return False, "Access denied: Invalid path syntax."

        if not is_within_permitted_roots(canonical, permitted_roots):
            return False, "Access denied: Path is outside permitted directories."

        if is_sensitive_path(canonical):
            return False, "Access denied: Reading restricted or sensitive files is not permitted."

        return True, None

    # Pre-check direct filename against sensitive rules (catches bare '.env', 'id_rsa', etc.)
    try:
        temp_direct = Path(clean_name)
        if is_sensitive_path(temp_direct):
            return None, "Access denied: Reading restricted or sensitive files is not permitted."
    except Exception:
        pass

    # 1. Direct path check (absolute or explicit relative)
    try:
        direct = Path(clean_name).expanduser()
    except (OSError, ValueError):
        return None, "Access denied: Invalid path syntax."

    if direct.is_absolute():
        try:
            canonical_direct = direct.resolve()
        except (OSError, ValueError):
            return None, "Access denied: Invalid path syntax."

        valid, err_msg = _validate_path_security(canonical_direct)
        if not valid:
            return None, err_msg

        if canonical_direct.is_dir():
            return None, f"'{canonical_direct.name}' is a directory, not a file. Please specify a file to read."
        if canonical_direct.is_file():
            return canonical_direct, None
    else:
        # Check relative to each permitted root
        for base in permitted_roots:
            try:
                candidate = (base / direct).resolve()
                if candidate.exists():
                    valid, err_msg = _validate_path_security(candidate)
                    if not valid:
                        return None, err_msg
                    if candidate.is_dir():
                        return None, f"'{candidate.name}' is a directory, not a file. Please specify a file to read."
                    if candidate.is_file():
                        return candidate, None
            except (OSError, ValueError):
                continue

    # 2. Search by filename across permitted roots
    target_name = Path(clean_name).name.lower()

    # Pre-check: if target_name is a known sensitive filename pattern, fail immediately
    temp_target = Path(target_name)
    if is_sensitive_path(temp_target):
        return None, "Access denied: Reading restricted or sensitive files is not permitted."

    candidates: List[Path] = []
    seen_paths = set()

    # Search using existing _find_files_sync in user document directories
    if _find_files_sync:
        try:
            found_matches = await asyncio.to_thread(_find_files_sync, target_name)
            for m in found_matches:
                try:
                    p = Path(m).resolve()
                    valid, _ = _validate_path_security(p)
                    if valid and p.is_file() and str(p).lower() not in seen_paths:
                        seen_paths.add(str(p).lower())
                        candidates.append(p)
                except (OSError, ValueError):
                    continue
        except Exception as e:
            logging.debug(f"_find_files_sync failed: {e}")

    # Search ROOT_DIR (Nexa workspace)
    try:
        for root, dirs, files in os.walk(ROOT_DIR):
            dirs[:] = [d for d in dirs if not d.startswith(('.', '__')) and d not in ('venv', '.venv', 'node_modules', 'dist', 'build')]
            for f in files:
                if f.startswith('.'):
                    continue
                if target_name in f.lower():
                    try:
                        p = (Path(root) / f).resolve()
                        valid, _ = _validate_path_security(p)
                        if valid and p.is_file() and str(p).lower() not in seen_paths:
                            seen_paths.add(str(p).lower())
                            candidates.append(p)
                    except (OSError, ValueError):
                        continue
    except Exception as e:
        logging.debug(f"Workspace walk search failed: {e}")

    # Prefer exact filename matches
    exact_matches = [p for p in candidates if p.name.lower() == target_name]
    if exact_matches:
        candidates = exact_matches

    if not candidates:
        return None, f"I could not find the file '{clean_name}'. Please verify the file name or provide the full path."

    if len(candidates) > 1:
        options = "\n".join(f"{i+1}. {p}" for i, p in enumerate(candidates[:5]))
        return None, f"I found multiple files matching '{clean_name}':\n{options}\nPlease specify the full path of the file you would like me to read."

    return candidates[0], None


@function_tool()
async def read_file_content(
    context: RunContext,  # type: ignore
    file_path: str,
    max_lines: int = 100,
    start_line: int = 1,
) -> str:
    """Reads and inspects the text content of a local file safely.

    Use this when the user explicitly wants to read, inspect, explain, summarize,
    or analyze a local file, code script, markdown document, CSV dataset, or log file.

    Supported formats: .txt, .md, .py, .js, .ts, .json, .yaml, .yml, .csv, .log, .html, .css, .sql

    Args:
        file_path: The name or path of the local file (e.g. 'train.py', 'dataset.csv', 'README.md', or full path).
        max_lines: Maximum number of lines/rows to read (default 100, max 200).
        start_line: 1-indexed starting line number (default 1).
    """
    resolved_path, err = await _resolve_local_file_path(file_path)
    if err:
        return err
    if not resolved_path:
        return f"Unable to resolve file path '{file_path}'."

    # Defense-in-depth: Re-verify containment and sensitivity on the resolved path
    permitted_roots = get_permitted_file_roots()
    if not is_within_permitted_roots(resolved_path, permitted_roots):
        return "Access denied: Path is outside permitted directories."
    if is_sensitive_path(resolved_path):
        return "Access denied: Reading restricted or sensitive files is not permitted."

    # Validate file type
    suffix = resolved_path.suffix.lower()
    if not suffix or suffix not in SUPPORTED_FILE_EXTENSIONS:
        ext_label = suffix if suffix else "(no extension)"
        allowed = ", ".join(sorted(SUPPORTED_FILE_EXTENSIONS))
        return f"Unsupported file type '{ext_label}'. NEXA currently supports: {allowed}."

    # Check file accessibility & size
    try:
        stat_info = resolved_path.stat()
        file_size = stat_info.st_size
    except PermissionError:
        return f"Permission denied: Unable to access '{resolved_path.name}'. The file is not accessible."
    except Exception as e:
        return f"Error accessing file '{resolved_path.name}': {e}"

    # Handle CSV files
    if suffix == ".csv":
        try:
            max_rows = min(max_lines, 20) if max_lines < 100 else 10
            rows, _, _ = await asyncio.to_thread(_read_csv_preview_sync, resolved_path, max_rows)
            if not rows:
                return f"The CSV file '{resolved_path.name}' is empty."
            header = rows[0]
            preview_lines = [
                f"File: {resolved_path.name} ({_format_size_bytes(file_size)})",
                f"Header ({len(header)} columns): {', '.join(header)}"
            ]
            if len(rows) > 1:
                for idx, r in enumerate(rows[1:], 1):
                    preview_lines.append(f"Row {idx}: {', '.join(r)}")
            return "\n".join(preview_lines)
        except PermissionError:
            return f"Permission denied: Unable to read '{resolved_path.name}'. The file is not accessible."
        except Exception as e:
            return f"Error reading CSV file '{resolved_path.name}': {e}"

    # Handle Large Non-CSV Files
    if file_size > MAX_FILE_SIZE_BYTES:
        if start_line == 1 and max_lines >= 100:
            return (
                f"The file '{resolved_path.name}' is {_format_size_bytes(file_size)}, which is quite large. "
                f"To avoid overwhelming the conversation, please let me know if you would like me to read the first 50 lines, "
                f"the latest lines, or a specific range."
            )
        try:
            slice_lines = min(max_lines, 50)
            lines, total_lines, _ = await asyncio.to_thread(_read_text_lines_sync, resolved_path, start_line, slice_lines)
            end_num = start_line + len(lines) - 1
            content = "".join(lines)
            return f"Showing lines {start_line} to {end_num} of '{resolved_path.name}' ({_format_size_bytes(file_size)} total):\n\n{content}"
        except PermissionError:
            return f"Permission denied: Unable to read '{resolved_path.name}'. The file is not accessible."
        except Exception as e:
            return f"Error reading file '{resolved_path.name}': {e}"

    # Handle Normal-Sized Text Files
    try:
        lines, total_lines, _ = await asyncio.to_thread(_read_text_lines_sync, resolved_path, start_line, max_lines)
        content = "".join(lines)
        if total_lines > len(lines):
            end_num = start_line + len(lines) - 1
            return (
                f"File: {resolved_path.name} ({_format_size_bytes(file_size)}, lines {start_line}-{end_num} of {total_lines}):\n\n"
                f"{content}\n\n[Showing {len(lines)} of {total_lines} lines. Ask if you need the next section.]"
            )
        return f"File: {resolved_path.name} ({_format_size_bytes(file_size)}, {total_lines} lines):\n\n{content}"
    except PermissionError:
        return f"Permission denied: Unable to read '{resolved_path.name}'. The file is not accessible."
    except Exception as e:
        return f"Error reading file '{resolved_path.name}': {e}"


@function_tool()
async def close_application(
    context: RunContext,  # type: ignore
    app_name: str,
    dry_run: bool = False
) -> str:
    """
    Safely close, exit, or terminate a running user desktop application.
    Use this when the user asks to close, exit, or quit an application (e.g. 'close Chrome', 'close Notepad', 'exit VS Code', 'quit Calculator').
    Do NOT use execute_desktop_action to close applications.

    Args:
        app_name: The name of the application to close (e.g. 'Chrome', 'Notepad', 'VS Code', 'Calculator', 'Spotify').
        dry_run: If True, simulates finding matching processes without terminating them. Defaults to False.
    """
    try:
        from backend.actions import close_application_action
    except ImportError:
        from actions import close_application_action  # type: ignore

    return await close_application_action(app_name=app_name, dry_run=dry_run)


@function_tool()
async def check_running_applications(
    context: RunContext,  # type: ignore
    app_name: Optional[str] = None,
    top_memory: bool = False
) -> str:
    """
    Inspect currently running applications and processes on the system (read-only).
    Use this tool when the user asks:
    - Whether a specific application is currently running (e.g., 'Is Chrome running?', 'Is Notepad open?').
    - How many processes or instances an application has (e.g., 'How many Chrome processes are running?').
    - What user applications are currently open/running (e.g., 'What apps are open?', 'What applications are running?').
    - Which applications are consuming the most memory/RAM (e.g., 'Which applications are using the most memory?').
    Do NOT use this tool to open or close applications.

    Args:
        app_name: Optional name of the specific application to check (e.g., 'Chrome', 'VS Code', 'Notepad').
        top_memory: If True, returns the highest memory-consuming user applications. Defaults to False.
    """
    try:
        from backend.actions import inspect_applications_action
    except ImportError:
        from actions import inspect_applications_action  # type: ignore

    return await inspect_applications_action(app_name=app_name, top_memory=top_memory)








