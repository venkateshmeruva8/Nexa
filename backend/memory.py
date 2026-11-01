import os
import sys
import asyncio
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path
from dotenv import load_dotenv

# Load environment configuration
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")
load_dotenv()
os.environ.setdefault("MEM0_TELEMETRY", "false")

# Singleton client reference
_ASYNC_CLIENT: Optional[Any] = None
_CLIENT_INITIALIZED: bool = False
logger = logging.getLogger("nexa.memory")
_CLIENT_LOCKS: dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}


def _get_client_lock() -> asyncio.Lock:
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.Lock()

    if current_loop not in _CLIENT_LOCKS:
        _CLIENT_LOCKS[current_loop] = asyncio.Lock()
    return _CLIENT_LOCKS[current_loop]


def get_user_name() -> str:
    """Return the configured user name or fallback to 'User'."""
    return os.getenv("USER_NAME", "User").strip() or "User"


def get_mem0_client() -> Optional[Any]:
    """
    Safely initialize and return the AsyncMemoryClient.
    Returns None if MEM0_API_KEY is missing or mem0 package is unavailable.
    Never exposes API keys or credentials in logs.
    """
    global _ASYNC_CLIENT, _CLIENT_INITIALIZED

    if _CLIENT_INITIALIZED:
        return _ASYNC_CLIENT

    api_key = os.getenv("MEM0_API_KEY")
    if not api_key or not api_key.strip():
        logger.info("Mem0 memory is disabled: MEM0_API_KEY is not configured.")
        _CLIENT_INITIALIZED = True
        _ASYNC_CLIENT = None
        return None

    try:
        from mem0 import AsyncMemoryClient
        _ASYNC_CLIENT = AsyncMemoryClient(api_key=api_key.strip())
        logger.info("Mem0 AsyncMemoryClient initialized successfully.")
    except Exception as e:
        logger.warning(f"Failed to initialize Mem0 client: {type(e).__name__}")
        _ASYNC_CLIENT = None

    _CLIENT_INITIALIZED = True
    return _ASYNC_CLIENT


async def get_mem0_client_async() -> Optional[Any]:
    """
    Asynchronously get or initialize the AsyncMemoryClient.
    Runs the synchronous client initialization (including Mem0's initial API ping)
    in a worker thread using asyncio.to_thread to prevent blocking the active RTC event loop.
    """
    global _ASYNC_CLIENT, _CLIENT_INITIALIZED

    if _CLIENT_INITIALIZED:
        return _ASYNC_CLIENT

    async with _get_client_lock():
        if _CLIENT_INITIALIZED:
            return _ASYNC_CLIENT
        return await asyncio.to_thread(get_mem0_client)


async def get_user_memories(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieve stored memories for a user at session start.
    Adapts to mem0 2.2.1 filter requirements.
    Fails safely without raising exceptions or leaking credentials.
    """
    client = await get_mem0_client_async()
    if client is None:
        return []

    target_user = user_id or get_user_name()
    try:
        # In mem0 >= 2.0, user_id must be passed inside filters
        response = await client.get_all(filters={"user_id": target_user})
        if isinstance(response, dict):
            results = response.get("results", [])
        elif isinstance(response, list):
            results = response
        else:
            results = []

        logger.info(f"Retrieved {len(results)} memories for user '{target_user}'.")
        return results
    except Exception as e:
        logger.warning(f"Failed to retrieve memories for user '{target_user}': {type(e).__name__}")
        return []


def format_memories(memories: List[Dict[str, Any]], user_name: Optional[str] = None) -> str:
    """
    Format a list of memory dicts into a concise context block for LLM prompts.
    """
    if not memories:
        return ""

    target_user = user_name or get_user_name()
    lines = []
    for item in memories:
        mem_text = item.get("memory") if isinstance(item, dict) else None
        if mem_text and isinstance(mem_text, str) and mem_text.strip():
            lines.append(f"- {mem_text.strip()}")

    if not lines:
        return ""

    return f"Known context about {target_user}:\n" + "\n".join(lines)


async def save_session_context(
    chat_ctx: Any,
    user_id: Optional[str] = None,
    memory_context_str: Optional[str] = None
) -> bool:
    """
    Extract conversation turns from ChatContext and save them to Mem0 on session shutdown.
    Filters out system instructions and initial memory context to avoid recursive memorization.
    """
    client = await get_mem0_client_async()
    if client is None:
        return False

    target_user = user_id or get_user_name()
    items = getattr(chat_ctx, "items", [])
    if not items:
        return False

    messages_formatted: List[Dict[str, str]] = []
    for item in items:
        content_val = getattr(item, "content", "")
        if isinstance(content_val, list):
            content_str = "".join(str(part) for part in content_val)
        else:
            content_str = str(content_val)

        content_str = content_str.strip()
        if not content_str:
            continue

        # Prevent recursive memorization of the loaded memory prompt
        if memory_context_str and memory_context_str in content_str:
            continue

        role = getattr(item, "role", None)
        if role in ["user", "assistant"]:
            messages_formatted.append({
                "role": role,
                "content": content_str
            })

    if not messages_formatted:
        logger.debug("No dialogue turns to persist to memory.")
        return False

    try:
        await client.add(messages_formatted, user_id=target_user)
        logger.info(f"Persisted {len(messages_formatted)} dialogue turns to Mem0 for '{target_user}'.")
        return True
    except Exception as e:
        logger.warning(f"Failed to persist dialogue to Mem0: {type(e).__name__}")
        return False


async def remember_fact(fact: str, user_id: Optional[str] = None) -> str:
    """
    Explicitly store a fact or preference for a user.
    """
    if not fact or not fact.strip():
        return "No information provided to remember."

    client = await get_mem0_client_async()
    if client is None:
        return "Memory storage is currently disabled or unconfigured."

    target_user = user_id or get_user_name()
    clean_fact = fact.strip()

    try:
        await client.add(clean_fact, user_id=target_user)
        logger.info(f"Explicitly recorded fact for '{target_user}'.")
        return f"I have remembered: {clean_fact}"
    except Exception as e:
        logger.warning(f"Failed to record fact: {type(e).__name__}")
        return "Failed to save information to memory."


async def search_memories(
    query: str,
    user_id: Optional[str] = None,
    top_k: int = 5
) -> List[Dict[str, Any]]:
    """
    Search stored memories for relevant information.
    """
    if not query or not query.strip():
        return []

    client = await get_mem0_client_async()
    if client is None:
        return []

    target_user = user_id or get_user_name()
    try:
        response = await client.search(
            query=query.strip(),
            filters={"user_id": target_user},
            top_k=top_k
        )
        if isinstance(response, dict):
            return response.get("results", [])
        elif isinstance(response, list):
            return response
        return []
    except Exception as e:
        logger.warning(f"Failed to search memories: {type(e).__name__}")
        return []


async def delete_memory(memory_id: str) -> bool:
    """
    Delete a specific stored memory by its unique Mem0 memory ID.
    """
    if not memory_id or not memory_id.strip():
        return False

    client = await get_mem0_client_async()
    if client is None:
        return False

    try:
        await client.delete(memory_id=memory_id.strip())
        logger.info(f"Deleted memory '{memory_id}' successfully.")
        return True
    except Exception as e:
        logger.warning(f"Failed to delete memory '{memory_id}': {type(e).__name__}")
        return False

