"""NEXA Unified Voice & Multilingual Processing Engine.

Provides real-time speech-to-text, voice activity detection, multilingual
language detection, command translation to English, response translation,
and speech synthesis.

Supported languages:
1. English ("en")
2. Telugu ("te")
3. Kannada ("kn")
4. Hindi ("hi")
5. Tamil ("ta")
6. Malayalam ("ml")
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv

# Ensure environment variables are loaded
BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
load_dotenv(ROOT_DIR / ".env")
load_dotenv()

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = {
    "en": "English",
    "te": "Telugu",
    "kn": "Kannada",
    "hi": "Hindi",
    "ta": "Tamil",
    "ml": "Malayalam",
}

# Cache for Gemini and speech recognition models
_GENAI_CONFIGURED = False
_GEMINI_MODEL: Any = None
_SPEECH_RECOGNIZER: Any = None


def _get_speech_recognizer() -> Any:
    """Initializes and caches the speech_recognition.Recognizer instance."""
    global _SPEECH_RECOGNIZER
    if _SPEECH_RECOGNIZER is not None:
        return _SPEECH_RECOGNIZER
    try:
        import speech_recognition as sr
        _SPEECH_RECOGNIZER = sr.Recognizer()
        return _SPEECH_RECOGNIZER
    except Exception as err:
        logger.warning("Error initializing speech_recognition: %s", err)
        return None


def _get_gemini_model() -> Any:
    """Initializes and caches the Gemini GenerativeModel instance."""
    global _GENAI_CONFIGURED, _GEMINI_MODEL
    if _GEMINI_MODEL is not None:
        return _GEMINI_MODEL

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("GOOGLE_API_KEY is not configured; Gemini voice processing unavailable.")
        return None

    try:
        import google.generativeai as genai
        if not _GENAI_CONFIGURED:
            genai.configure(api_key=api_key)
            _GENAI_CONFIGURED = True

        models_to_try = [
            "gemini-flash-lite-latest",
            "gemini-3.8-flash",
            "gemini-flash-latest",
            "gemini-2.5-flash-lite",
        ]
        for m_name in models_to_try:
            try:
                _GEMINI_MODEL = genai.GenerativeModel(m_name)
                return _GEMINI_MODEL
            except Exception as e:
                logger.debug("Could not initialize model %s: %s", m_name, e)
    except Exception as err:
        logger.warning("Error initializing google.generativeai: %s", err)

    return None


def transcribe_and_detect_language(
    audio_data: Any,
    preferred_engine: str = "auto"
) -> Dict[str, Any]:
    """Transcribes audio, detects spoken language, and normalizes into an English command.

    Args:
        audio_data: speech_recognition.AudioData instance.
        preferred_engine: "auto", "google", "fast", or "gemini".
            "auto" uses the fast Google Web Speech API first (~500ms) with seamless
            fallback to Gemini Multimodal STT for multilingual or complex audio.

    Returns:
        Dict with keys:
            success (bool): Whether transcription succeeded.
            transcript (str): User speech in native script.
            language (str): ISO language code ("en", "te", "kn", "hi", "ta", "ml").
            language_name (str): Full name of the language.
            english_command (str): English translated command for route_intent().
            error (str | None): User-facing clean message if failed.
    """
    if audio_data is None:
        return {
            "success": False,
            "transcript": "",
            "language": "en",
            "language_name": "English",
            "english_command": "",
            "error": "I couldn't understand that. Please try again.",
        }

    # Respect environment override if explicitly configured
    env_engine = os.getenv("NEXA_STT_ENGINE", "").lower().strip()
    if env_engine:
        preferred_engine = env_engine

    # 1. Primary Low-Latency Engine: Google Web Speech API (for "auto", "google", "fast")
    # Low latency (~450-650ms) vs ~2400ms for multimodal LLM, highly accurate for desktop voice commands.
    if preferred_engine in ("auto", "google", "fast"):
        try:
            r = _get_speech_recognizer()
            if r is not None:
                text = r.recognize_google(audio_data, language="en-IN")
                cleaned_text = (text or "").strip()
                if cleaned_text:
                    return {
                        "success": True,
                        "transcript": cleaned_text,
                        "language": "en",
                        "language_name": "English",
                        "english_command": cleaned_text,
                        "error": None,
                    }
        except Exception as e:
            logger.debug("Google STT recognition notice (%s); falling back to Gemini Multimodal STT", e)

    # 2. Gemini Multimodal STT (supports all 6 languages + multilingual detection in one pass)
    # Used when preferred_engine == "gemini", or as fallback when Google STT does not understand
    wav_bytes = audio_data.get_wav_data(convert_rate=16000, convert_width=2)
    if not wav_bytes or len(wav_bytes) < 800:
        return {
            "success": False,
            "transcript": "",
            "language": "en",
            "language_name": "English",
            "english_command": "",
            "error": "I couldn't understand that. Please try again.",
        }

    model = _get_gemini_model()
    if model is not None:
        try:
            prompt = (
                "You are NEXA AI's real-time speech recognizer. "
                "Listen carefully to this audio clip and return JSON with:\n"
                "{\n"
                '  "transcript": "exact spoken text in native script",\n'
                '  "language": "en" or "hi" or "te" or "kn" or "ta" or "ml",\n'
                '  "language_name": "English" or "Hindi" or "Telugu" or "Kannada" or "Tamil" or "Malayalam",\n'
                '  "english_command": "concise, direct English command suitable for desktop assistant action routing"\n'
                "}\n"
                "If the audio is silence, static, or unintelligible noise, return:\n"
                '{"transcript": "", "language": "en", "language_name": "English", "english_command": ""}\n'
                "Return ONLY valid JSON."
            )

            resp = model.generate_content(
                [
                    prompt,
                    {"mime_type": "audio/wav", "data": wav_bytes}
                ],
                generation_config={
                    "temperature": 0.0,
                    "max_output_tokens": 100,
                    "response_mime_type": "application/json",
                }
            )

            if resp and resp.text:
                cleaned_json = resp.text.strip()
                if cleaned_json.startswith("```"):
                    cleaned_json = re.sub(r"^```(?:json)?\s*", "", cleaned_json)
                    cleaned_json = re.sub(r"\s*```$", "", cleaned_json)

                data = json.loads(cleaned_json)
                transcript = str(data.get("transcript", "")).strip()
                lang = str(data.get("language", "en")).lower().strip()
                lang_name = str(data.get("language_name", SUPPORTED_LANGUAGES.get(lang, "English"))).strip()
                eng_cmd = str(data.get("english_command", transcript)).strip()

                if lang not in SUPPORTED_LANGUAGES:
                    lang = "en"
                    lang_name = "English"

                if transcript:
                    if not eng_cmd:
                        eng_cmd = transcript
                    return {
                        "success": True,
                        "transcript": transcript,
                        "language": lang,
                        "language_name": lang_name,
                        "english_command": eng_cmd,
                        "error": None,
                    }
        except Exception as e:
            logger.warning("Gemini multimodal STT encountered error: %s", e)

    # 3. Final Fallback to Google STT if Gemini was primary and failed
    if preferred_engine == "gemini":
        try:
            r = _get_speech_recognizer()
            if r is not None:
                text = r.recognize_google(audio_data, language="en-IN")
                cleaned_text = (text or "").strip()
                if cleaned_text:
                    return {
                        "success": True,
                        "transcript": cleaned_text,
                        "language": "en",
                        "language_name": "English",
                        "english_command": cleaned_text,
                        "error": None,
                    }
        except Exception as e:
            logger.debug("Google STT fallback error: %s", e)

    return {
        "success": False,
        "transcript": "",
        "language": "en",
        "language_name": "English",
        "english_command": "",
        "error": "I couldn't understand that. Please try again.",
    }


def translate_response_to_language(text: str, target_lang: str) -> str:
    """Translates an English assistant response back into the user's spoken language.

    If target_lang is English or translation fails, returns text unmodified.
    """
    clean_text = (text or "").strip()
    if not clean_text:
        return ""

    norm_lang = (target_lang or "en").lower().strip()
    if norm_lang == "en" or norm_lang not in SUPPORTED_LANGUAGES:
        return clean_text

    lang_name = SUPPORTED_LANGUAGES.get(norm_lang, "English")
    model = _get_gemini_model()
    if model is None:
        return clean_text

    try:
        prompt = (
            f"Translate this assistant response into natural spoken {lang_name} ({norm_lang}). "
            f"Keep technical terms, app names (like Chrome, YouTube, Python) natural. "
            f"Return ONLY the direct translated sentence with no quotes, notes, or explanation:\n'{clean_text}'"
        )
        resp = model.generate_content(prompt)
        if resp and resp.text:
            translated = resp.text.strip().strip("'\"")
            if translated:
                return translated
    except Exception as err:
        logger.warning("Translation to %s failed: %s; returning original English response", lang_name, err)

    return clean_text


def synthesize_multilingual_audio(text: str, lang: str) -> Optional[str]:
    """Generates a temporary MP3 audio file for native speech playback in supported languages.

    Returns file path string on success, or None for English (to use native SAPI).
    """
    clean_text = (text or "").strip()
    if not clean_text:
        return None

    norm_lang = (lang or "en").lower().strip()
    if norm_lang == "en":
        # English is handled natively and with lowest latency via Windows SAPI
        return None

    if norm_lang not in SUPPORTED_LANGUAGES:
        norm_lang = "en"
        return None

    try:
        from gtts import gTTS
        tts = gTTS(text=clean_text, lang=norm_lang, slow=False)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
            tmp_path = tf.name
        tts.save(tmp_path)
        return tmp_path
    except Exception as err:
        logger.warning("Multilingual speech synthesis failed for %s: %s", norm_lang, err)
        return None
