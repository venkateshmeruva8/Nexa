import os
import re
import json
import time
import asyncio
import inspect
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional
from livekit.agents import function_tool
from dotenv import load_dotenv

load_dotenv()

from .server import MCPServer
from .util import FunctionTool, MCPUtil

logger = logging.getLogger("nexa.mcp.agent_tools")

KOLKATA_TZ = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")

_RECENT_CALENDAR_DISPATCHES: List[Any] = []
_CALENDAR_DEBOUNCE_SECONDS = 10.0


def check_and_record_calendar_dispatch(calendar: str, start: str, end: str, summary: str) -> bool:
    """
    Prevents duplicate calendar event creation within a 10-second debounce window.
    Returns True if dispatch should proceed, False if duplicate detected.
    """
    global _RECENT_CALENDAR_DISPATCHES
    now = time.time()
    _RECENT_CALENDAR_DISPATCHES = [
        (c, s, e, sub, t) for c, s, e, sub, t in _RECENT_CALENDAR_DISPATCHES if now - t < 60.0
    ]
    norm_cal = (calendar or "primary").strip().lower()
    norm_start = (start or "").strip()
    norm_end = (end or "").strip()
    norm_sub = (summary or "").strip().lower()
    for c, s, e, sub, t in _RECENT_CALENDAR_DISPATCHES:
        if c == norm_cal and s == norm_start and e == norm_end and sub == norm_sub and (now - t) < _CALENDAR_DEBOUNCE_SECONDS:
            return False
    _RECENT_CALENDAR_DISPATCHES.append((norm_cal, norm_start, norm_end, norm_sub, now))
    return True


def resolve_calendar_id(val: Optional[str] = None) -> str:
    """
    Resolves the calendar identifier using the configuration priority:
    1. GOOGLE_CALENDAR_ID environment variable.
    2. GMAIL_USER environment variable.
    3. "primary" only if neither configuration value is available.
    Preserves an explicitly supplied calendar email address or custom identifier.
    """
    clean_val = str(val or "").strip()
    if not clean_val or clean_val.lower() == "primary":
        configured_id = (os.getenv("GOOGLE_CALENDAR_ID") or "").strip() or (os.getenv("GMAIL_USER") or "").strip()
        return configured_id or "primary"
    return clean_val


def normalize_to_kolkata_rfc3339(dt_str: str) -> str:
    """
    Interpret user/LLM-provided local datetimes as Asia/Kolkata (UTC+05:30) and
    format as explicit RFC3339 strings with +05:30 offset, e.g. '2026-10-05T11:00:00+05:30'.
    """
    if not dt_str or not isinstance(dt_str, str):
        return dt_str

    clean_str = dt_str.strip()
    # If already formatted with +05:30 or +0530 offset, standardize format
    if re.search(r"\+05:?30$", clean_str):
        if clean_str.endswith("+0530"):
            return clean_str[:-5] + "+05:30"
        return clean_str

    # Python 3.11 datetime.fromisoformat parses ISO8601 strings (including 'Z', offsets, spaces)
    try:
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is not None:
            # Timezone-aware (e.g. UTC Z from Gemini) -> convert to Kolkata timezone
            return dt.astimezone(KOLKATA_TZ).isoformat()
        else:
            # Naive wall-clock time -> attach Kolkata timezone
            return dt.replace(tzinfo=KOLKATA_TZ).isoformat()
    except Exception:
        pass

    # Clean prepositions, commas, ordinal suffixes for natural language formats
    clean_prep = re.sub(r"\b(on|at|from|to)\b", "", clean_str, flags=re.I)
    clean_prep = clean_prep.replace(",", " ")
    clean_prep = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", clean_prep, flags=re.I)
    clean_prep = re.sub(r"\s+", " ", clean_prep).strip()

    now = datetime.now(KOLKATA_TZ)
    # Support human-readable datetimes or natural language formats
    for fmt in (
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d %I %p",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d %B %Y %I:%M %p",
        "%d %B %Y %I %p",
        "%d %B %Y %H:%M",
        "%B %d %Y %I:%M %p",
        "%B %d %Y %I %p",
        "%B %d %Y %H:%M",
        "%d %b %Y %I:%M %p",
        "%d %b %Y %I %p",
        "%d %b %Y %H:%M",
        "%b %d %Y %I:%M %p",
        "%b %d %Y %I %p",
        "%b %d %Y %H:%M",
        "%d %B %I:%M %p",
        "%d %B %I %p",
        "%d %B %H:%M",
        "%B %d %I:%M %p",
        "%B %d %I %p",
        "%B %d %H:%M",
        "%d %b %I:%M %p",
        "%d %b %I %p",
        "%d %b %H:%M",
        "%b %d %I:%M %p",
        "%b %d %I %p",
        "%b %d %H:%M",
        "%I:%M %p",
        "%I %p",
        "%H:%M",
    ):
        try:
            dt = datetime.strptime(clean_prep, fmt)
            if dt.year == 1900:
                dt = dt.replace(year=now.year)
            if dt.month == 1 and dt.day == 1 and "%m" not in fmt and "%b" not in fmt and "%B" not in fmt:
                dt = dt.replace(month=now.month, day=now.day)
            return dt.replace(tzinfo=KOLKATA_TZ).isoformat()
        except ValueError:
            continue

    return clean_str


TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


class MCPToolsIntegration:
    """Bridges MCP servers and their tools into LiveKit function tools."""

    @staticmethod
    def _create_decorated_tool(tool: FunctionTool) -> Any:
        schema_props = tool.params_json_schema.get("properties", {})
        schema_required = set(tool.params_json_schema.get("required", []))

        is_calendar_tool = any(
            term in tool.name.lower() for term in ("calendar", "event", "schedule")
        )
        is_email_tool = any(
            term in tool.name.lower() for term in ("email", "mail", "send_an_email")
        )

        params = []
        annotations: Dict[str, Any] = {}
        param_name_mapping: Dict[str, str] = {}  # safe_name -> original_name
        seen_keys: set = set()

        for p_name, p_details in schema_props.items():
            # Sanitize parameter name to valid Python identifier
            safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", p_name)
            if safe_name.isidentifier() and not safe_name.startswith("_"):
                param_key = safe_name
            else:
                param_key = f"arg_{safe_name}"

            seen_keys.add(param_key.lower())
            seen_keys.add(p_name.lower())
            param_name_mapping[param_key] = p_name

            json_type = p_details.get("type", "string") if isinstance(p_details, dict) else "string"
            py_type = TYPE_MAP.get(json_type, Any)
            annotations[param_key] = py_type

            is_required = p_name in schema_required
            default = inspect.Parameter.empty if is_required else (
                p_details.get("default", None) if isinstance(p_details, dict) else None
            )

            # Default Calendar to "primary" if not explicitly defaulted
            if is_calendar_tool and p_name.lower() == "calendar" and (default is None or default is inspect.Parameter.empty):
                default = "primary"
            # Default From_Email to GMAIL_USER if not explicitly defaulted
            if is_email_tool and p_name.lower() in ("from_email", "from") and (default is None or default is inspect.Parameter.empty):
                default = os.getenv("GMAIL_USER", "")

            params.append(
                inspect.Parameter(
                    name=param_key,
                    kind=inspect.Parameter.KEYWORD_ONLY,
                    annotation=py_type,
                    default=default,
                )
            )

        # Augment Calendar tools with Summary and Description if not in schema_props
        if is_calendar_tool:
            if "summary" not in seen_keys:
                params.append(
                    inspect.Parameter(
                        name="Summary",
                        kind=inspect.Parameter.KEYWORD_ONLY,
                        annotation=Optional[str],
                        default=None,
                    )
                )
                annotations["Summary"] = Optional[str]
                param_name_mapping["Summary"] = "Summary"
                seen_keys.add("summary")
            if "description" not in seen_keys:
                params.append(
                    inspect.Parameter(
                        name="Description",
                        kind=inspect.Parameter.KEYWORD_ONLY,
                        annotation=Optional[str],
                        default=None,
                    )
                )
                annotations["Description"] = Optional[str]
                param_name_mapping["Description"] = "Description"
                seen_keys.add("description")

        # Augment Email tools with Message and Cc_Email if not in schema_props
        if is_email_tool:
            if "message" not in seen_keys and "body" not in seen_keys:
                params.append(
                    inspect.Parameter(
                        name="Message",
                        kind=inspect.Parameter.KEYWORD_ONLY,
                        annotation=Optional[str],
                        default=None,
                    )
                )
                annotations["Message"] = Optional[str]
                param_name_mapping["Message"] = "Message"
                seen_keys.add("message")
            if "cc_email" not in seen_keys and "cc" not in seen_keys:
                params.append(
                    inspect.Parameter(
                        name="Cc_Email",
                        kind=inspect.Parameter.KEYWORD_ONLY,
                        annotation=Optional[str],
                        default=None,
                    )
                )
                annotations["Cc_Email"] = Optional[str]
                param_name_mapping["Cc_Email"] = "Cc_Email"
                seen_keys.add("cc_email")

        # Define dynamic implementation callable
        async def tool_impl(**kwargs) -> str:
            # Map Python argument names back to original schema parameter names
            mapped_args = {}
            for k, v in kwargs.items():
                if v is not None:
                    orig_key = param_name_mapping.get(k, k)
                    mapped_args[orig_key] = v

            # Normalize Google Calendar / scheduling parameters for Asia/Kolkata (UTC+05:30)
            cal_detected = is_calendar_tool or any(
                term in tool.name.lower() for term in ("calendar", "event", "schedule")
            ) or any(k.lower() in ("start", "end") for k in mapped_args)

            if cal_detected:
                # 1. Normalize Start and End
                for k in list(mapped_args.keys()):
                    if k.lower() in ("start", "end") and isinstance(mapped_args[k], str):
                        mapped_args[k] = normalize_to_kolkata_rfc3339(mapped_args[k])

                # 2. Canonicalize Calendar ID: resolve "primary", empty, or omitted to GOOGLE_CALENDAR_ID -> GMAIL_USER -> "primary"
                # Preserve explicitly supplied calendar email address
                cal_key = next((k for k in mapped_args if k.lower() == "calendar"), None)
                if cal_key:
                    mapped_args[cal_key] = resolve_calendar_id(mapped_args[cal_key])
                elif any(p.lower() == "calendar" for p in schema_props):
                    orig_cal = next(p for p in schema_props if p.lower() == "calendar")
                    mapped_args[orig_cal] = resolve_calendar_id(None)
                else:
                    mapped_args["Calendar"] = resolve_calendar_id(None)

                # 3. Canonicalize Summary
                sum_key = next((k for k in mapped_args if k.lower() in ("summary", "title")), None)
                if sum_key and mapped_args[sum_key]:
                    mapped_args["Summary"] = str(mapped_args[sum_key]).strip()

                # 4. Standardize timezone
                if "timeZone" not in mapped_args and "timezone" not in mapped_args:
                    mapped_args["timeZone"] = "Asia/Kolkata"

                # 5. Prevent duplicate calendar creation within 10-second debounce window
                cal_id = mapped_args.get("Calendar") or (mapped_args.get(cal_key) if cal_key else None) or resolve_calendar_id(None)
                start_val = mapped_args.get("Start") or ""
                end_val = mapped_args.get("End") or ""
                sub_val = mapped_args.get("Summary") or "Event"
                if not check_and_record_calendar_dispatch(cal_id, start_val, end_val, sub_val):
                    logger.warning(f"Duplicate calendar event creation blocked: '{sub_val}' from {start_val} to {end_val}")
                    return f"Notice: Duplicate calendar event creation prevented. An event '{sub_val}' at {start_val} was already scheduled moments ago."

            # Intercept dynamic MCP email tools to enforce fail-closed security and prevent unconfirmed dispatch
            email_detected = is_email_tool or any(
                term in tool.name.lower() for term in ("email", "mail", "send_an_email")
            )
            if email_detected:
                to_addr = str(
                    mapped_args.get("To_Email") or mapped_args.get("to_email") or
                    mapped_args.get("to") or mapped_args.get("recipient") or ""
                ).strip()
                sub = str(
                    mapped_args.get("Subject") or mapped_args.get("subject") or "NEXA Message"
                ).strip()
                body = str(
                    mapped_args.get("Message") or mapped_args.get("message") or
                    mapped_args.get("body") or mapped_args.get("content") or ""
                ).strip()
                cc_addr = str(
                    mapped_args.get("Cc_Email") or mapped_args.get("cc_email") or
                    mapped_args.get("cc") or ""
                ).strip() or None

                try:
                    from backend.tools import send_email
                except ImportError:
                    from tools import send_email  # type: ignore

                logger.info(f"Intercepting dynamic MCP email tool '{tool.name}' to enforce fail-closed staging.")
                return await send_email(context=None, to_email=to_addr, subject=sub, message=body, cc_email=cc_addr)

            logger.info(f"Invoking MCP tool '{tool.name}' with args: {mapped_args}")
            try:
                input_json = json.dumps(mapped_args, default=str)
                result_str = await tool.on_invoke_tool(None, input_json)

                if not result_str or not str(result_str).strip():
                    if cal_detected:
                        return "Google Calendar service returned an empty response. Event creation could not be verified."
                    return f"Tool '{tool.name}' executed but returned an empty response."

                clean_res = str(result_str).strip()
                lower_res = clean_res.lower()

                # Requirement 5: HTTP 202 Accepted must NOT automatically be treated as proof of creation
                is_202_accepted = (
                    "workflow was started" in lower_res or
                    "accepted" in lower_res or
                    ("202" in lower_res and "accepted" in lower_res)
                )
                if is_202_accepted and not any(k in lower_res for k in ("htmllink", "id", "summary")):
                    if cal_detected:
                        return (
                            "Your calendar event request has been accepted by the scheduling service. "
                            "Please check your Google Calendar to confirm the event was created."
                        )
                    return f"Request was accepted by the workflow (HTTP 202 Accepted) for '{tool.name}', but completion has not yet been confirmed."

                if cal_detected:
                    try:
                        parsed_res = json.loads(clean_res)
                        ev = parsed_res[0] if isinstance(parsed_res, list) and len(parsed_res) > 0 and isinstance(parsed_res[0], dict) else (parsed_res if isinstance(parsed_res, dict) else None)
                        if ev:
                            # Check for error fields in payload
                            if "error" in ev or ("status" in ev and str(ev.get("status")).lower() == "error"):
                                err_msg = ev.get("error") or ev.get("message") or clean_res
                                return f"Google Calendar event creation failed: {err_msg}"

                            if "htmlLink" in ev or "id" in ev or "summary" in ev:
                                summary = ev.get("summary") or mapped_args.get("Summary") or "Event"
                                start_info = ev.get("start", {}).get("dateTime") or mapped_args.get("Start", "")
                                end_info = ev.get("end", {}).get("dateTime") or mapped_args.get("End", "")
                                link = ev.get("htmlLink", "")
                                msg = f"Event '{summary}' successfully created in Google Calendar from {start_info} to {end_info}."
                                if link:
                                    msg += f" Event link: {link}"
                                return msg
                    except Exception:
                        pass

                    # Direct error text returned by MCP tool
                    if "error" in lower_res or "failed" in lower_res or "invalid" in lower_res:
                        return f"Google Calendar event creation failed: {clean_res}"

                return clean_res

            except Exception as e:
                logger.error(f"Error invoking MCP tool '{tool.name}': {e}")
                err_str = str(e)
                if isinstance(e, (asyncio.TimeoutError, TimeoutError)) or "timeout" in err_str.lower() or "timed out" in err_str.lower():
                    if cal_detected:
                        return f"Google Calendar event creation timed out while waiting for the MCP server: {type(e).__name__}"
                    return f"MCP tool '{tool.name}' timed out: {type(e).__name__}"
                if isinstance(e, (ConnectionError, ConnectionRefusedError, ConnectionResetError)) or "not connected" in err_str.lower() or "unreachable" in err_str.lower():
                    if cal_detected:
                        return f"Google Calendar event creation failed because the calendar service is unreachable: {type(e).__name__} - {err_str}"
                    return f"Error executing MCP tool '{tool.name}': {type(e).__name__} - {err_str}"
                if cal_detected:
                    return f"Google Calendar event creation failed: {type(e).__name__} - {err_str}"
                return f"Error executing MCP tool '{tool.name}': {type(e).__name__} - {err_str}"

        # Sanitize tool name to valid Python function name
        safe_tool_name = re.sub(r"[^a-zA-Z0-9_]", "_", tool.name)
        tool_impl.__signature__ = inspect.Signature(parameters=params)
        tool_impl.__name__ = safe_tool_name
        tool_impl.__doc__ = tool.description or f"MCP tool: {tool.name}"
        tool_impl.__annotations__ = {"return": str, **annotations}

        return function_tool()(tool_impl)

    @staticmethod
    async def prepare_dynamic_tools(
        mcp_servers: List[MCPServer],
        auto_connect: bool = True,
        connect_timeout: float = 5.0,
    ) -> List[Any]:
        """
        Connects to MCP servers, discovers their tools, and wraps them as LiveKit function tools.
        Fails safely without raising exceptions if any server is unreachable.
        """
        prepared_tools: List[Any] = []

        for server in mcp_servers:
            if auto_connect and not getattr(server, "connected", False):
                try:
                    logger.info(f"Connecting to MCP server: {server.name}")
                    await server.connect(timeout=connect_timeout)
                except Exception as e:
                    logger.warning(f"Could not connect to MCP server {server.name}: {e}")
                    continue

            try:
                mcp_tools = await MCPUtil.get_function_tools(server)
                logger.info(f"Discovered {len(mcp_tools)} tools from {server.name}")
            except Exception as e:
                logger.warning(f"Failed to fetch tools from {server.name}: {e}")
                continue

            for tool_instance in mcp_tools:
                try:
                    decorated = MCPToolsIntegration._create_decorated_tool(tool_instance)
                    prepared_tools.append(decorated)
                    logger.debug(f"Prepared tool '{tool_instance.name}'")
                except Exception as e:
                    logger.warning(f"Failed to decorate tool '{tool_instance.name}': {e}")

        return prepared_tools
