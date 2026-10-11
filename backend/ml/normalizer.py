import re
from typing import Any

# Spoken colloquialisms and common speech-to-text variations
SPOKEN_REPLACEMENTS = {
    "wi-fi": "wifi",
    "wi fi": "wifi",
    "blu tooth": "bluetooth",
    "blue tooth": "bluetooth",
    "vs code": "visual studio code",
    "google chrome": "chrome",
    "web cam": "webcam",
    "screen sharing": "screen share",
    "shut down": "shutdown",
    "power off": "shutdown",
    "power down": "shutdown",
    "log off": "shutdown",
    "re boot": "reboot",
    "turn off laptop": "shutdown laptop",
    "turn off computer": "shutdown computer",
    "turn off the computer": "shutdown the computer",
    "turn off the laptop": "shutdown the laptop",
    "turn off my machine": "shutdown my machine",
    "turn off the machine": "shutdown the machine",
    "turn off pc": "shutdown pc",
    "turn off my pc": "shutdown my pc",
    "audio input": "microphone",
    "sound input": "microphone",
    "enable sound output": "unmute sound",
    "enable audio output": "unmute sound",
    "enable sound": "unmute sound",
    "enable audio": "unmute sound",
    "unmute sound output": "unmute sound",
    "unmute audio output": "unmute audio",
    "much obliged": "thank you",
}


def strip_carrier_prefixes(text: str) -> str:
    """
    Strips leading wake words (e.g. 'nexa', 'hey nexa') and polite carrier phrases
    (e.g. 'could you please', 'would you mind') when followed by actionable commands,
    while preserving standalone greetings, thanks, farewells, or assistant address.
    """
    cleaned = text.strip()
    if not cleaned:
        return ""

    lower = cleaned.lower()
    # Preserve standalone social tokens or direct inquiries
    if lower in ("nexa", "hey nexa", "hi nexa", "hello nexa", "bye nexa", "thanks nexa", "please", "kindly",
                  "hello", "hi", "hey", "hey there", "hello there", "hi there"):
        return cleaned

    # Strip leading assistant wake-word addresses
    subbed_wake = re.sub(r"^(?:(?:hey|hi|hello|ok)?\s*nexa\b\s*[,:]?\s*)+", "", cleaned, flags=re.IGNORECASE).strip()
    if subbed_wake:
        cleaned = subbed_wake

    # Strip leading casual callouts like "hey," when followed by actionable command words
    cleaned = re.sub(
        r"^(?:(?:hey|hi|hello|ok)\s*[,:]?\s*)(?=(?:turn|open|close|mute|unmute|set|what|tell|schedule|create|remind|search|dim|brighten|share|look|find|increase|decrease|lower|raise|boost)\b)",
        "",
        cleaned,
        flags=re.IGNORECASE
    ).strip()

    # Strip leading polite carrier framing phrases
    polite_pattern = r"^(?:(?:can\s+you\s+please|could\s+you\s+please|would\s+you\s+please|would\s+you\s+mind|can\s+you|could\s+you|would\s+you|please|kindly)\s+)+"
    subbed_polite = re.sub(polite_pattern, "", cleaned, flags=re.IGNORECASE).strip()
    if subbed_polite:
        cleaned = subbed_polite

    return cleaned


def normalize_text(text: Any) -> str:
    """
    Deterministically normalizes user speech or text input for intent classification.
    
    1. Converts text to lowercase and strips outer whitespace.
    2. Safely strips leading carrier phrases (wake words, polite prefixes) when followed by commands.
    3. Maps common spoken variations to standard command words.
    4. Safely removes non-alphanumeric punctuation while preserving words and numbers.
    5. Collapses multiple whitespace characters into single spaces.
    """
    if not text or not isinstance(text, str):
        return ""

    cleaned = text.lower().strip()
    if not cleaned:
        return ""

    cleaned = strip_carrier_prefixes(cleaned)

    for variant, target in SPOKEN_REPLACEMENTS.items():
        cleaned = cleaned.replace(variant, target)

    # Safely remove punctuation symbols, preserving alphanumeric characters and spaces
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)

    # Normalize multiple whitespace characters
    cleaned = " ".join(cleaned.split())

    return cleaned
