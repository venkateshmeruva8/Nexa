import os
import sys
import re
import glob
import pickle
import asyncio
import platform
import ctypes
import datetime
import subprocess
import socket
import time
import json
import urllib.request
import logging
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Callable

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    from backend.ml.classifier import predict_intent_details
    from backend.ml.normalizer import normalize_text
except ImportError:
    try:
        from ml.classifier import predict_intent_details
        from ml.normalizer import normalize_text
    except ImportError:
        predict_intent_details = None  # type: ignore
        normalize_text = None  # type: ignore

# Base paths
BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "models" / "nexa_intent_model.pkl"

# Cached model bundle
_CACHED_MODEL_BUNDLE: Optional[Dict[str, Any]] = None

# Key codes for Windows volume control (ctypes native, non-blocking, zero subprocess overhead)
VK_VOLUME_UP = 0xAF    # 175
VK_VOLUME_DOWN = 0xAE  # 174
VK_VOLUME_MUTE = 0xAD  # 173

# Application alias mappings for Windows
COMMON_APPS = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "paint": "mspaint",
    "mspaint": "mspaint",
    "spotify": "spotify",
    "vscode": "code",
    "vs code": "code",
    "code": "code",
    "visual studio code": "code",
    "terminal": "wt",
    "windows terminal": "wt",
    "cmd": "cmd",
    "command prompt": "cmd",
    "powershell": "powershell",
    "explorer": "explorer",
    "file explorer": "explorer",
    "fileexplorer": "explorer",
    "windows explorer": "explorer",
    "clock": "ms-clock:",
    "alarms and clock": "ms-clock:",
    "alarms & clock": "ms-clock:",
    "alarm": "ms-clock:",
    "microsoft store": "ms-windows-store:",
    "ms store": "ms-windows-store:",
    "windows store": "ms-windows-store:",
    "store": "ms-windows-store:",
    "obsidian": "obsidian",
    "copilot": "ms-copilot:",
    "microsoft copilot": "ms-copilot:",
    "task manager": "taskmgr",
    "taskmgr": "taskmgr",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "settings": "ms-settings:",
    "control panel": "control",
    "whatsapp": "whatsapp:",
}

# Process executable mappings for closing applications
APP_PROCESS_MAP = {
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
    "msedge": ["msedge.exe"],
    "notepad": ["notepad.exe"],
    "calculator": ["calculatorapp.exe", "calc.exe", "calculator.exe"],
    "calc": ["calculatorapp.exe", "calc.exe", "calculator.exe"],
    "paint": ["mspaint.exe"],
    "mspaint": ["mspaint.exe"],
    "spotify": ["spotify.exe"],
    "vscode": ["code.exe"],
    "vs code": ["code.exe"],
    "code": ["code.exe"],
    "visual studio code": ["code.exe"],
    "terminal": ["windowsterminal.exe", "wt.exe"],
    "windows terminal": ["windowsterminal.exe", "wt.exe"],
    "cmd": ["cmd.exe"],
    "command prompt": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "task manager": ["taskmgr.exe"],
    "taskmgr": ["taskmgr.exe"],
    "word": ["winword.exe"],
    "excel": ["excel.exe"],
    "powerpoint": ["powerpnt.exe"],
    "whatsapp": ["whatsapp.exe"],
    "obsidian": ["obsidian.exe"],
    "clock": ["time.exe", "clock.exe"],
    "microsoft store": ["winstore.app.exe"],
    "copilot": ["copilot.exe"],
}

# Critical Windows and system processes strictly forbidden from termination
CRITICAL_SYSTEM_PROCESSES = {
    "csrss.exe",
    "lsass.exe",
    "services.exe",
    "wininit.exe",
    "winlogon.exe",
    "smss.exe",
    "svchost.exe",
    "explorer.exe",
    "system",
    "system idle process",
    "registry",
    "runtimebroker.exe",
    "dwm.exe",
    "spoolsv.exe",
    "sihost.exe",
    "fontdrvhost.exe",
}


# Folder alias mappings
COMMON_FOLDERS = {
    "downloads": Path.home() / "Downloads",
    "download": Path.home() / "Downloads",
    "documents": Path.home() / "Documents",
    "document": Path.home() / "Documents",
    "docs": Path.home() / "Documents",
    "desktop": Path.home() / "Desktop",
    "pictures": Path.home() / "Pictures",
    "photos": Path.home() / "Pictures",
    "images": Path.home() / "Pictures",
    "videos": Path.home() / "Videos",
    "movies": Path.home() / "Videos",
    "music": Path.home() / "Music",
    "songs": Path.home() / "Music",
    "home": Path.home(),
    "root": Path.home(),
}

# Settings URI mappings
SETTINGS_MAP = {
    "OPEN_WINDOWS_SETTINGS": ("ms-settings:", "Windows Settings"),
    "OPEN_WIFI_SETTINGS": ("ms-settings:network-wifi", "Wi-Fi Settings"),
    "OPEN_BLUETOOTH_SETTINGS": ("ms-settings:bluetooth", "Bluetooth Settings"),
    "OPEN_NETWORK_SETTINGS": ("ms-settings:network", "Network Settings"),
    "OPEN_DISPLAY_SETTINGS": ("ms-settings:display", "Display Settings"),
    "OPEN_SOUND_SETTINGS": ("ms-settings:sound", "Sound Settings"),
}


def get_model_bundle() -> Optional[Dict[str, Any]]:
    """Loads and caches the trained ML intent model bundle."""
    global _CACHED_MODEL_BUNDLE
    if _CACHED_MODEL_BUNDLE is None and MODEL_PATH.exists():
        try:
            with open(MODEL_PATH, "rb") as f:
                _CACHED_MODEL_BUNDLE = pickle.load(f)
        except Exception:
            _CACHED_MODEL_BUNDLE = None
    return _CACHED_MODEL_BUNDLE


def reload_model_bundle() -> Optional[Dict[str, Any]]:
    """Forces reloading of the trained ML intent model bundle from disk."""
    global _CACHED_MODEL_BUNDLE
    _CACHED_MODEL_BUNDLE = None
    return get_model_bundle()


# ---------------------------------------------------------
# Volume Control Actions
# ---------------------------------------------------------

def _send_volume_pulses_sync(vk_code: int, pulses: int = 5) -> None:
    """Sends native Windows volume keyboard events via ctypes."""
    for _ in range(pulses):
        ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)


async def increase_volume(steps: int = 5) -> str:
    """Increases system volume smoothly and non-blockingly."""
    await asyncio.to_thread(_send_volume_pulses_sync, VK_VOLUME_UP, steps)
    return "Increased system volume."


async def decrease_volume(steps: int = 5) -> str:
    """Decreases system volume smoothly and non-blockingly."""
    await asyncio.to_thread(_send_volume_pulses_sync, VK_VOLUME_DOWN, steps)
    return "Decreased system volume."


# ---------------------------------------------------------
# Brightness Control Actions
# ---------------------------------------------------------

def _get_brightness_sync() -> Optional[int]:
    """Queries current monitor brightness via WMI CIM query."""
    try:
        cmd = ["powershell", "-NoProfile", "-Command",
               "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
        out = res.stdout.strip()
        if out.isdigit():
            return int(out)
    except Exception:
        pass
    return None


def _set_brightness_sync(level: int) -> bool:
    """Sets monitor brightness via WMI CIM method."""
    try:
        level = max(0, min(100, level))
        ps_cmd = (
            f"Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | "
            f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout = 1; Brightness = {level}}}"
        )
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd],
                             capture_output=True, text=True, timeout=5)
        return res.returncode == 0
    except Exception:
        return False


async def increase_brightness(step: int = 10) -> str:
    """Increases screen brightness."""
    curr = await asyncio.to_thread(_get_brightness_sync)
    if curr is None:
        return "Screen brightness adjustment is not supported by your display hardware."
    target = min(100, curr + step)
    success = await asyncio.to_thread(_set_brightness_sync, target)
    if success:
        return f"Increased brightness to {target}%."
    return "Failed to adjust screen brightness."


async def decrease_brightness(step: int = 10) -> str:
    """Decreases screen brightness."""
    curr = await asyncio.to_thread(_get_brightness_sync)
    if curr is None:
        return "Screen brightness adjustment is not supported by your display hardware."
    target = max(0, curr - step)
    success = await asyncio.to_thread(_set_brightness_sync, target)
    if success:
        return f"Decreased brightness to {target}%."
    return "Failed to adjust screen brightness."


async def set_brightness(text_or_level: Any) -> str:
    """Sets screen brightness to a specific percentage parsed from command text or number."""
    target_level = 50
    if isinstance(text_or_level, (int, float)):
        target_level = int(text_or_level)
    elif isinstance(text_or_level, str):
        match = re.search(r"(\d{1,3})", text_or_level)
        if match:
            target_level = int(match.group(1))

    target_level = max(0, min(100, target_level))
    curr = await asyncio.to_thread(_get_brightness_sync)
    if curr is None:
        return "Screen brightness adjustment is not supported by your display hardware."
    success = await asyncio.to_thread(_set_brightness_sync, target_level)
    if success:
        return f"Set brightness to {target_level}%."
    return "Failed to adjust screen brightness."


# ---------------------------------------------------------
# Windows Settings Actions
# ---------------------------------------------------------

def _open_uri_sync(uri: str) -> bool:
    """Opens a Windows protocol URI or file using os.startfile."""
    try:
        os.startfile(uri)
        return True
    except Exception:
        return False


async def open_settings_pane(intent: str) -> str:
    """Opens the requested Windows settings pane."""
    if intent not in SETTINGS_MAP:
        return "Unknown settings panel."
    uri, name = SETTINGS_MAP[intent]
    success = await asyncio.to_thread(_open_uri_sync, uri)
    if success:
        return f"Opened {name}."
    return f"Could not open {name}."


# ---------------------------------------------------------
# Network Toggling Actions (Safe implementation)
# ---------------------------------------------------------

async def toggle_wifi(enable: bool = True) -> str:
    """
    Direct physical radio manipulation requires elevated UAC permissions
    and risks dropping active network connectivity.
    Opens Wi-Fi settings safely so user can toggle it reliably.
    """
    await asyncio.to_thread(_open_uri_sync, "ms-settings:network-wifi")
    state = "on" if enable else "off"
    return f"Direct Wi-Fi toggle requires elevated administrative privileges. Opened Wi-Fi settings so you can switch it {state}."


async def toggle_bluetooth(enable: bool = True) -> str:
    """
    Direct Bluetooth radio manipulation requires elevated UAC permissions.
    Opens Bluetooth settings safely so user can toggle it reliably.
    """
    await asyncio.to_thread(_open_uri_sync, "ms-settings:bluetooth")
    state = "on" if enable else "off"
    return f"Direct Bluetooth toggle requires elevated administrative privileges. Opened Bluetooth settings so you can switch it {state}."


# ---------------------------------------------------------
# Restart & Shutdown Actions (Explicit Confirmation Gate & Test Guard)
# ---------------------------------------------------------

def _is_safe_simulation_mode(dry_run: bool = False) -> bool:
    """Returns True if dry-run parameter or safety environment variable is active."""
    if dry_run:
        return True
    env_flags = ("NEXA_DRY_RUN", "NEXA_TEST_MODE", "NEXA_TESTING", "PYTEST_CURRENT_TEST")
    return any(os.getenv(flag, "").strip().lower() in ("1", "true", "yes") for flag in env_flags)


async def restart_system(confirmed: bool = False, dry_run: bool = False) -> str:
    """
    Restarts the computer. Never executes immediately without explicit confirmation.
    In dry-run or test mode, simulates the action safely without calling shutdown.exe.
    """
    if not confirmed:
        return "Are you sure you want to restart your computer? Please confirm to proceed."
    if _is_safe_simulation_mode(dry_run):
        logging.info("Restart confirmed in dry-run/test mode. Skipping live shutdown.exe execution.")
        return "[DRY-RUN] System restart confirmed. Windows shutdown.exe was not invoked because test/dry-run mode is active."
    try:
        subprocess.run(["shutdown", "/r", "/t", "10"], capture_output=True, text=True)
        return "Restarting your computer in 10 seconds. You can type 'shutdown /a' in command prompt to cancel."
    except Exception as e:
        return f"Failed to initiate system restart: {e}"


async def shutdown_system(confirmed: bool = False, dry_run: bool = False) -> str:
    """
    Shuts down the computer. Never executes immediately without explicit confirmation.
    In dry-run or test mode, simulates the action safely without calling shutdown.exe.
    """
    if not confirmed:
        return "Are you sure you want to shut down your computer? Please confirm to proceed."
    if _is_safe_simulation_mode(dry_run):
        logging.info("Shutdown confirmed in dry-run/test mode. Skipping live shutdown.exe execution.")
        return "[DRY-RUN] System shutdown confirmed. Windows shutdown.exe was not invoked because test/dry-run mode is active."
    try:
        subprocess.run(["shutdown", "/s", "/t", "10"], capture_output=True, text=True)
        return "Shutting down your computer in 10 seconds. You can type 'shutdown /a' in command prompt to cancel."
    except Exception as e:
        return f"Failed to initiate system shutdown: {e}"


# ---------------------------------------------------------
# System Info, Time & Date Actions
# ---------------------------------------------------------

def _get_disk_info_sync() -> List[Dict[str, Any]]:
    """Retrieves disk storage space information across mounted fixed drives."""
    disks = []
    try:
        import psutil
        partitions = psutil.disk_partitions(all=False)
        seen_mounts = set()
        for p in partitions:
            # Skip cdrom or empty filesystem types
            if "cdrom" in p.opts.lower() or not p.fstype:
                continue
            mount = p.mountpoint
            if mount in seen_mounts:
                continue
            seen_mounts.add(mount)
            try:
                usage = psutil.disk_usage(mount)
                dev_name = p.device.rstrip("\\")
                if not dev_name:
                    dev_name = mount.rstrip("\\")
                disks.append({
                    "device": dev_name,
                    "mountpoint": mount,
                    "total_gb": round(usage.total / (1024 ** 3), 1),
                    "used_gb": round(usage.used / (1024 ** 3), 1),
                    "free_gb": round(usage.free / (1024 ** 3), 1),
                    "percent": round(usage.percent, 1),
                })
            except (PermissionError, OSError):
                continue
    except Exception as e:
        logging.warning(f"Could not retrieve disk partitions: {e}")
    return disks


def _extract_app_name_from_resource_query(text: str) -> Optional[str]:
    """Finds known app alias in text for process resource queries."""
    clean = text.lower()
    for alias in (
        "google chrome", "chrome", "vs code", "vscode", "visual studio code",
        "code", "microsoft edge", "edge", "notepad", "calculator", "paint",
        "spotify", "slack", "discord", "whatsapp", "powershell", "terminal",
        "cmd", "command prompt", "word", "excel", "powerpoint"
    ):
        pattern = r"\b" + re.escape(alias) + r"\b"
        if re.search(pattern, clean):
            return alias
    return None


def _get_wifi_details_sync() -> Dict[str, Optional[str]]:
    """
    Retrieves Wi-Fi connection details on Windows via netsh wlan show interfaces.
    Returns dict with state, ssid, signal, and name.
    """
    result: Dict[str, Optional[str]] = {
        "state": None,
        "ssid": None,
        "signal": None,
        "name": None,
    }
    try:
        proc = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            timeout=2.0
        )
        out = proc.stdout or ""
        state_match = re.search(r"^\s*State\s*:\s*(.+)$", out, re.MULTILINE)
        ssid_match = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.MULTILINE)
        signal_match = re.search(r"^\s*Signal\s*:\s*(.+)$", out, re.MULTILINE)
        name_match = re.search(r"^\s*Name\s*:\s*(.+)$", out, re.MULTILINE)

        if state_match:
            result["state"] = state_match.group(1).strip()
        if ssid_match:
            result["ssid"] = ssid_match.group(1).strip()
        if signal_match:
            result["signal"] = signal_match.group(1).strip()
        if name_match:
            result["name"] = name_match.group(1).strip()
    except Exception as e:
        logging.warning(f"Could not retrieve Wi-Fi details via netsh: {e}")

    return result


def _get_local_ip_sync() -> Tuple[Optional[str], Optional[str]]:
    """
    Finds the active outbound IPv4 address and its corresponding interface name.
    Falls back to inspecting psutil net_if_addrs for active non-loopback interfaces.
    """
    local_ip = None
    adapter_name = None

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    try:
        import psutil
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()

        if local_ip:
            for iface, addr_list in addrs.items():
                for addr in addr_list:
                    if addr.family == socket.AF_INET and addr.address == local_ip:
                        adapter_name = iface
                        break
                if adapter_name:
                    break
            return local_ip, adapter_name

        # Fallback: scan for any active non-loopback, non-APIPA IPv4 address
        for iface, stat in stats.items():
            if stat.isup and iface in addrs:
                for addr in addrs[iface]:
                    if addr.family == socket.AF_INET and not addr.address.startswith("127.") and not addr.address.startswith("169.254."):
                        return addr.address, iface
    except Exception as e:
        logging.warning(f"Could not determine local IP/adapter: {e}")

    return local_ip, adapter_name


def _get_public_ip_sync() -> Optional[str]:
    """
    Queries lightweight public IP lookup services (api.ipify.org, checkip.amazonaws.com).
    Returns the public IP string, or None if unreachable.
    """
    lookup_urls = [
        "https://api.ipify.org",
        "https://checkip.amazonaws.com"
    ]
    for url in lookup_urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "NEXA/1.0"})
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                raw = resp.read().decode("utf-8").strip()
                if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", raw):
                    return raw
        except Exception:
            continue
    return None


def _measure_ping_sync(host: str = "1.1.1.1") -> Tuple[bool, Optional[float]]:
    """
    Measures round-trip latency to a reliable public host (Cloudflare DNS: 1.1.1.1).
    Attempts native ICMP ping first, with TCP socket fallback.
    Returns (is_online, latency_ms).
    """
    # 1. ICMP ping
    try:
        proc = subprocess.run(
            ["ping", "-n", "1", "-w", "1200", host],
            capture_output=True,
            text=True,
            timeout=2.5
        )
        if proc.returncode == 0:
            m = re.search(r"(?:time[=<]|Average = )(\d+)ms", proc.stdout or "", re.I)
            if m:
                return True, float(m.group(1))
            return True, 15.0
    except Exception:
        pass

    # 2. TCP socket connection fallback (port 53 DNS)
    t0 = time.time()
    try:
        sock = socket.create_connection((host, 53), timeout=1.5)
        sock.close()
        latency = round((time.time() - t0) * 1000, 1)
        return True, latency
    except Exception:
        pass

    return False, None


def _get_network_io_sync() -> Tuple[int, int]:
    """
    Retrieves cumulative bytes sent and received since system boot.
    Returns (bytes_sent, bytes_recv).
    """
    try:
        import psutil
        io = psutil.net_io_counters()
        return io.bytes_sent, io.bytes_recv
    except Exception:
        return 0, 0


AUDIO_CORE_CSHARP = r"""
using System;
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IAudioEndpointVolume {
    int f(); int g(); int h(); int i(); 
    int SetMasterVolumeLevelScalar(float fLevel, Guid pguidEventContext);
    int j(); 
    int GetMasterVolumeLevelScalar(out float pfLevel);
    int k(); int l(); int m(); int n();
    int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, Guid pguidEventContext);
    int GetMute(out bool pbMute);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDevice {
    int Activate(ref Guid id, int clsCtx, int activationParams, out IAudioEndpointVolume aev);
}
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDeviceEnumerator {
    int f(); 
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint);
}
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
public class MMDeviceEnumeratorComObject { }
public class AudioHelper {
    static IAudioEndpointVolume GetVol(int dataFlow) {
        var enumerator = new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator;
        IMMDevice dev = null;
        enumerator.GetDefaultAudioEndpoint(dataFlow, 1, out dev);
        IAudioEndpointVolume epv = null;
        var epvid = typeof(IAudioEndpointVolume).GUID;
        dev.Activate(ref epvid, 23, 0, out epv);
        return epv;
    }
    public static string GetStatus() {
        float v = -1; GetVol(0).GetMasterVolumeLevelScalar(out v);
        bool m = false; GetVol(0).GetMute(out m);
        bool mm = false;
        try { GetVol(1).GetMute(out mm); } catch {}
        return string.Format("{0}|{1}|{2}", (int)Math.Round(v * 100), m, mm);
    }
    public static void SetMute(bool mute) {
        GetVol(0).SetMute(mute, Guid.Empty);
    }
    public static void SetMicMute(bool mute) {
        GetVol(1).SetMute(mute, Guid.Empty);
    }
}
"""


def _get_audio_endpoint_status_sync() -> Tuple[Optional[int], Optional[bool], Optional[bool]]:
    """
    Queries Windows CoreAudio for master volume level, master mute state, and mic mute state.
    Returns (volume_percent, is_volume_muted, is_mic_muted).
    """
    ps = f'Add-Type -TypeDefinition @"\n{AUDIO_CORE_CSHARP}\n"@\n[AudioHelper]::GetStatus()'
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=4.0
        )
        parts = proc.stdout.strip().split("|")
        if len(parts) == 3:
            vol = int(parts[0]) if parts[0].isdigit() or (parts[0].startswith('-') and parts[0][1:].isdigit()) else None
            if vol is not None:
                vol = max(0, min(100, vol))
            mute = parts[1].strip().lower() == "true"
            mic_mute = parts[2].strip().lower() == "true"
            return vol, mute, mic_mute
    except Exception as e:
        logging.warning(f"Error querying audio endpoint status via CoreAudio: {e}")
    return None, None, None


def _set_volume_mute_sync(mute: bool) -> bool:
    """Sets master system volume mute state via CoreAudio."""
    val = "$true" if mute else "$false"
    ps = f'Add-Type -TypeDefinition @"\n{AUDIO_CORE_CSHARP}\n"@\n[AudioHelper]::SetMute({val})'
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=4.0
        )
        return proc.returncode == 0
    except Exception as e:
        logging.warning(f"Error setting volume mute: {e}")
        return False


def _set_mic_mute_sync(mute: bool) -> bool:
    """Sets master microphone mute state via CoreAudio."""
    val = "$true" if mute else "$false"
    ps = f'Add-Type -TypeDefinition @"\n{AUDIO_CORE_CSHARP}\n"@\n[AudioHelper]::SetMicMute({val})'
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=4.0
        )
        return proc.returncode == 0
    except Exception as e:
        logging.warning(f"Error setting microphone mute: {e}")
        return False


async def mute_system_volume(mute: bool = True, dry_run: bool = False) -> str:
    """Mutes or unmutes system audio with simulation guard."""
    action_word = "mute" if mute else "unmute"
    past_word = "Muted" if mute else "Unmuted"
    if _is_safe_simulation_mode(dry_run):
        return f"[DRY-RUN] System audio {action_word} simulated. Device volume state was not modified because test/dry-run mode is active."
    success = await asyncio.to_thread(_set_volume_mute_sync, mute)
    if success:
        return f"{past_word} system volume."
    return f"Failed to {action_word} system volume."


async def mute_microphone(mute: bool = True, dry_run: bool = False) -> str:
    """Mutes or unmutes microphone input with simulation guard."""
    action_word = "mute" if mute else "unmute"
    past_word = "Muted" if mute else "Unmuted"
    if _is_safe_simulation_mode(dry_run):
        return f"[DRY-RUN] Microphone {action_word} simulated. Device microphone state was not modified because test/dry-run mode is active."
    success = await asyncio.to_thread(_set_mic_mute_sync, mute)
    if success:
        return f"{past_word} microphone."
    return f"Failed to {action_word} microphone."


def _clean_device_name(name: Optional[str]) -> str:
    """Cleans up raw audio device name string."""
    if not name:
        return "Unknown Device"
    cleaned = re.sub(r"[\ufffd\x80-\xff]+", "", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _get_audio_devices_sync() -> Dict[str, Any]:
    """
    Queries sounddevice for default input/output devices and tests input readiness.
    """
    result: Dict[str, Any] = {
        "output_device": None,
        "input_device": None,
        "mic_available": False,
        "mic_working": False,
    }
    try:
        import sounddevice as sd
        defaults = sd.default.device
        devices = sd.query_devices()

        if defaults[1] is not None and defaults[1] >= 0 and defaults[1] < len(devices):
            raw_out = devices[defaults[1]]["name"]
            result["output_device"] = _clean_device_name(raw_out)

        if defaults[0] is not None and defaults[0] >= 0 and defaults[0] < len(devices):
            raw_in = devices[defaults[0]]["name"]
            result["input_device"] = _clean_device_name(raw_in)
            result["mic_available"] = True
            try:
                sd.check_input_settings(device=defaults[0])
                result["mic_working"] = True
            except Exception:
                result["mic_working"] = False

    except Exception as e:
        logging.warning(f"Error querying audio devices via sounddevice: {e}")

    return result


def _get_camera_status_sync() -> Dict[str, Any]:
    """
    Queries Windows PnP devices for camera/webcam hardware availability and status.
    """
    result = {
        "available": False,
        "name": None,
        "status": "Not detected",
    }
    try:
        cmd = [
            "powershell", "-NoProfile", "-Command",
            "Get-PnpDevice -Class Camera,Image | Where-Object { $_.Status -ne 'Unknown' } | Select-Object FriendlyName, Status, Present | ConvertTo-Json"
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=4.0)
        out = proc.stdout.strip()
        if out:
            data = json.loads(out)
            if isinstance(data, list) and len(data) > 0:
                c = data[0]
            elif isinstance(data, dict):
                c = data
            else:
                c = {}

            if c.get("FriendlyName"):
                result["name"] = c["FriendlyName"]
                status = c.get("Status", "OK")
                present = c.get("Present", True)
                result["available"] = (status == "OK" and present is True)
                result["status"] = status
    except Exception as e:
        logging.warning(f"Error querying camera status: {e}")

    return result


# -------------------------------------------------------------------------
# Camera Frame State & Vision Hooks
# -------------------------------------------------------------------------
_CAMERA_ACTIVE: bool = False
_LATEST_CAMERA_FRAME: Any = None
_CAMERA_FRAME_GETTER: Optional[Callable[[], Any]] = None


def set_camera_active_state(active: bool) -> None:
    """Set global camera viewport activation state."""
    global _CAMERA_ACTIVE
    _CAMERA_ACTIVE = bool(active)


def is_camera_active() -> bool:
    """Check if camera viewport is currently active."""
    return _CAMERA_ACTIVE


def set_camera_frame_provider(getter: Optional[Callable[[], Any]]) -> None:
    """Register thread-safe callback to fetch the latest camera frame."""
    global _CAMERA_FRAME_GETTER
    _CAMERA_FRAME_GETTER = getter


def set_latest_camera_frame(frame: Any) -> None:
    """Explicitly cache the latest camera frame."""
    global _LATEST_CAMERA_FRAME
    _LATEST_CAMERA_FRAME = frame


def get_latest_camera_frame() -> Any:
    """Retrieve the latest camera frame from registered provider or cache."""
    if _CAMERA_FRAME_GETTER is not None:
        try:
            f = _CAMERA_FRAME_GETTER()
            if f is not None:
                return f
        except Exception as e:
            logging.warning(f"Error fetching frame from provider: {e}")
    return _LATEST_CAMERA_FRAME


def _clean_for_tts(text: str) -> str:
    """Sanitize assistant responses and descriptions for natural TTS and speech output."""
    if not text:
        return ""
    # Strip code blocks and JSON blocks
    cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"\{[^{}]*:[^{}]*\}", "", cleaned)

    # Strip markdown headers, bold, italics, strikethrough, backticks
    cleaned = re.sub(r"[`*_#~]", "", cleaned)

    # Convert markdown links [Label](url) -> Label
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)

    # Strip raw URLs (e.g. https://www.google.com/search?q=...)
    cleaned = re.sub(r"https?://\S+", "", cleaned)

    # Strip list bullets (e.g. * item, - item, 1. item)
    cleaned = re.sub(r"(?m)^\s*[-*•]\s+", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*\d+\.\s+", "", cleaned)

    # Strip dry-run and internal debug tags like [DRY-RUN]
    cleaned = re.sub(r"\[(?:DRY-RUN|DEBUG|INFO|NOTICE)\]", "", cleaned, flags=re.IGNORECASE)

    # Strip intent diagnostics like "intent: SEARCH_WEB", "confidence: 0.95", "margin: 0.8"
    cleaned = re.sub(r"\b(?:intent|confidence|margin|trusted|fallback)\s*[:=]\s*[^,;\n]+", "", cleaned, flags=re.IGNORECASE)

    # Strip special characters such as # @ * ) ( [ ] { } \ / ^ ~ < > | =
    cleaned = re.sub(r"[@#*()\[\]{}\\\/^~<>|+=_]", " ", cleaned)

    # Collapse multiple whitespaces and newlines into single spaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned



def _convert_frame_to_jpeg_bytes(frame: Any) -> Optional[bytes]:
    """Convert frame (QImage, PIL.Image, or raw bytes) to JPEG bytes in-memory."""
    if frame is None:
        return None

    if isinstance(frame, (bytes, bytearray)):
        return bytes(frame)

    # Check for PySide6 / PyQt QImage
    try:
        from PySide6.QtGui import QImage
        from PySide6.QtCore import QBuffer, QIODevice
        if isinstance(frame, QImage):
            if frame.isNull():
                return None
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            frame.save(buf, "JPEG", quality=85)
            data = bytes(buf.data().data())
            buf.close()
            return data
    except ImportError:
        pass

    # Check for PIL Image
    try:
        import io
        from PIL import Image
        if isinstance(frame, Image.Image):
            buf = io.BytesIO()
            frame.convert("RGB").save(buf, format="JPEG", quality=85)
            return buf.getvalue()
    except ImportError:
        pass

    return None


def _capture_live_camera_frame_sync() -> Optional[bytes]:
    """Capture a single frame directly from the physical webcam synchronously on demand."""
    try:
        import subprocess
        import sys

        code = (
            "import sys\n"
            "from PySide6.QtCore import QTimer, QEventLoop, QBuffer, QIODevice\n"
            "from PySide6.QtGui import QGuiApplication\n"
            "from PySide6.QtMultimedia import QMediaDevices, QCamera, QMediaCaptureSession, QVideoSink\n"
            "app = QGuiApplication(sys.argv)\n"
            "devs = QMediaDevices.videoInputs()\n"
            "if not devs:\n"
            "    sys.exit(1)\n"
            "cam = QCamera(devs[0])\n"
            "session = QMediaCaptureSession()\n"
            "session.setCamera(cam)\n"
            "sink = QVideoSink()\n"
            "session.setVideoSink(sink)\n"
            "captured = None\n"
            "def on_frame(f):\n"
            "    global captured\n"
            "    if f.isValid() and captured is None:\n"
            "        captured = f.toImage()\n"
            "sink.videoFrameChanged.connect(on_frame)\n"
            "cam.start()\n"
            "loop = QEventLoop()\n"
            "def check():\n"
            "    if captured is not None or not cam.isActive():\n"
            "        loop.quit()\n"
            "timer = QTimer()\n"
            "timer.timeout.connect(check)\n"
            "timer.start(50)\n"
            "QTimer.singleShot(2500, loop.quit)\n"
            "loop.exec()\n"
            "cam.stop()\n"
            "if captured is not None and not captured.isNull():\n"
            "    buf = QBuffer()\n"
            "    buf.open(QIODevice.OpenModeFlag.WriteOnly)\n"
            "    captured.save(buf, 'JPEG', quality=85)\n"
            "    sys.stdout.buffer.write(bytes(buf.data().data()))\n"
            "    buf.close()\n"
            "    sys.exit(0)\n"
            "sys.exit(2)\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            timeout=4.5,
        )
        if proc.returncode == 0 and proc.stdout:
            return bytes(proc.stdout)
        return None
    except Exception as e:
        logging.warning(f"Direct camera frame capture failed: {e}")
        return None


def _is_visual_search_query(text: str) -> bool:
    """Determine whether the natural language command is a visual product search for an item in front of the camera."""
    clean = re.sub(
        r"^(?:nexa[,\s]+|hey nexa[,\s]+|please\s+|can you\s+|could you\s+)",
        "",
        text.strip().lower(),
    ).strip(" ?.")

    # Visual search patterns referencing physical objects in front of camera
    patterns = [
        r"^(?:search\s+for|find|look\s+up|buy)\s+(?:these|this)\s+[a-z]+(?:\s+online)?$",
        r"^(?:search\s+for|find|look\s+up)\s+what\s+(?:i\s+am\s+holding|i\'m\s+holding|is\s+in\s+my\s+hand)(?:\s+online)?$",
        r"^(?:search\s+for|find|look\s+up)\s+this\s+object(?:\s+online)?$",
        r"^(?:where\s+can\s+i\s+buy\s+this|how\s+much\s+is\s+this|shop\s+for\s+this)$",
    ]
    return any(re.search(p, clean) for p in patterns)


def _is_screen_understanding_query(text: str) -> bool:
    """Determine whether the natural language command is a screen understanding question."""
    if not text:
        return False
    clean = text.strip().lower()
    clean = re.sub(r"^(?:nexa[,\s]+|hey nexa[,\s]+)", "", clean).strip()
    clean = re.sub(r"^(?:can\s+you\s+(?:please\s+|tell\s+me\s+)?|could\s+you\s+(?:please\s+|tell\s+me\s+)?|please\s+(?:tell\s+me\s+)?|tell\s+me\s+)", "", clean).strip()
    clean_nopunct = re.sub(r"[^a-z0-9\s]", " ", clean)
    clean_norm = re.sub(r"\s+", " ", clean_nopunct).strip()

    # Guard 1: Screen share commands must route to SCREEN_SHARE
    if re.search(r"\b(?:share|sharing)\b", clean_norm):
        return False

    # Guard 2: Camera/personal vision queries
    if re.search(r"\b(?:see\s+me|wearing|dressed|holding|in\s+front\s+of\s+me|looking\s+like\s+me)\b", clean_norm):
        return False

    # Guard 3: Application inspection plural / running list
    if re.search(r"\b(?:running\s+(?:apps|applications)|list\s+(?:open|running)\s+(?:apps|applications)|what\s+(?:apps|applications)\s+are\s+running)\b", clean_norm):
        return False

    # Specific Screen Understanding Regex Patterns
    screen_patterns = [
        # Screen content / description
        r"\b(?:what\s+is|what\s+s|whats)\s+on\s+(?:my\s+|the\s+)?screen\b",
        r"\b(?:what\s+(?:do\s+you|can\s+you|you)?|describe\s+what\s+you)\s+see\s+on\s+(?:my\s+|the\s+)?screen\b",
        r"\b(?:describe|explain)\s+(?:what\s+is\s+on\s+|what\s+s\s+on\s+)?(?:my\s+|the\s+)?screen\b",
        r"\bread\s+(?:what\s+is\s+on\s+|what\s+s\s+on\s+|what\s+is\s+written\s+on\s+)?(?:my\s+|the\s+)?screen\b",
        r"\b(?:can\s+you\s+)?see\s+(?:what\s+is\s+on\s+|what\s+s\s+on\s+)?(?:my\s+|the\s+)?screen\b",
        r"\bwhat\s+(?:does\s+)?(?:my\s+|the\s+)?screen\s+show\b",
        # What am I looking at
        r"\b(?:what\s+am\s+i|what\s+i\s+am)\s+looking\s+at\b",
        # Active tab
        r"\b(?:which|what)\s+tab\s+is\s+(?:open|active)\b",
        r"\b(?:current|active)\s+tab\b",
        # Active application (singular)
        r"\b(?:which|what)\s+(?:application|app)\s+is\s+(?:open|active|in\s+focus)\b",
        r"\b(?:current|active)\s+(?:application|app)\b",
    ]

    return any(re.search(p, clean_norm) for p in screen_patterns)


def _is_camera_vision_query(text: str) -> bool:
    """Determine whether the natural language command is a camera visual question."""
    if not text:
        return False
    if _is_visual_search_query(text):
        return False
    if _is_screen_understanding_query(text):
        return False

    clean = text.strip().lower()
    if "screen" in clean:
        return False
    clean = re.sub(r"^(?:nexa[,\s]+|hey nexa[,\s]+)", "", clean).strip()

    # Exact camera control commands that must NOT be treated as visual queries
    control_exact = {
        "turn on camera", "turn on the camera", "turn on my camera", "open camera", "open the camera", "open my camera",
        "start camera", "start the camera", "start my camera", "enable camera", "enable the camera",
        "turn off camera", "turn off the camera", "turn off my camera", "close camera", "close the camera", "close my camera",
        "stop camera", "stop the camera", "stop my camera", "disable camera", "disable the camera",
        "turn camera on", "turn camera off", "activate camera", "deactivate camera",
        "is my camera available", "is my camera working", "camera status", "is camera working", "is camera available",
        "open the camera roll folder", "open camera folder", "open camera roll"
    }
    if clean.strip(" ?.") in control_exact:
        return False

    vision_regexes = [
        # See me / presence
        r"\bsee\s+me\b",
        r"\bsee\s+(?:anyone|anybody|a\s+person|someone)\b",
        r"\bperson\s+in\s+front\s+of\b",
        r"\blook\s+at\s+me\b",
        # Wearing / clothes
        r"\b(?:what\s+am\s+i|what\s+i\s+am)\s+(?:wearing|dressed)\b",
        r"\b(?:what\s+color\s+is\s+my\s+(?:shirt|clothes|t-shirt|top|dress))\b",
        r"\bdescribe\s+(?:my\s+clothes|what\s+i\s+am\s+wearing)\b",
        # Doing / activity
        r"\b(?:what\s+am\s+i|what\s+i\s+am)\s+(?:doing|holding|showing)\b",
        r"\bdescribe\s+(?:what\s+i\s+am\s+doing|my\s+action)\b",
        # In front of me/you/camera
        r"\bin\s+front\s+of\s+(?:me|you|the\s+camera|my\s+camera)\b",
        # What do you see / describe what you see
        r"\b(?:what\s+do\s+you|what\s+can\s+you|describe\s+what\s+you)\s+see\b",
        r"\bwhat\s+you\s+see\b",
        # What is this / that / object
        r"\bwhat(?:\'s|\s+is)\s+(?:this|that)\b",
        r"\bwhat\s+object\s+is\s+this\b",
        r"\bidentify\s+this\b",
        r"\blook\s+at\s+this\b",
        r"\bwhat(?:\'s|\s+is)\s+in\s+(?:my\s+)?hand\b",
        r"\bwhat\s+color\s+is\s+(?:this|that|the\s+object)\b",
        r"\bwhat\s+color\s+do\s+you\s+see\b",
        r"\bdescribe\s+this\s+object\b",
        r"\bwhat\s+does\s+this\s+look\s+like\b",
    ]

    for p in vision_regexes:
        if re.search(p, clean):
            return True
    return False


async def execute_visual_product_search(text: str, dry_run: bool = False) -> str:
    """
    Captures live camera frame, analyzes the target object with Gemini vision,
    derives a concise search query, and opens Chrome with the search results.
    """
    clean_low = text.strip().lower()

    # Dry-run or test mode: simulate query generation from object keyword
    if dry_run or os.getenv("NEXA_TEST_MODE") == "1":
        match = re.search(r"(?:these|this)\s+([a-z]+)", clean_low)
        item = match.group(1) if match else "product"
        simulated_query = f"{item}"
        if item == "glasses":
            simulated_query = "reading glasses"
        elif item == "dress":
            simulated_query = "casual summer dress"
        elif item == "shoes":
            simulated_query = "casual running shoes"
        elif item == "watch":
            simulated_query = "wrist watch"

        await execute_web_search(simulated_query, dry_run=True)
        return f"Searching for {simulated_query} in Chrome."

    frame = get_latest_camera_frame()
    if frame is None:
        frame = await asyncio.to_thread(_capture_live_camera_frame_sync)

    if frame is None:
        return "I couldn't access the camera right now."

    jpeg_bytes = _convert_frame_to_jpeg_bytes(frame)
    if not jpeg_bytes:
        return "I couldn't access the camera right now."

    # Live mode: use Gemini multimodal vision to generate search query
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "Google API key is not configured for visual search."

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        part = types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg")

        sys_instruct = (
            f"Analyze the product or item indicated in this image (User command: '{text}'). "
            "Identify its specific visual characteristics (type, style, color, distinguishing features) and "
            "output ONLY a concise, high-relevance search query of 3 to 6 words suitable for finding it online. "
            "Do not include markdown, quotes, punctuation, or explanations."
        )

        models_to_try = [
            "gemini-flash-lite-latest",
            "gemini-3.8-flash",
            "gemini-flash-latest",
        ]

        identified_query = ""
        for model_name in models_to_try:
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=[part, sys_instruct],
                )
                if resp and resp.text:
                    identified_query = resp.text.strip().strip('"\'`')
                    identified_query = identified_query.split("\n")[0].strip()
                    break
            except Exception as model_err:
                logging.warning(f"Visual product search with {model_name} failed: {model_err}")

        if not identified_query:
            return "The image was captured, but visual analysis was unavailable right now."

        await execute_web_search(identified_query, dry_run=False)
        return f"Searching for {identified_query} in Chrome."

    except Exception as err:
        logging.warning(f"Visual product search error: {err}")
        return "The image was captured, but visual analysis was unavailable right now."


async def execute_camera_vision_query(text: str, dry_run: bool = False) -> str:
    """
    Analyzes live camera feed on-demand using Gemini multimodal vision.
    Captures live frame from active preview or directly from webcam hardware.
    """
    # In dry-run or automated test mode without real camera:
    if dry_run or os.getenv("NEXA_TEST_MODE") == "1":
        clean_low = text.strip().lower()
        if any(k in clean_low for k in ("see me", "person", "see anyone")):
            return "Yes, I can see you clearly in front of the camera."
        elif any(k in clean_low for k in ("wearing", "dressed")):
            return "You appear to be wearing a dark shirt in front of the camera."
        elif "doing" in clean_low:
            return "You are sitting at your desk facing the camera."
        elif any(k in clean_low for k in ("in front of me", "in front of you", "in front of the camera")):
            return "In front of you is your computer desk and monitor setup."
        elif any(k in clean_low for k in ("holding", "in my hand", "identify this", "what is this", "what object")):
            return "You are holding an item in front of the camera."
        elif "color" in clean_low:
            return "I can see dark slate color tones and clear contrast in the camera frame."
        else:
            return "I can see the camera viewport is active and displaying the current view."

    # Real on-demand frame capture
    frame = get_latest_camera_frame()
    if frame is None:
        frame = await asyncio.to_thread(_capture_live_camera_frame_sync)

    if frame is None:
        return "I couldn't access the camera right now."

    jpeg_bytes = _convert_frame_to_jpeg_bytes(frame)
    if not jpeg_bytes:
        return "I couldn't access the camera right now."

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "Google API key is not configured for vision analysis."

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        part = types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg")

        sys_instruct = (
            "You are NEXA, a helpful desktop AI assistant analyzing a single live camera frame in response to the user's question. "
            "Answer concisely and naturally in 1-2 plain text sentences suitable for text-to-speech based ONLY on what is clearly visible in the image. "
            "Never use markdown formatting, bullet points, asterisks, hashtags, or raw JSON."
        )

        models_to_try = [
            "gemini-flash-lite-latest",
            "gemini-3.8-flash",
            "gemini-flash-latest",
        ]

        response_text = ""
        for model_name in models_to_try:
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=[part, f"{sys_instruct}\nUser Question: {text}"],
                )
                if resp and resp.text:
                    response_text = resp.text.strip()
                    break
            except Exception as model_err:
                logging.warning(f"Vision analysis with {model_name} failed: {model_err}")

        if response_text:
            return _clean_for_tts(response_text)
        return "The image was captured, but visual analysis was unavailable right now."

    except Exception as err:
        logging.warning(f"Camera vision error: {err}")
        return "The image was captured, but visual analysis was unavailable right now."


def _capture_screen_frame_sync() -> Optional[bytes]:
    """
    Capture a single current desktop screen frame in-memory on demand using PySide6.
    Returns JPEG bytes or None if capture is unavailable.
    """
    try:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import QBuffer, QIODevice
        import sys
        import threading

        app = QGuiApplication.instance()
        if not app:
            if threading.current_thread() is threading.main_thread():
                app = QGuiApplication(sys.argv)
            else:
                logging.warning("No QGuiApplication instance found on main thread for screen capture.")
                return None

        screen = QGuiApplication.primaryScreen()
        if not screen:
            logging.warning("No primary screen detected for screen capture.")
            return None

        pix = screen.grabWindow(0)
        if pix.isNull():
            return None

        img = pix.toImage()
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "JPEG", quality=85)
        data = bytes(buf.data().data())
        buf.close()
        return data
    except Exception as e:
        logging.warning(f"Screen capture error: {e}")
        return None


async def execute_screen_understanding(text: str, dry_run: bool = False) -> str:
    """
    Captures the current visible desktop screen frame and analyzes it on-demand
    using Gemini multimodal vision to answer the user's question.
    """
    clean_low = text.strip().lower()

    # Dry-run or test mode simulation
    if dry_run or os.getenv("NEXA_TEST_MODE") == "1":
        if "tab" in clean_low:
            return "I see your active browser tab is displaying the current web page."
        elif "app" in clean_low or "application" in clean_low:
            return "The active application open on your screen is NEXA AI Assistant."
        elif "read" in clean_low:
            return "The visible text on your screen shows your desktop workspace and active windows."
        elif "explain" in clean_low:
            return "Your screen displays your current desktop environment with open applications."
        else:
            return "I can see your current desktop screen with active application windows."

    # Real on-demand desktop frame capture (executed in ~20ms)
    jpeg_bytes = _capture_screen_frame_sync()
    if not jpeg_bytes:
        return "I couldn't access the screen right now."

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "Google API key is not configured for vision analysis."

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        part = types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg")

        sys_instruct = (
            "You are NEXA, a helpful desktop AI assistant analyzing a single live screenshot of the user's computer screen in response to the user's question. "
            "Answer concisely and naturally in 1-2 plain text sentences suitable for text-to-speech based ONLY on what is clearly visible on the screen. "
            "Do not guess or hallucinate content that is not visible. Never use markdown formatting, bullet points, asterisks, hashtags, or raw JSON."
        )

        models_to_try = [
            "gemini-flash-lite-latest",
            "gemini-3.8-flash",
            "gemini-flash-latest",
        ]

        response_text = ""
        for model_name in models_to_try:
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=[part, f"{sys_instruct}\nUser Question: {text}"],
                )
                if resp and resp.text:
                    response_text = resp.text.strip()
                    break
            except Exception as model_err:
                logging.warning(f"Screen vision analysis with {model_name} failed: {model_err}")

        if response_text:
            return _clean_for_tts(response_text)
        return "The screen was captured, but visual analysis was unavailable right now."

    except Exception as err:
        logging.warning(f"Screen vision error: {err}")
        return "The screen was captured, but visual analysis was unavailable right now."


def _get_system_info_sync(query: Optional[str] = None) -> str:
    """
    Retrieves OS, CPU, RAM, Battery, Storage, and Health details non-blockingly.
    Answers specific resource questions when query is provided, or full status if general.
    """
    try:
        import psutil
        clean_q = (query or "").strip().lower()

        # 1. Application-specific resource query (e.g. "How much RAM is Chrome using?")
        app_match = _extract_app_name_from_resource_query(clean_q)
        if app_match and any(k in clean_q for k in ("ram", "memory", "cpu", "resource")):
            return _get_process_awareness_sync(app_name=app_match)

        # 2. Top memory / RAM consumers query
        if any(k in clean_q for k in ("most memory", "highest memory", "most ram", "top memory", "using most memory")):
            return _get_process_awareness_sync(top_memory=True)

        # 3. RAM / Memory query
        if any(k in clean_q for k in ("ram", "memory", "how much ram", "how much memory", "ram usage", "memory usage")) and not any(k in clean_q for k in ("status", "info", "health", "system")):
            mem = psutil.virtual_memory()
            used_gb = round(mem.used / (1024 ** 3), 1)
            total_gb = round(mem.total / (1024 ** 3), 1)
            free_gb = round(mem.available / (1024 ** 3), 1)
            return f"You are currently using {used_gb} GB of RAM out of {total_gb} GB, which is {round(mem.percent, 1)}% of your total memory with {free_gb} GB available."

        # 4. CPU usage query
        if any(k in clean_q for k in ("cpu", "processor", "cpu usage", "processor usage", "cpu being used")) and not any(k in clean_q for k in ("status", "info", "health", "system")):
            cpu_usage = psutil.cpu_percent(interval=0.1)
            logical_cores = psutil.cpu_count(logical=True)
            return f"Current CPU usage is at {cpu_usage}% across {logical_cores} logical cores."

        # 5. Battery Charging query (e.g. "Is my battery charging?", "Is the laptop plugged in?")
        if any(k in clean_q for k in ("charging", "plugged in", "power adapter", "is my battery charging", "is my laptop charging", "is the battery charging")):
            batt = psutil.sensors_battery()
            if not batt:
                return "This system is running on AC power with no battery detected."
            if batt.power_plugged:
                if batt.percent >= 100:
                    return "Yes, your laptop is plugged in and fully charged at 100%."
                return f"Yes, your laptop is plugged in and charging at {batt.percent}%."
            else:
                return f"No, your laptop is not charging. It is running on battery power at {batt.percent}%."

        # 6. Battery Level / Remaining query (e.g. "How much battery is left?")
        if any(k in clean_q for k in ("battery", "battery left", "battery percent", "battery remaining", "how much battery")):
            batt = psutil.sensors_battery()
            if not batt:
                return "This system is running on AC power with no battery detected."
            charging_str = "plugged in and charging" if batt.power_plugged else "on battery power"
            if batt.power_plugged and batt.percent >= 100:
                charging_str = "plugged in and fully charged"
            time_str = ""
            if not batt.power_plugged and batt.secsleft and batt.secsleft > 0 and batt.secsleft != psutil.POWER_TIME_UNLIMITED:
                hrs = batt.secsleft // 3600
                mins = (batt.secsleft % 3600) // 60
                if hrs > 0:
                    time_str = f" with about {hrs} hour{'s' if hrs != 1 else ''} and {mins} minute{'s' if mins != 1 else ''} remaining"
                else:
                    time_str = f" with about {mins} minute{'s' if mins != 1 else ''} remaining"
            return f"Your battery is at {batt.percent}% ({charging_str}{time_str})."

        # 7. Which drive is running low / Low disk space query
        if any(k in clean_q for k in ("running low", "low disk", "low space", "drive full", "disk full", "low storage", "out of space", "drive is low", "drives running low")):
            disks = _get_disk_info_sync()
            if not disks:
                return "Unable to access disk storage information."
            low_disks = [d for d in disks if d['percent'] >= 85.0 or d['free_gb'] < 15.0]
            if low_disks:
                low_parts = [f"Drive {d['device']} with {d['free_gb']} GB free ({d['percent']}% full)" for d in low_disks]
                other_disks = [d for d in disks if d not in low_disks]
                other_str = ""
                if other_disks:
                    other_parts = [f"Drive {d['device']} has {d['free_gb']} GB free" for d in other_disks]
                    other_str = f" Meanwhile, {', and '.join(other_parts)}."
                prefix = "The following drive is running low on space: " if len(low_disks) == 1 else "The following drives are running low on space: "
                return f"{prefix}{', '.join(low_parts)}.{other_str}"
            else:
                primary = disks[0]
                return f"None of your drives are running low on space. Drive {primary['device']} has {primary['free_gb']} GB free out of {primary['total_gb']} GB ({primary['percent']}% used)."

        # 8. Storage space query (e.g. "How much storage space do I have?")
        if any(k in clean_q for k in ("storage", "storage space", "disk space", "hard drive", "drive space", "how much storage", "how much disk", "free space")):
            disks = _get_disk_info_sync()
            if not disks:
                return "Unable to retrieve storage drive information."
            parts = [
                f"Drive {d['device']} has {d['free_gb']} GB free out of {d['total_gb']} GB ({d['percent']}% used)"
                for d in disks
            ]
            return "Storage details: " + ", and ".join(parts) + "."

        # 9. Heavy load / system load query (e.g. "Is my laptop under heavy load?")
        if any(k in clean_q for k in ("heavy load", "high load", "laptop slow", "computer slow", "under load", "under heavy load", "stressed", "working hard", "system load")):
            cpu_usage = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            mem_pct = round(mem.percent, 1)
            used_gb = round(mem.used / (1024 ** 3), 1)
            is_heavy = (cpu_usage >= 75.0) or (mem_pct >= 85.0)
            is_moderate = (cpu_usage >= 50.0) or (mem_pct >= 70.0)
            if is_heavy:
                return f"Yes, your laptop is currently under heavy load. CPU usage is at {cpu_usage}% and memory usage is at {mem_pct}% ({used_gb} GB used)."
            elif is_moderate:
                return f"Your laptop is under moderate load. CPU usage is at {cpu_usage}% and memory usage is at {mem_pct}% ({used_gb} GB used)."
            else:
                return f"No, your laptop is not under heavy load. CPU usage is at {cpu_usage}% and memory usage is at {mem_pct}% ({used_gb} GB used)."

        # 10. Public IP address query (e.g. "What is my public IP address?", "What's my external IP?")
        if any(k in clean_q for k in ("public ip", "external ip")):
            pub_ip = _get_public_ip_sync()
            if pub_ip:
                return f"Your public IP address is {pub_ip}."
            return "Unable to determine your public IP address because the internet connection is offline or unreachable."

        # 11. Local IP address query (e.g. "What is my local IP address?", "What is my internal IP?")
        if any(k in clean_q for k in ("local ip", "internal ip", "private ip")):
            loc_ip, adapter = _get_local_ip_sync()
            if loc_ip:
                adapter_str = f" on {adapter}" if adapter else ""
                return f"Your local IP address is {loc_ip}{adapter_str}."
            return "No active local IP address found. You appear to be disconnected from the local network."

        # 12. General IP query (e.g. "What is my IP address?", "What's my IP?")
        if any(k in clean_q for k in ("what is my ip", "what's my ip", "my ip address", "my ip")):
            pub_ip = _get_public_ip_sync()
            loc_ip, adapter = _get_local_ip_sync()
            if pub_ip and loc_ip:
                adapter_str = f" ({adapter})" if adapter else ""
                return f"Your public IP address is {pub_ip}, and your local IP address is {loc_ip}{adapter_str}."
            elif pub_ip:
                return f"Your public IP address is {pub_ip}."
            elif loc_ip:
                adapter_str = f" ({adapter})" if adapter else ""
                return f"Your local IP address is {loc_ip}{adapter_str}. Internet is currently unreachable to determine your public IP."
            return "Unable to determine your IP address because you are currently disconnected from the network."

        # 13. Wi-Fi network / SSID query (e.g. "What Wi-Fi network am I connected to?", "What is my SSID?")
        if any(k in clean_q for k in ("wifi network", "wi-fi network", "what wifi", "what wi-fi", "which wifi", "which wi-fi", "ssid", "wifi am i on", "wi-fi am i on", "connected to wifi", "connected to wi-fi", "wifi name", "wi-fi name")):
            wifi = _get_wifi_details_sync()
            if wifi.get("state") == "connected" and wifi.get("ssid"):
                signal_str = f" with {wifi['signal']} signal strength" if wifi.get("signal") else ""
                return f"You are connected to the Wi-Fi network '{wifi['ssid']}'{signal_str}."
            else:
                loc_ip, adapter = _get_local_ip_sync()
                if loc_ip and adapter and "ethernet" in adapter.lower():
                    return f"You are not connected to Wi-Fi; you are connected via Ethernet on {adapter} (IP: {loc_ip})."
                elif loc_ip:
                    return f"You are not connected to Wi-Fi, but you have an active network connection on {adapter or 'local adapter'} ({loc_ip})."
                return "You are not currently connected to any Wi-Fi network."

        # 14. Ping / Latency query (e.g. "What is my ping?", "What is my latency?")
        if any(k in clean_q for k in ("ping", "latency", "what is my ping", "what's my ping", "round trip time")) and not any(k in clean_q for k in ("status", "health", "system", "info")):
            is_online, latency = _measure_ping_sync()
            if is_online and latency is not None:
                lat_display = int(latency) if latency.is_integer() else latency
                return f"Your current ping to Cloudflare DNS is {lat_display} ms."
            return "Unable to measure ping because the network is currently unreachable."

        # 15. Connection stability query (e.g. "Is my internet connection stable?")
        if any(k in clean_q for k in ("stable", "stability", "connection stable", "internet stable", "is my connection")):
            is_online, latency = _measure_ping_sync()
            if not is_online or latency is None:
                return "Your internet connection is currently offline or unreachable."
            lat_display = int(latency) if latency.is_integer() else latency
            if latency <= 50:
                return f"Yes, your internet connection is very stable with an average latency of {lat_display} ms."
            elif latency <= 120:
                return f"Your internet connection is stable with a moderate latency of {lat_display} ms."
            else:
                return f"Your internet connection is experiencing high latency ({lat_display} ms), which may cause instability."

        # 16. Data usage / Uploaded / Downloaded query (e.g. "How much data have I uploaded/downloaded?")
        if any(k in clean_q for k in ("uploaded", "downloaded", "data usage", "bandwidth", "data have i used", "network usage", "data consumed", "how much data")):
            sent, recv = _get_network_io_sync()
            sent_str = _format_mem_bytes(sent)
            recv_str = _format_mem_bytes(recv)
            return f"Since last system boot, you have uploaded {sent_str} and downloaded {recv_str} of data."

        # 17. Connected to internet query (e.g. "Am I connected to the internet?", "Are we online?")
        if any(k in clean_q for k in ("connected to the internet", "connected to internet", "am i connected", "have internet", "is internet working", "are we online", "is the internet working", "do i have internet", "internet connection", "online")) and not any(k in clean_q for k in ("network status", "network health", "network info", "network details")):
            is_online, latency = _measure_ping_sync()
            if is_online:
                wifi = _get_wifi_details_sync()
                if wifi.get("state") == "connected" and wifi.get("ssid"):
                    medium_str = f" via Wi-Fi ('{wifi['ssid']}')"
                else:
                    loc_ip, adapter = _get_local_ip_sync()
                    if adapter and "ethernet" in adapter.lower():
                        medium_str = f" via Ethernet ({adapter})"
                    elif adapter:
                        medium_str = f" via {adapter}"
                    else:
                        medium_str = ""
                lat_display = int(latency) if (latency is not None and latency.is_integer()) else latency
                lat_str = f" with {lat_display} ms latency" if latency is not None else ""
                return f"Yes, you are connected to the internet{medium_str}{lat_str}."
            else:
                return "No, you are not connected to the internet."

        # 18. Network status / Network health / Network details (e.g. "Give me my network status.")
        if any(k in clean_q for k in ("network status", "network health", "network info", "network information", "network details", "check network", "internet status", "connection status")):
            is_online, latency = _measure_ping_sync()
            wifi = _get_wifi_details_sync()
            loc_ip, adapter = _get_local_ip_sync()

            if not is_online and not loc_ip:
                return "You are currently disconnected from the network and offline."

            if is_online:
                lat_display = int(latency) if (latency is not None and latency.is_integer()) else latency
                lat_str = f" with {lat_display} ms ping" if latency is not None else ""
                if wifi.get("state") == "connected" and wifi.get("ssid"):
                    sig_str = f" at {wifi['signal']} signal" if wifi.get("signal") else ""
                    net_desc = f"Wi-Fi ('{wifi['ssid']}'{sig_str})"
                elif adapter and "ethernet" in adapter.lower():
                    net_desc = f"Ethernet ({adapter})"
                else:
                    net_desc = adapter or "local network"
                ip_str = f" Your local IP is {loc_ip}." if loc_ip else ""
                return f"You are connected to the internet via {net_desc}{lat_str}.{ip_str}"
            else:
                return f"You are connected to local network adapter '{adapter}' (IP: {loc_ip}), but the internet is currently unreachable."

        # 19. Volume level query (e.g. "What is my volume level?", "What is the volume?")
        if any(k in clean_q for k in ("volume level", "what is my volume", "what is the volume", "how loud", "sound level", "current volume")) and not any(k in clean_q for k in ("status", "devices")):
            vol, is_muted, _ = _get_audio_endpoint_status_sync()
            if vol is not None:
                mute_str = "muted" if is_muted else "unmuted"
                return f"Your system volume is at {vol}% ({mute_str})."
            return "Unable to retrieve current volume level."

        # 20. Microphone availability & working status query (e.g. "Is my microphone available/working?")
        if any(k in clean_q for k in ("microphone available", "microphone working", "is my microphone", "is my mic", "mic working", "mic available", "microphone status", "mic status", "check microphone")):
            audio_devs = _get_audio_devices_sync()
            _, _, mic_muted = _get_audio_endpoint_status_sync()
            if audio_devs["mic_available"] and audio_devs["input_device"]:
                mic_name = audio_devs["input_device"]
                if audio_devs["mic_working"]:
                    mute_str = " (currently muted)" if mic_muted else " and unmuted"
                    return f"Yes, your microphone '{mic_name}' is available, working normally{mute_str}."
                else:
                    return f"Your microphone '{mic_name}' is detected, but encountered an error initializing audio input settings."
            return "No active microphone was detected on this system."

        # 21. Camera availability query (e.g. "Is my camera available?", "Is my webcam working?")
        if any(k in clean_q for k in ("camera available", "camera working", "is my camera", "is my webcam", "webcam available", "webcam working", "camera status", "webcam status", "check camera")):
            cam = _get_camera_status_sync()
            if cam["available"] and cam["name"]:
                return f"Yes, your camera '{cam['name']}' is available and working normally."
            elif cam["name"]:
                return f"Your camera '{cam['name']}' was found, but status reports '{cam['status']}'."
            return "No active camera or webcam was detected on this device."

        # 22. Audio device query (e.g. "What audio device am I using?", "What speaker am I using?")
        if any(k in clean_q for k in ("what audio device", "which audio device", "what speaker", "audio device am i using", "what audio device am i using", "current audio device", "audio devices am i using")) and not any(k in clean_q for k in ("audio status", "sound status")):
            audio_devs = _get_audio_devices_sync()
            out_dev = audio_devs.get("output_device")
            in_dev = audio_devs.get("input_device")
            if out_dev and in_dev:
                return f"You are using '{out_dev}' for audio output and '{in_dev}' for microphone input."
            elif out_dev:
                return f"You are using '{out_dev}' for audio output. No active microphone input device is configured."
            return "Unable to determine your active audio devices."

        # 23. Audio / Device status summary (e.g. "Give me my audio status.", "Check audio devices")
        if any(k in clean_q for k in ("audio status", "audio health", "sound status", "device status", "check audio devices", "check audio")):
            audio_devs = _get_audio_devices_sync()
            vol, is_muted, mic_muted = _get_audio_endpoint_status_sync()
            out_dev = audio_devs.get("output_device") or "Default Speaker"
            in_dev = audio_devs.get("input_device") or "Default Microphone"
            vol_str = f" at {vol}% ({'muted' if is_muted else 'unmuted'})" if vol is not None else ""
            mic_mute_str = "muted" if mic_muted else "unmuted"
            return f"Audio output is set to '{out_dev}'{vol_str}. Microphone input is '{in_dev}' ({mic_mute_str})."

        # 10. General system status / health / specifications (Default)
        os_name = f"{platform.system()} {platform.release()}"
        cpu_usage = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        mem_pct = round(mem.percent, 1)
        used_gb = round(mem.used / (1024 ** 3), 1)
        total_gb = round(mem.total / (1024 ** 3), 1)

        batt = psutil.sensors_battery()
        if batt:
            charging_str = "charging" if batt.power_plugged else "on battery power"
            batt_str = f"battery is at {batt.percent}% ({charging_str})"
        else:
            batt_str = "running on AC power"

        disks = _get_disk_info_sync()
        disk_str = f", Drive {disks[0]['device']} has {disks[0]['free_gb']} GB free" if disks else ""

        return f"Running {os_name} with CPU usage at {cpu_usage}%, memory usage at {mem_pct}% ({used_gb} of {total_gb} GB used){disk_str}, and {batt_str}."
    except Exception as e:
        return f"Could not retrieve complete system info: {e}"


async def get_system_info(query: Optional[str] = None) -> str:
    """Returns real-time CPU, RAM, battery, storage, health, network connectivity, and device/audio status."""
    return await asyncio.to_thread(_get_system_info_sync, query)


async def get_current_time() -> str:
    """Returns the current formatted time."""
    now_str = datetime.datetime.now().strftime("%I:%M %p").lstrip("0")
    return f"The current time is {now_str}."


async def get_current_date() -> str:
    """Returns the current formatted date."""
    date_str = datetime.datetime.now().strftime("%A, %B %d, %Y")
    return f"Today is {date_str}."


# ---------------------------------------------------------
# Application, Folder & File Actions
# ---------------------------------------------------------

def _extract_app_name(text: str) -> str:
    """Extracts application name from command text."""
    cleaned = re.sub(
        r"^(?:(?:can\s+you|could\s+you|would\s+you|please|kindly|nexa)\s+)*(?:open|launch|start|run)\s+(?:the\s+)?",
        "",
        text.strip(),
        flags=re.IGNORECASE
    )
    cleaned = re.sub(r"\s+(?:app|application)$", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned.lower()


def _launch_application_sync(app_name: str) -> bool:
    """Finds and launches an application executable or shortcut safely without shell interpretation."""
    clean_name = app_name.strip()
    if not clean_name:
        return False

    name_lower = clean_name.lower()
    target = COMMON_APPS.get(name_lower)

    # 1. If target is in known allowlist / alias map (e.g. 'calc', 'chrome', 'ms-settings:')
    if target:
        try:
            os.startfile(target)
            return True
        except Exception:
            pass

        # If it's a known URI protocol that failed to open, do not search disk
        if target.endswith(":"):
            return False

    # 2. Check if clean_name is an explicit existing file path (e.g. 'C:\Program Files\App\app.exe')
    try:
        direct_path = Path(clean_name)
        if direct_path.is_file():
            try:
                os.startfile(str(direct_path))
                return True
            except Exception:
                pass
    except (OSError, ValueError):
        pass

    # 3. Check local programs directories (e.g. Obsidian, VS Code, Discord)
    search_names = [name_lower]
    if target and target.lower() != name_lower:
        search_names.insert(0, target.lower())

    for s_name in search_names:
        local_candidates = [
            Path.home() / "AppData" / "Local" / "Programs" / s_name / f"{s_name}.exe",
            Path.home() / "AppData" / "Local" / s_name / f"{s_name}.exe",
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / s_name / f"{s_name}.exe",
            Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / s_name / f"{s_name}.exe",
        ]
        for cand in local_candidates:
            try:
                if cand.is_file():
                    try:
                        os.startfile(str(cand))
                        return True
                    except Exception:
                        pass
            except (OSError, ValueError):
                continue

    # 4. Search Windows Start Menu shortcuts (.lnk)
    start_menu_dirs = [
        Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "Microsoft\\Windows\\Start Menu\\Programs",
        Path.home() / "AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs",
    ]
    for menu_dir in start_menu_dirs:
        try:
            if not menu_dir.exists():
                continue
            for lnk_path in menu_dir.rglob("*.lnk"):
                try:
                    stem_low = lnk_path.stem.lower()
                    if any(s_name in stem_low for s_name in search_names):
                        try:
                            os.startfile(str(lnk_path))
                            return True
                        except Exception:
                            continue
                except (OSError, ValueError):
                    continue
        except (OSError, ValueError):
            continue

    # 5. Check system PATH via safe which resolution
    for s_name in search_names:
        try:
            which_cand = shutil.which(s_name) or shutil.which(f"{s_name}.exe")
            if which_cand:
                which_path = Path(which_cand)
                if which_path.is_file():
                    try:
                        os.startfile(str(which_path))
                        return True
                    except Exception:
                        pass
        except (OSError, ValueError):
            continue

    # 6. Fail closed: Unresolved or unsafe target is never executed
    return False




async def open_application(text: str) -> str:
    """Extracts and launches the specified application."""
    app_name = _extract_app_name(text)
    if not app_name:
        return "Please specify which application you would like to open."
    success = await asyncio.to_thread(_launch_application_sync, app_name)
    if success:
        return f"Opened {app_name}."
    return f"Could not find or launch application '{app_name}'."


def _extract_close_app_name(text: str) -> str:
    """Extracts target application name from a close/exit command text."""
    cleaned = re.sub(
        r"^(?:(?:can\s+you|could\s+you|would\s+you|please|kindly|nexa)\s+)*(?:close|exit|quit|terminate|kill|shut down)\s+(?:the\s+)?",
        "",
        text.strip(),
        flags=re.IGNORECASE
    )
    cleaned = re.sub(r"^(?:all\s+instances\s+of|all\s+|every\s+instance\s+of)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+(?:app|application|window|process|processes|instances|instance)$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\ball\b\s*", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned.lower()


def _close_application_sync(app_name: str, dry_run: bool = False) -> str:
    """
    Terminates running instances of the specified application safely.
    Checks simulation/dry-run mode and critical process blocklist.
    """
    import psutil

    raw_name = app_name.strip()
    if not raw_name:
        return "Please specify which application you would like to close."

    clean_name = _extract_close_app_name(raw_name) if any(
        raw_name.lower().startswith(p) for p in ("close ", "exit ", "quit ", "terminate ", "kill ")
    ) else raw_name.lower()

    if not clean_name:
        return "Please specify which application you would like to close."

    # Determine target executable names
    target_executables: List[str] = []
    if clean_name in APP_PROCESS_MAP:
        target_executables = APP_PROCESS_MAP[clean_name]
    elif clean_name.endswith(".exe"):
        target_executables = [clean_name]
    else:
        candidate = f"{clean_name}.exe"
        target_executables = [candidate]

    # Validate against critical system processes
    for target in target_executables:
        if target.lower() in CRITICAL_SYSTEM_PROCESSES or clean_name in CRITICAL_SYSTEM_PROCESSES:
            return f"Refused to terminate '{app_name}': '{target}' is a protected Windows system process."

    is_sim = _is_safe_simulation_mode(dry_run)

    matched_procs: List[Any] = []
    matched_pids: List[int] = []

    target_set = {t.lower() for t in target_executables}
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            p_name = proc.info.get('name')
            if p_name and p_name.lower() in target_set:
                matched_procs.append(proc)
                matched_pids.append(proc.info['pid'])
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    display_name = clean_name.title() if len(clean_name) > 3 else clean_name.upper()
    if clean_name in ("vscode", "vs code", "code"):
        display_name = "VS Code"
    elif clean_name in ("chrome", "google chrome"):
        display_name = "Chrome"

    if not matched_procs:
        return f"'{display_name}' is not currently running."

    if is_sim:
        return (
            f"[DRY-RUN] Found {len(matched_pids)} running process(es) for '{display_name}' "
            f"(PIDs: {matched_pids}). Process termination was not executed because test/dry-run mode is active."
        )

    # Real termination: attempt graceful terminate first, then kill if needed
    terminated_count = 0
    for proc in matched_procs:
        try:
            proc.terminate()
            terminated_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Wait up to 3 seconds for graceful exit
    gone, alive = psutil.wait_procs(matched_procs, timeout=3.0)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return f"Closed {display_name} (terminated {terminated_count} process(es))."


async def close_application_action(app_name: str, dry_run: bool = False) -> str:
    """Closes user application non-blockingly via worker thread."""
    return await asyncio.to_thread(_close_application_sync, app_name, dry_run)


# System and background service processes excluded from user-facing app listings
SYSTEM_PROCESS_NAMES = {
    "csrss.exe", "lsass.exe", "services.exe", "wininit.exe", "winlogon.exe",
    "smss.exe", "svchost.exe", "explorer.exe", "system", "system idle process",
    "registry", "runtimebroker.exe", "dwm.exe", "spoolsv.exe", "sihost.exe",
    "fontdrvhost.exe", "memcompression", "msmpeng.exe", "nissrv.exe",
    "conhost.exe", "taskhostw.exe", "dllhost.exe", "searchhost.exe",
    "startmenuexperiencehost.exe", "textinputhost.exe", "shellexperiencehost.exe",
    "ctfmon.exe", "smartscreen.exe", "securityhealthservice.exe",
    "securityhealthsystray.exe", "audiodg.exe", "wlanext.exe", "dashost.exe",
    "compattelrunner.exe", "wmiapsrv.exe", "wmiprvse.exe", "searchindexer.exe",
    "searchapp.exe", "searchfilterhost.exe", "searchprotocolhost.exe",
    "applicationframehost.exe", "sedlauncher.exe",
}

# User-friendly display names for known process executable names
PROCESS_DISPLAY_MAP = {
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "msedgewebview2.exe": "Edge WebView",
    "notepad.exe": "Notepad",
    "calculatorapp.exe": "Calculator",
    "calc.exe": "Calculator",
    "calculator.exe": "Calculator",
    "mspaint.exe": "Paint",
    "spotify.exe": "Spotify",
    "code.exe": "VS Code",
    "windowsterminal.exe": "Windows Terminal",
    "wt.exe": "Windows Terminal",
    "cmd.exe": "Command Prompt",
    "powershell.exe": "PowerShell",
    "taskmgr.exe": "Task Manager",
    "winword.exe": "Word",
    "excel.exe": "Excel",
    "powerpnt.exe": "PowerPoint",
    "whatsapp.exe": "WhatsApp",
    "whatsapp.root.exe": "WhatsApp",
    "antigravity.exe": "Antigravity",
    "discord.exe": "Discord",
    "slack.exe": "Slack",
    "zoom.exe": "Zoom",
    "teams.exe": "Microsoft Teams",
    "vlc.exe": "VLC",
    "obs64.exe": "OBS Studio",
    "obs.exe": "OBS Studio",
    "steam.exe": "Steam",
    "python.exe": "Python",
    "pythonw.exe": "Python",
}


def _format_mem_bytes(bytes_count: int) -> str:
    """Formats byte count into human-readable MB or GB string."""
    mb = bytes_count / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.1f} MB"


def _get_process_awareness_sync(
    app_name: Optional[str] = None,
    top_memory: bool = False
) -> str:
    """
    Inspects running processes safely and returns status, list of open apps, or top memory consumers.
    Read-only operation; never modifies system state.
    """
    import psutil

    # 1. Top Memory Applications
    if top_memory or (app_name and any(k in app_name.lower() for k in ("memory", "ram", "most memory", "highest memory"))):
        app_mem: Dict[str, int] = {}
        app_proc_count: Dict[str, int] = {}

        for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                p_name = (proc.info.get('name') or '').lower()
                if not p_name or p_name in SYSTEM_PROCESS_NAMES or p_name in CRITICAL_SYSTEM_PROCESSES:
                    continue
                mem_info = proc.info.get('memory_info')
                rss = mem_info.rss if mem_info else 0
                if rss < 5 * 1024 * 1024:
                    continue
                friendly = PROCESS_DISPLAY_MAP.get(p_name, p_name.replace(".exe", "").title())
                app_mem[friendly] = app_mem.get(friendly, 0) + rss
                app_proc_count[friendly] = app_proc_count.get(friendly, 0) + 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if not app_mem:
            return "No major user applications are currently consuming significant memory."

        sorted_apps = sorted(app_mem.items(), key=lambda x: x[1], reverse=True)[:5]
        lines = []
        for idx, (name, total_bytes) in enumerate(sorted_apps, 1):
            count = app_proc_count.get(name, 1)
            proc_label = f"across {count} processes" if count > 1 else "1 process"
            lines.append(f"{idx}. {name}: {_format_mem_bytes(total_bytes)} ({proc_label})")

        return "The highest-memory applications currently running are:\n" + "\n".join(lines)

    # 2. Specific Application Check (e.g. "Is Chrome running?", "How many Chrome processes...")
    if app_name and app_name.strip():
        clean_app = app_name.strip().lower()
        clean_app = re.sub(r"[?!.,]+$", "", clean_app).strip()
        for prefix in (
            "how many processes of ", "how many instances of ", "how many processes are there for ",
            "how many ", "what is the status of ", "is ", "are there any ", "are ",
            "check if ", "check ", "status of ", "find "
        ):
            if clean_app.startswith(prefix):
                clean_app = clean_app[len(prefix):].strip()
                break

        # Strip trailing process/running qualifiers
        clean_app = re.sub(r"\s+(?:processes|instances|process|instance)?\s*(?:are\s+)?(?:running|open|active|opened|started|launched)$", "", clean_app, flags=re.I).strip()
        clean_app = re.sub(r"\s+(?:processes|instances|process|instance)$", "", clean_app, flags=re.I).strip()
        clean_app = re.sub(r"\s+(?:app|application)$", "", clean_app, flags=re.I).strip()
        clean_app = re.sub(r"[?!.,]+$", "", clean_app).strip()

        # Determine target executables
        target_executables: List[str] = []
        if clean_app in APP_PROCESS_MAP:
            target_executables = APP_PROCESS_MAP[clean_app]
        elif clean_app.endswith(".exe"):
            target_executables = [clean_app]
        else:
            target_executables = [f"{clean_app}.exe"]

        target_set = {t.lower() for t in target_executables}
        display_name = clean_app.title() if len(clean_app) > 3 else clean_app.upper()
        if clean_app in ("vscode", "vs code", "code"):
            display_name = "VS Code"
        elif clean_app in ("chrome", "google chrome"):
            display_name = "Chrome"

        matching_pids: List[int] = []
        total_rss = 0
        for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                p_name = proc.info.get('name')
                if p_name and p_name.lower() in target_set:
                    matching_pids.append(proc.info['pid'])
                    mem_info = proc.info.get('memory_info')
                    if mem_info:
                        total_rss += mem_info.rss
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        count = len(matching_pids)
        if count == 0:
            return f"No, {display_name} is not currently running."
        elif count == 1:
            return f"Yes, {display_name} is currently running (1 process, using {_format_mem_bytes(total_rss)} of RAM)."
        else:
            return f"Yes, {display_name} is currently running with {count} processes (using {_format_mem_bytes(total_rss)} of RAM)."

    # 3. List Open User Applications (e.g. "What apps are open?")
    running_user_apps: Dict[str, int] = {}
    for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
        try:
            p_name = (proc.info.get('name') or '').lower()
            if not p_name or p_name in SYSTEM_PROCESS_NAMES or p_name in CRITICAL_SYSTEM_PROCESSES:
                continue
            if any(k in p_name for k in ('service', 'helper', 'host', 'cap.exe', 'container', 'analytics', 'driver', 'agent')):
                continue
            if p_name in PROCESS_DISPLAY_MAP:
                friendly = PROCESS_DISPLAY_MAP[p_name]
                running_user_apps[friendly] = running_user_apps.get(friendly, 0) + 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if not running_user_apps:
        return "There are currently no major user applications running."

    app_items = []
    for name, count in sorted(running_user_apps.items(), key=lambda x: x[1], reverse=True):
        label = f"{name} ({count} processes)" if count > 1 else f"{name} (1 process)"
        app_items.append(label)

    return f"The following user applications are currently running: {', '.join(app_items)}."


async def inspect_applications_action(
    app_name: Optional[str] = None,
    top_memory: bool = False
) -> str:
    """Non-blocking process awareness action executed via worker thread."""
    return await asyncio.to_thread(_get_process_awareness_sync, app_name, top_memory)


def _extract_folder_name(text: str) -> str:
    """Extracts folder name from command text."""
    cleaned = re.sub(
        r"^(?:(?:can\s+you|could\s+you|would\s+you|please|kindly|nexa)\s+)*(?:open|show|access)\s+(?:the\s+|my\s+)?",
        "",
        text.strip(),
        flags=re.IGNORECASE
    )
    cleaned = re.sub(r"\s+(?:folder|directory)$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^(?:the|my)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned.lower()



def _open_folder_sync(folder_name: str) -> Tuple[bool, str]:
    """Finds and opens a folder in Windows Explorer."""
    # Check common known folders
    if folder_name in COMMON_FOLDERS:
        folder_path = COMMON_FOLDERS[folder_name]
        if folder_path.exists():
            os.startfile(str(folder_path))
            return True, str(folder_path)

    # Check directly under user home
    user_sub = Path.home() / folder_name
    if user_sub.exists() and user_sub.is_dir():
        os.startfile(str(user_sub))
        return True, str(user_sub)

    return False, ""


async def open_folder(text: str) -> str:
    """Extracts and opens the requested Windows folder."""
    folder_name = _extract_folder_name(text)
    if not folder_name:
        folder_name = "downloads"
    success, path = await asyncio.to_thread(_open_folder_sync, folder_name)
    if success:
        return f"Opened {folder_name} folder."
    return f"Folder '{folder_name}' not found."


def _extract_file_name(text: str) -> str:
    """Extracts target file name or search phrase from command text."""
    # Strip leading polite prefixes and action verbs
    cleaned = re.sub(
        r"^(?:(?:can\s+you|could\s+you|would\s+you|please|kindly|nexa)\s+)*(?:find|search for|look for|locate|open|show|access|view|read)\s+",
        "",
        text.strip(),
        flags=re.IGNORECASE
    ).strip()

    # Strip conversational descriptors like "the file called", "the document named", etc.
    cleaned = re.sub(
        r"^(?:the\s+file\s+called|the\s+file\s+named|the\s+document\s+called|the\s+document\s+named|file\s+called|file\s+named|document\s+called|document\s+named)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE
    ).strip()

    # Strip leading determiners/possessives
    cleaned = re.sub(
        r"^(?:the\s+|my\s+|that\s+|this\s+|a\s+|an\s+)",
        "",
        cleaned,
        flags=re.IGNORECASE
    ).strip()

    # Normalize trailing format keywords like "resume pdf" -> "resume.pdf"
    cleaned = re.sub(
        r"\s+(pdf|docx?|txt|csv|xlsx?|json|py|md|png|jpe?g)$",
        r".\1",
        cleaned,
        flags=re.IGNORECASE
    ).strip()

    # Strip trailing descriptive nouns like "file", "document", "doc"
    cleaned = re.sub(
        r"\s+(?:file|document|doc)$",
        "",
        cleaned,
        flags=re.IGNORECASE
    ).strip()

    return cleaned


def _find_files_sync(filename: str, max_depth: int = 3) -> List[str]:
    """Fast, ranked, synonym-aware search for a file in Desktop, Documents, and Downloads up to max_depth."""
    search_dirs = [
        Path.home() / "Downloads",
        Path.home() / "Documents",
        Path.home() / "Desktop",
    ]
    query = filename.strip()
    if not query:
        return []

    # Check if an extension is requested
    target_ext = None
    query_base = query
    m_ext = re.search(r"\.([a-zA-Z0-9]+)$", query)
    if m_ext:
        target_ext = f".{m_ext.group(1).lower()}"
        query_base = query[:m_ext.start()].strip()

    # Synonyms dictionary
    SYNONYMS = {
        "cv": {"cv", "resume", "curriculum vitae"},
        "resume": {"resume", "cv", "curriculum vitae"},
    }

    # Tokenize query_base
    raw_tokens = [t.lower() for t in re.split(r"[\s_\-]+", query_base) if t.strip()]
    if not raw_tokens and target_ext:
        raw_tokens = [target_ext.lstrip(".")]

    # Build token synonym variants
    token_synonym_groups: List[set] = []
    for token in raw_tokens:
        if token in SYNONYMS:
            token_synonym_groups.append(SYNONYMS[token])
        else:
            token_synonym_groups.append({token})

    scored_candidates: List[Tuple[float, float, str]] = []

    for base in search_dirs:
        if not base.exists():
            continue
        base_depth = len(base.parts)
        for root, dirs, files in os.walk(base):
            if len(Path(root).parts) - base_depth > max_depth:
                dirs.clear()
                continue
            for f in files:
                f_path = Path(root) / f
                stem_lower = f_path.stem.lower()
                ext_lower = f_path.suffix.lower()
                full_lower = f.lower()

                # Check if every token matches (either directly or via synonym)
                all_matched = True
                for syn_group in token_synonym_groups:
                    if not any(syn in full_lower or syn in stem_lower for syn in syn_group):
                        all_matched = False
                        break

                if not all_matched:
                    continue

                # Calculate score
                score = 0.0

                # Target extension matching
                if target_ext:
                    if ext_lower == target_ext:
                        score += 50.0
                    else:
                        score -= 20.0
                elif ext_lower in (".pdf", ".docx", ".txt", ".xlsx"):
                    score += 5.0

                # Exact stem match
                if stem_lower == query_base.lower():
                    score += 100.0
                elif query_base.lower() in stem_lower:
                    score += 40.0

                # Shorter stem bonus (closer match to target term)
                score += max(0.0, 30.0 - abs(len(stem_lower) - len(query_base)))

                # User personalization bonus: if "resume" or "cv" is in query and file contains "venkatesh"
                if any(k in query_base.lower() for k in ("resume", "cv")):
                    if "venkatesh" in stem_lower:
                        score += 35.0
                    elif "radhika" in stem_lower and "venkatesh" not in query_base.lower():
                        score -= 10.0

                try:
                    mtime = f_path.stat().st_mtime
                except Exception:
                    mtime = 0.0

                scored_candidates.append((score, mtime, str(f_path)))

    # Sort descending by score, then by recency (mtime)
    scored_candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [c[2] for c in scored_candidates]


async def find_file(text: str) -> str:
    """Searches for a file matching query in common user directories."""
    filename = _extract_file_name(text)
    if not filename:
        return "Please specify the name of the file to find."
    matches = await asyncio.to_thread(_find_files_sync, filename)
    if matches:
        return f"Found file at: {matches[0]}"
    return f"Could not find file '{filename}'."


async def open_file(text: str) -> str:
    """Finds and opens a file using its default system application."""
    filename = _extract_file_name(text)
    if not filename:
        return "Please specify which file you would like to open."

    # Direct path check
    direct_path = Path(filename)
    if direct_path.exists() and direct_path.is_file():
        success = await asyncio.to_thread(_open_uri_sync, str(direct_path))
        if success:
            return f"Opened {direct_path.name}."

    # Search for matching file
    matches = await asyncio.to_thread(_find_files_sync, filename)
    if matches:
        first_match = matches[0]
        success = await asyncio.to_thread(_open_uri_sync, first_match)
        if success:
            return f"Opened {Path(first_match).name}."
    return f"Could not find file '{filename}' to open."


# ---------------------------------------------------------
# ---------------------------------------------------------
# Browser Context, Search & Browser Controller
# ---------------------------------------------------------

_BROWSER_CONTEXT: Optional[Dict[str, Any]] = None


def get_browser_context() -> Optional[Dict[str, Any]]:
    """Returns the active browser context dictionary."""
    return _BROWSER_CONTEXT


def set_browser_context(context_dict: Dict[str, Any]) -> None:
    """Sets the active browser context dictionary."""
    global _BROWSER_CONTEXT
    _BROWSER_CONTEXT = context_dict


def clear_browser_context() -> None:
    """Clears the active browser context."""
    global _BROWSER_CONTEXT
    _BROWSER_CONTEXT = None


def _find_chrome_executable() -> Optional[str]:
    """Locates the Google Chrome executable on Windows."""
    import shutil
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        shutil.which("chrome"),
        shutil.which("google-chrome"),
    ]
    return next((p for p in candidates if p and os.path.exists(p)), None)


def _find_browser_window_hwnd() -> Optional[int]:
    """Finds the window handle for active Chrome or default browser window on Windows."""
    try:
        import win32gui
        import win32process
        import psutil

        browser_exes = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"}
        found_hwnd = None

        def enum_cb(hwnd, extra):
            nonlocal found_hwnd
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        proc = psutil.Process(pid)
                        name = proc.name().lower()
                        if name in browser_exes:
                            if name == "chrome.exe":
                                found_hwnd = hwnd
                                return False  # Stop enumeration once Chrome is found
                            if found_hwnd is None:
                                found_hwnd = hwnd
                    except Exception:
                        pass
            return True

        try:
            win32gui.EnumWindows(enum_cb, None)
        except Exception:
            pass

        return found_hwnd
    except Exception as e:
        logging.warning(f"Error finding browser window hwnd: {e}")
        return None


def _send_browser_key(action: str) -> bool:
    """Sends keystrokes to the browser window safely on Windows."""
    try:
        import win32gui
        import win32con
        import win32process
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = _find_browser_window_hwnd()
        if not hwnd:
            logging.warning(f"No browser window found for action '{action}'")
            return False

        try:
            # Safely bring browser window to the foreground
            foreground_hwnd = win32gui.GetForegroundWindow()
            if foreground_hwnd != hwnd:
                fg_tid = win32process.GetWindowThreadProcessId(foreground_hwnd)[0]
                cur_tid = kernel32.GetCurrentThreadId()
                user32.AttachThreadInput(cur_tid, fg_tid, True)
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                user32.AttachThreadInput(cur_tid, fg_tid, False)
                time.sleep(0.08)
        except Exception as win_err:
            logging.debug(f"Could not focus browser window: {win_err}")

        VK_MENU = 0x12       # Alt
        VK_LEFT = 0x25       # Left Arrow
        VK_RIGHT = 0x27      # Right Arrow
        VK_UP = 0x26         # Up Arrow
        VK_DOWN = 0x28       # Down Arrow
        VK_PRIOR = 0x21      # Page Up
        VK_NEXT = 0x22       # Page Down
        VK_HOME = 0x24       # Home
        VK_END = 0x23        # End
        VK_F5 = 0x74         # F5
        KEYEVENTF_KEYUP = 0x0002

        def press_key(vk: int):
            user32.keybd_event(vk, 0, 0, 0)
            time.sleep(0.03)
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

        def press_combo(mod: int, vk: int):
            user32.keybd_event(mod, 0, 0, 0)
            time.sleep(0.02)
            user32.keybd_event(vk, 0, 0, 0)
            time.sleep(0.04)
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.02)
            user32.keybd_event(mod, 0, KEYEVENTF_KEYUP, 0)

        if action in ("scroll_down", "go_down"):
            press_key(VK_NEXT)
        elif action == "scroll_down_little":
            for _ in range(4):
                press_key(VK_DOWN)
                time.sleep(0.02)
        elif action == "scroll_down_more":
            press_key(VK_NEXT)
            time.sleep(0.05)
            press_key(VK_NEXT)
        elif action in ("scroll_up", "go_up"):
            press_key(VK_PRIOR)
        elif action == "scroll_up_little":
            for _ in range(4):
                press_key(VK_UP)
                time.sleep(0.02)
        elif action == "scroll_up_more":
            press_key(VK_PRIOR)
            time.sleep(0.05)
            press_key(VK_PRIOR)
        elif action == "go_top":
            press_key(VK_HOME)
        elif action == "go_bottom":
            press_key(VK_END)
        elif action == "go_back":
            press_combo(VK_MENU, VK_LEFT)
        elif action == "go_forward":
            press_combo(VK_MENU, VK_RIGHT)
        elif action == "refresh":
            press_key(VK_F5)
        return True
    except Exception as e:
        logging.error(f"Error sending browser key for action '{action}': {e}")
        return False


def _normalize_browser_command(text: str) -> str:
    """Normalizes natural language browser navigation and selection commands."""
    try:
        from backend.ml.normalizer import strip_carrier_prefixes
        clean = strip_carrier_prefixes(text)
    except Exception:
        clean = text
    clean = clean.lower().strip()
    # Strip any leading wake words or polite carrier prefixes
    clean = re.sub(r"^(?:(?:hey|hi|hello|ok|okay)?\s*nexa\b\s*[,:]?\s*)+", "", clean, flags=re.IGNORECASE).strip()
    clean = re.sub(
        r"^(?:(?:can\s+you\s+please|could\s+you\s+please|would\s+you\s+please|would\s+you\s+mind|can\s+you|could\s+you|would\s+you|please\s+could\s+you|please|kindly|okay|ok)\s+)+",
        "",
        clean,
        flags=re.IGNORECASE
    ).strip()
    clean = re.sub(r"[^\w\s]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _extract_search_query(text: str) -> str:
    """Normalizes natural language web search queries and extracts only the actual search term."""
    cleaned = text.strip()
    cleaned = re.sub(r"^(?:(?:hey|hi|hello|ok|okay)?\s*nexa\b\s*[,:]?\s*)+", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(
        r"^(?:(?:can\s+you\s+please|could\s+you\s+please|would\s+you\s+please|would\s+you\s+mind|can\s+you|could\s+you|would\s+you|please|kindly)\s+)+",
        "",
        cleaned,
        flags=re.IGNORECASE
    ).strip()
    cleaned = re.sub(
        r"^(?:search(?:\s+the\s+web)?(?:\s+for)?|google(?:\s+for)?|look\s+up|find)(?:\s+|$)",
        "",
        cleaned,
        flags=re.IGNORECASE
    ).strip()
    cleaned = re.sub(
        r"\s+(?:online|on\s+the\s+web|on\s+google|on\s+the\s+internet|on\s+internet)$",
        "",
        cleaned,
        flags=re.IGNORECASE
    ).strip()
    # Strip trailing punctuation
    cleaned = re.sub(r"[.!,?]+$", "", cleaned).strip()
    return cleaned


def _is_explicit_web_search(clean_low: str) -> bool:
    """Determines whether text input is an explicit web search command."""
    clean = _normalize_browser_command(clean_low)

    # Confusion guard: Do not treat local disk/file search commands as web searches
    if any(clean.startswith(p) for p in (
        "search disk", "search drive", "search pc", "search computer",
        "search my files", "search files", "search file", "find file", "find my file",
        "locate file", "locate my file"
    )):
        return False

    # Confusion guard: navigation and result selection
    if _extract_browser_nav_action(clean_low) is not None:
        return False
    if _extract_browser_result_index(clean_low) is not None:
        return False

    search_prefixes = (
        "search the web for ", "search web for ", "search for ", "search ",
        "google for ", "google ", "look up ", "browse for ", "browse "
    )
    if any(clean.startswith(p) or clean == p.strip() for p in search_prefixes):
        return True

    if clean.startswith("find ") and any(clean.endswith(suf) for suf in (" online", " on the web", " on google", " on internet")):
        return True

    return False


def _extract_browser_result_index(text: str) -> Optional[int]:
    """Extracts 1-based index from result selection phrases (e.g. 'open the first link', 'the first one', 'click the first result')."""
    clean = _normalize_browser_command(text)
    ordinals = {
        "first": 1, "1st": 1, "one": 1,
        "second": 2, "2nd": 2, "two": 2,
        "third": 3, "3rd": 3, "three": 3,
        "fourth": 4, "4th": 4, "four": 4,
        "fifth": 5, "5th": 5, "five": 5,
    }

    # Pattern 1: (open|click|view|select|go to) (the)? (first|1st|second...) (link|result|one|item|website|page|video)
    m = re.search(r"\b(?:open\s+|click\s+|view\s+|select\s+|go\s+to\s+)?(?:the\s+)?(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th)\s+(?:link|result|one|item|website|page|video|option)\b", clean)
    if m:
        return ordinals.get(m.group(1))

    # Pattern 2: (open|click|select)? (the)? (first|second|third...)
    m = re.search(r"^(?:open\s+|click\s+|select\s+)?(?:the\s+)?(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th)$", clean)
    if m:
        return ordinals.get(m.group(1))

    # Pattern 3: (open|click|select)? result/link/option/number (1-5|one-five)
    m = re.search(r"\b(?:open\s+|click\s+|select\s+)?(?:result|link|option|number|video)\s+(?:number\s+|#\s*)?([1-5]|one|two|three|four|five)\b", clean)
    if m:
        val = m.group(1)
        return int(val) if val.isdigit() else ordinals.get(val)

    # Pattern 4: the (first|second|...) one
    m = re.search(r"^the\s+(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)\s+one$", clean)
    if m:
        return ordinals.get(m.group(1))

    # Pattern 5: exact short phrases
    if clean in ("the first one", "first one", "first link", "first result", "first video"):
        return 1
    if clean in ("the second one", "second one", "second link", "second result", "second video"):
        return 2
    if clean in ("the third one", "third one", "third link", "third result", "third video"):
        return 3
    if clean in ("the fourth one", "fourth one", "fourth link", "fourth result"):
        return 4
    if clean in ("the fifth one", "fifth one", "fifth link", "fifth result"):
        return 5

    return None


def _extract_browser_nav_action(text: str) -> Optional[str]:
    """Identifies browser scrolling and navigation commands."""
    clean = _normalize_browser_command(text)

    # Scrolling down
    if clean in (
        "scroll down a little", "scroll down a bit", "scroll a little down", "scroll a bit down",
        "go down a bit", "go down a little", "down a little", "down a bit", "scroll down slightly"
    ):
        return "scroll_down_little"
    if clean in ("scroll down more", "scroll more down", "go down more", "down more"):
        return "scroll_down_more"
    if clean in ("scroll down", "go down", "page down", "move down", "scroll down page"):
        return "scroll_down"

    # Scrolling up
    if clean in (
        "scroll up a little", "scroll up a bit", "scroll a little up", "scroll a bit up",
        "go up a bit", "go up a little", "up a little", "up a bit", "scroll up slightly"
    ):
        return "scroll_up_little"
    if clean in ("scroll up more", "scroll more up", "go up more", "up more"):
        return "scroll_up_more"
    if clean in ("scroll up", "go up", "page up", "move up", "scroll up page"):
        return "scroll_up"

    # Top / Bottom
    if clean in ("go to the top", "go to top", "scroll to top", "top of the page", "top of page", "scroll top"):
        return "go_top"
    if clean in ("go to the bottom", "go to bottom", "scroll to bottom", "bottom of the page", "bottom of page", "scroll bottom"):
        return "go_bottom"

    # History Navigation
    if clean in ("go back", "navigate back", "back page", "previous page", "browser back", "back"):
        return "go_back"
    if clean in ("go forward", "navigate forward", "forward page", "next page", "browser forward", "forward"):
        return "go_forward"

    # Reload / Refresh
    if clean in ("refresh the page", "refresh page", "refresh", "reload the page", "reload page", "reload"):
        return "refresh"

    return None


async def execute_web_search(text: str, context: Optional[Any] = None, dry_run: bool = False) -> str:
    """
    Executes live web search in Chrome (or default browser),
    populates in-memory _BROWSER_CONTEXT with top results for follow-up
    link/result selection, and returns a concise user confirmation.
    """
    global _BROWSER_CONTEXT
    import urllib.parse
    import webbrowser

    query = _extract_search_query(text)
    if not query:
        return "Please specify what you would like me to search for."

    clean_q = query.strip()
    # Check if query is explicitly directed at YouTube
    is_yt = bool(re.search(r"\b(?:youtube|video|videos)\b", clean_q, re.I))
    if re.search(r"^(?:on\s+)?youtube(?:\s+for)?\b", clean_q, re.I):
        yt_query = re.sub(r"^(?:on\s+)?youtube(?:\s+for)?\s*", "", clean_q, flags=re.I).strip()
        encoded = urllib.parse.quote(yt_query or clean_q)
        search_url = f"https://www.youtube.com/results?search_query={encoded}"
    else:
        encoded = urllib.parse.quote(clean_q)
        search_url = f"https://www.google.com/search?q={encoded}"

    browser_name = "Chrome"

    # Launch browser visibly
    if not dry_run:
        chrome_exe = _find_chrome_executable()
        try:
            if chrome_exe:
                subprocess.Popen([chrome_exe, search_url])
                browser_name = "Chrome"
            else:
                webbrowser.open(search_url)
                browser_name = "browser"
        except Exception as e:
            logging.error(f"Error opening Chrome for search '{query}': {e}")
            try:
                webbrowser.open(search_url)
                browser_name = "browser"
            except Exception as e2:
                logging.error(f"Fallback browser open failed: {e2}")
                return "Failed to open the browser for web search."

    # Initialize / update _BROWSER_CONTEXT immediately
    _BROWSER_CONTEXT = {
        "browser": browser_name,
        "query": query,
        "search_url": search_url,
        "active_url": search_url,
        "results": [],
        "history": [search_url],
        "history_idx": 0,
        "opened_by_nexa": True,
        "timestamp": time.time(),
    }

    # Attempt to cache top search results using existing DDG tools
    # Browser launch success MUST NOT depend on scraping success
    try:
        from backend.tools import _fetch_ddg_html_sync, _extract_ddg_html_results
        html_page = await asyncio.to_thread(_fetch_ddg_html_sync, query)
        if html_page:
            extracted = _extract_ddg_html_results(html_page, max_results=5)
            if extracted:
                _BROWSER_CONTEXT["results"] = extracted
        if not _BROWSER_CONTEXT["results"]:
            from backend.tools import _fetch_ddg_instant_sync
            instant = await asyncio.to_thread(_fetch_ddg_instant_sync, query, max_results=5)
            if instant:
                _BROWSER_CONTEXT["results"] = instant
    except Exception as e:
        logging.warning(f"Could not populate browser result cache for '{query}': {e}")

    # Fallback synthetic results if scraping could not populate (e.g. offline/blocked)
    if not _BROWSER_CONTEXT.get("results"):
        _BROWSER_CONTEXT["results"] = [
            {"title": f"{query} - Search Result", "url": search_url, "snippet": f"Web results for {query}"}
        ]

    # Return only a concise confirmation (Do NOT return scraped result lists in the transcript)
    return f"Searching for {query} in {browser_name}."


async def execute_browser_select_result(text: str, dry_run: bool = False) -> str:
    """Opens the user-selected search result link in Chrome from active _BROWSER_CONTEXT."""
    global _BROWSER_CONTEXT
    idx = _extract_browser_result_index(text)
    if idx is None:
        return "Please specify which result you want to open (e.g. 'open the first link')."

    zero_idx = idx - 1
    if not _BROWSER_CONTEXT or not _BROWSER_CONTEXT.get("results"):
        return "There are no search results available yet. Please search for something first."

    results = _BROWSER_CONTEXT.get("results", [])
    if zero_idx < 0 or zero_idx >= len(results):
        count = len(results)
        return f"Only {count} search results are available. Please choose between 1 and {count}."

    target_item = results[zero_idx]
    target_url = target_item.get("url", "")
    target_title = target_item.get("title", f"Result {idx}")

    ordinal_names = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}
    ord_str = ordinal_names.get(idx, f"#{idx}")

    if not dry_run and target_url:
        chrome_exe = _find_chrome_executable()
        try:
            if chrome_exe:
                subprocess.Popen([chrome_exe, target_url])
            else:
                import webbrowser
                webbrowser.open(target_url)
        except Exception as e:
            logging.error(f"Error opening selected result URL '{target_url}': {e}")
            try:
                import webbrowser
                webbrowser.open(target_url)
            except Exception:
                return f"Failed to open the {ord_str} result."

    # Update context history
    if target_url:
        _BROWSER_CONTEXT["active_url"] = target_url
        _BROWSER_CONTEXT["history"].append(target_url)
        _BROWSER_CONTEXT["history_idx"] = len(_BROWSER_CONTEXT["history"]) - 1

    return f"Opening the {ord_str} result: {target_title}."


async def execute_browser_control(action: str, dry_run: bool = False) -> str:
    """Executes browser scrolling and navigation commands."""
    global _BROWSER_CONTEXT

    # Guard: check if browser window exists or context is established
    hwnd = _find_browser_window_hwnd() if not dry_run else None
    has_active_browser = (hwnd is not None)
    has_context = (_BROWSER_CONTEXT is not None)

    if not dry_run and not has_active_browser and not has_context:
        return "There is no active browser window or search to navigate. Please search for something first."

    browser_name = _BROWSER_CONTEXT.get("browser", "Chrome") if _BROWSER_CONTEXT else "Chrome"

    if not dry_run:
        success = _send_browser_key(action)
        if not success and not has_active_browser:
            return "Could not find an active browser window to navigate."

    if _BROWSER_CONTEXT:
        if action == "go_back" and _BROWSER_CONTEXT.get("history_idx", 0) > 0:
            _BROWSER_CONTEXT["history_idx"] -= 1
            idx = _BROWSER_CONTEXT["history_idx"]
            _BROWSER_CONTEXT["active_url"] = _BROWSER_CONTEXT["history"][idx]
        elif action == "go_forward" and _BROWSER_CONTEXT.get("history_idx", 0) < len(_BROWSER_CONTEXT.get("history", [])) - 1:
            _BROWSER_CONTEXT["history_idx"] += 1
            idx = _BROWSER_CONTEXT["history_idx"]
            _BROWSER_CONTEXT["active_url"] = _BROWSER_CONTEXT["history"][idx]

    messages = {
        "scroll_down": f"Scrolled down in {browser_name}.",
        "scroll_down_little": f"Scrolled down a little in {browser_name}.",
        "scroll_down_more": f"Scrolled down in {browser_name}.",
        "go_down": f"Scrolled down in {browser_name}.",
        "scroll_up": f"Scrolled up in {browser_name}.",
        "go_up": f"Scrolled up in {browser_name}.",
        "scroll_up_little": f"Scrolled up a little in {browser_name}.",
        "scroll_up_more": f"Scrolled up in {browser_name}.",
        "go_top": f"Scrolled to the top of the page in {browser_name}.",
        "go_bottom": f"Scrolled to the bottom of the page in {browser_name}.",
        "go_back": f"Navigated back in {browser_name}.",
        "go_forward": f"Navigated forward in {browser_name}.",
        "refresh": f"Refreshed the page in {browser_name}.",
    }
    return messages.get(action, f"Executed browser command in {browser_name}.")


async def execute_weather(text: str, context: Optional[Any] = None) -> str:
    """Invokes existing weather tool."""
    try:
        from backend.tools import get_weather
    except ImportError:
        from tools import get_weather  # type: ignore

    # Extract city name or default to local
    cleaned = text.strip().rstrip("?.!")
    city_match = re.search(r"\b(?:in|for|at)\b\s+([A-Za-z\s]+)$", cleaned, flags=re.IGNORECASE)
    city = city_match.group(1).strip() if city_match else "Delhi"

    return await get_weather(context=context, city=city)


# ---------------------------------------------------------
# Email & Google Calendar Action Invokers
# ---------------------------------------------------------

_PENDING_EMAIL_STATE: Optional[Dict[str, Any]] = None
_PENDING_CALENDAR_STATE: Optional[Dict[str, Any]] = None
_PENDING_REMINDER_STATE: Optional[Dict[str, Any]] = None

def get_pending_email_state() -> Optional[Dict[str, Any]]:
    return _PENDING_EMAIL_STATE

def clear_pending_email_state() -> None:
    global _PENDING_EMAIL_STATE
    _PENDING_EMAIL_STATE = None
    try:
        from backend.tools import clear_pending_email_for_session
        clear_pending_email_for_session("default_session")
        clear_pending_email_for_session("offline_default")
    except Exception:
        pass

def get_pending_calendar_state() -> Optional[Dict[str, Any]]:
    return _PENDING_CALENDAR_STATE

def clear_pending_calendar_state() -> None:
    global _PENDING_CALENDAR_STATE
    _PENDING_CALENDAR_STATE = None

def get_pending_reminder_state() -> Optional[Dict[str, Any]]:
    return _PENDING_REMINDER_STATE

def clear_pending_reminder_state() -> None:
    global _PENDING_REMINDER_STATE
    _PENDING_REMINDER_STATE = None


def _is_reminder_capability_or_incomplete(clean_low: str) -> Tuple[bool, str]:
    """Determines if query is a capability question or incomplete reminder command."""
    # Capability inquiries (e.g. "can you set reminder", "are you able to set reminders?")
    capability_patterns = (
        "can you set reminder", "can you set a reminder", "can you set reminders",
        "could you set reminder", "could you set a reminder",
        "are you able to set reminder", "are you able to set reminders",
        "do you support reminders", "do you set reminders",
        "can you create reminder", "can you create a reminder", "can you create reminders",
        "can you remind me", "could you remind me"
    )
    if any(p in clean_low for p in capability_patterns) and not any(k in clean_low for k in (" in ", " at ", " to ", " by ", " for ")):
        return True, "Yes, I can set reminders! What would you like to be reminded about, and when?"

    # Incomplete reminder commands (e.g. "set reminder", "remind me")
    incomplete_commands = (
        "set reminder", "set a reminder", "set the reminder",
        "create reminder", "create a reminder", "add reminder", "add a reminder",
        "remind me", "please remind me", "set timer", "set a timer"
    )
    clean_stripped = clean_low.rstrip(".!? ")
    if clean_stripped in incomplete_commands:
        return True, "What would you like to be reminded about, and when (e.g. 'buy groceries in 30 minutes')?"

    return False, ""


def _parse_reminder_text_and_time(text: str) -> Tuple[str, str]:
    """Parses reminder text and target time safely."""
    clean = text.strip()
    try:
        from backend.ml.normalizer import strip_carrier_prefixes
        clean = strip_carrier_prefixes(clean)
    except Exception:
        pass
    clean = clean.strip(".!? ")
    m = re.match(r"^(?:please\s+)?remind\s+me\s+in\s+(\d+\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?))\s+to\s+(.+)$", clean, re.I)
    if m:
        return (m.group(2).strip(), m.group(1).strip())
    m = re.match(r"^(?:please\s+)?remind\s+me\s+to\s+(.+?)\s+(?:in|at|by)\s+(\d+.*)$", clean, re.I)
    if m:
        return (m.group(1).strip(), m.group(2).strip())
    m = re.match(r"^(?:please\s+)?set\s+(?:a\s+)?timer\s+for\s+(\d+\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?))(?:\s+to\s+(.+))?$", clean, re.I)
    if m:
        return ((m.group(2) or "Timer").strip(), m.group(1).strip())
    m = re.match(r"^(?:please\s+)?set\s+(?:a\s+)?reminder\s+in\s+(\d+\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?))\s+(?:to|for)\s+(.+)$", clean, re.I)
    if m:
        return (m.group(2).strip(), m.group(1).strip())
    m = re.match(r"^(?:please\s+)?set\s+(?:a\s+)?reminder\s+(?:to|for)\s+(.+?)\s+(?:in|at|by)\s+(\d+.*)$", clean, re.I)
    if m:
        return (m.group(1).strip(), m.group(2).strip())
    m = re.match(r"^(?:to\s+)?(.+?)\s+(?:in|at|by)\s+(\d+.*)$", clean, re.I)
    if m:
        return (m.group(1).strip(), m.group(2).strip())
    m = re.match(r"^(?:please\s+)?remind\s+me\s+to\s+(.+)$", clean, re.I)
    if m:
        return (m.group(1).strip(), "in 10 minutes")
    m = re.match(r"^(?:please\s+)?set\s+(?:a\s+)?reminder\s+(?:to|for)\s+(.+)$", clean, re.I)
    if m:
        return (m.group(1).strip(), "in 10 minutes")
    return (clean, "in 10 minutes")


async def execute_send_email(text: str, dry_run: bool = False) -> str:
    """Parses recipient, subject, and body from user command text and sends email via SMTP."""
    global _PENDING_EMAIL_STATE
    from dotenv import load_dotenv
    load_dotenv()

    gmail_user = os.getenv("GMAIL_USER", "").strip()
    clean = text.strip()

    # 1. Recipient extraction
    recipient = None
    m_email = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", clean)
    if m_email:
        recipient = m_email.group(0)
    elif re.search(r"\b(?:to\s+)?(?:myself|me)\b", clean, re.I):
        recipient = gmail_user or "myself"

    if not recipient:
        _PENDING_EMAIL_STATE = {
            "step": "recipient",
            "recipient": None,
            "subject": None,
            "body": None,
        }
        return "Please provide the recipient's email address."

    # Direct email command: clear pending state
    _PENDING_EMAIL_STATE = None

    # 2. Subject extraction
    subject = "NEXA Message"
    m_subj = re.search(r"\bwith\s+subject\s+([^,]+?)(?:\s+(?:saying|body|that|message)\b|$)", clean, re.I)
    if not m_subj:
        m_subj = re.search(r"\bsubject\s+([^,]+?)(?:\s+(?:saying|body|that|message)\b|$)", clean, re.I)
    if m_subj:
        subject = m_subj.group(1).strip().strip("'\"")

    # 3. Body/Message extraction
    m_body = re.search(r"\b(?:saying|body|message|that)\s+(.+)$", clean, re.I)
    if m_body:
        body = m_body.group(1).strip().strip("'\"")
    else:
        body = subject

    if dry_run:
        return f"[DRY-RUN] Email dispatch simulated to {recipient} with subject '{subject}' and body '{body}'."

    try:
        from backend.tools import send_email
    except ImportError:
        from tools import send_email  # type: ignore

    return await send_email(context=None, to_email=recipient, subject=subject, message=body)


async def execute_calendar_event(text: str, dry_run: bool = False) -> str:
    """Parses meeting details from user command and schedules event in Google Calendar via n8n MCP."""
    from datetime import datetime, timedelta
    from dotenv import load_dotenv
    load_dotenv()

    try:
        from backend.mcp.agent_tools import KOLKATA_TZ, normalize_to_kolkata_rfc3339, resolve_calendar_id
    except ImportError:
        from mcp.agent_tools import KOLKATA_TZ, normalize_to_kolkata_rfc3339, resolve_calendar_id  # type: ignore

    now = datetime.now(KOLKATA_TZ)
    clean = text.strip()

    # 1. Summary/Title extraction
    summary = "Meeting"
    m_topic = re.search(r"\b(?:schedule|create|set up|add|book)\s+(?:an?\s+)?([a-zA-Z0-9\s]+?)(?:\s+(?:on|at|from|tomorrow|today|with|for|about)\b|$)", clean, re.I)
    m_with = re.search(r"\b(?:with|about|for)\s+([A-Za-z0-9\s]+?)(?:\s+(?:on|at|from|tomorrow|today)\b|$)", clean, re.I)
    if m_topic and m_topic.group(1).strip().lower() not in ("meeting", "event", "call", "appointment", ""):
        base_topic = m_topic.group(1).strip().title()
        if m_with:
            summary = f"{base_topic} with {m_with.group(1).strip().title()}"
        else:
            summary = base_topic
    elif m_with:
        summary = f"Meeting with {m_with.group(1).strip().title()}"

    # 2. Date extraction
    target_date = now.date()
    matched_date_str = ""
    if re.search(r"\btomorrow\b", clean, re.I):
        target_date = (now + timedelta(days=1)).date()
    elif re.search(r"\btoday\b", clean, re.I):
        target_date = now.date()
    else:
        m_iso = re.search(r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})\b", clean)
        if m_iso:
            iso_str = m_iso.group(1)
            matched_date_str = iso_str
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
                try:
                    target_date = datetime.strptime(iso_str, fmt).date()
                    break
                except ValueError:
                    pass
        else:
            m_date = re.search(r"\b(?:on\s+)?(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+|[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?)(?:\s*,?\s*(\d{4}))?\b", clean, re.I)
            if m_date:
                date_str = m_date.group(0)
                matched_date_str = date_str
                date_str = re.sub(r"^(on\s+)", "", date_str, flags=re.I)
                date_str = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str, flags=re.I).strip()
                for fmt in ("%d %B %Y", "%B %d %Y", "%d %b %Y", "%b %d %Y", "%d %B", "%B %d", "%d %b", "%b %d"):
                    try:
                        d = datetime.strptime(date_str, fmt)
                        year = d.year if d.year != 1900 else (int(m_date.group(2)) if m_date.group(2) else now.year)
                        target_date = d.replace(year=year).date()
                        break
                    except ValueError:
                        continue

    # Remove matched date string from time candidate to avoid hyphen collisions
    time_clean = clean.replace(matched_date_str, "") if matched_date_str else clean

    # 3. Time range extraction
    start_dt = None
    end_dt = None
    m_range = re.search(r"\b(?:from\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:to|-)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", time_clean, re.I)
    if m_range:
        t1_str, t2_str = m_range.group(1).strip(), m_range.group(2).strip()
        if not re.search(r"[a-zA-Z]", t1_str) and re.search(r"[a-zA-Z]", t2_str):
            suffix = re.search(r"(am|pm)", t2_str, re.I).group(1)
            t1_str += f" {suffix}"
        t1_str = re.sub(r"(\d+)(am|pm)", r"\1 \2", t1_str, flags=re.I)
        t2_str = re.sub(r"(\d+)(am|pm)", r"\1 \2", t2_str, flags=re.I)
        for fmt in ("%I:%M %p", "%I %p", "%I:%M%p", "%I%p", "%H:%M"):
            try:
                t1 = datetime.strptime(t1_str.upper(), fmt).time()
                start_dt = datetime.combine(target_date, t1).replace(tzinfo=KOLKATA_TZ)
                break
            except ValueError:
                pass
        for fmt in ("%I:%M %p", "%I %p", "%I:%M%p", "%I%p", "%H:%M"):
            try:
                t2 = datetime.strptime(t2_str.upper(), fmt).time()
                end_dt = datetime.combine(target_date, t2).replace(tzinfo=KOLKATA_TZ)
                break
            except ValueError:
                pass

    if not start_dt:
        m_at = re.search(r"\b(?:at\s+)(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", time_clean, re.I)
        if m_at:
            t_str = m_at.group(1).strip()
            t_str = re.sub(r"(\d+)(am|pm)", r"\1 \2", t_str, flags=re.I)
            for fmt in ("%I:%M %p", "%I %p", "%I:%M%p", "%I%p", "%H:%M"):
                try:
                    t = datetime.strptime(t_str.upper(), fmt).time()
                    start_dt = datetime.combine(target_date, t).replace(tzinfo=KOLKATA_TZ)
                    end_dt = start_dt + timedelta(hours=1)
                    break
                except ValueError:
                    pass

    global _PENDING_CALENDAR_STATE
    if not start_dt:
        _PENDING_CALENDAR_STATE = {
            "summary": summary,
            "date": target_date,
            "original_text": text,
        }
        return "Please specify the time for the meeting (e.g. 'Schedule a meeting tomorrow from 11 AM to 12 PM' or 'from 1pm to 5pm')."

    _PENDING_CALENDAR_STATE = None

    if not end_dt:
        end_dt = start_dt + timedelta(hours=1)

    start_iso = start_dt.isoformat()
    end_iso = end_dt.isoformat()

    if dry_run:
        return f"[DRY-RUN] Calendar event creation simulated for '{summary}' from {start_iso} to {end_iso}."

    server_url = os.getenv("N8N_MCP_SERVER_URL", "")
    if not server_url:
        return "I cannot schedule that meeting right now because Google Calendar integration is not configured. Please set N8N_MCP_SERVER_URL."

    try:
        from backend.mcp.server import MCPServerSse
        from backend.mcp.util import MCPUtil
        from backend.mcp.agent_tools import MCPToolsIntegration
    except ImportError:
        from mcp.server import MCPServerSse  # type: ignore
        from mcp.util import MCPUtil  # type: ignore
        from mcp.agent_tools import MCPToolsIntegration  # type: ignore

    server = MCPServerSse({"url": server_url, "sse_read_timeout": None})
    try:
        await server.connect(timeout=5.0)
        fts = await MCPUtil.get_function_tools(server)
        cal_tool = next((t for t in fts if "calendar" in t.name.lower()), None)
        if not cal_tool:
            return "I cannot schedule that meeting right now because Google Calendar integration tool is not found on the MCP server."
        dec_tool = MCPToolsIntegration._create_decorated_tool(cal_tool)
        cal_id = resolve_calendar_id()
        res = await dec_tool(Calendar=cal_id, Start=start_iso, End=end_iso, Summary=summary)
        return str(res)
    except Exception as e:
        logging.warning("Google Calendar MCP connection error: %s", e)
        return f"I cannot schedule that meeting right now due to a calendar service error: {e}"
    finally:
        await server.cleanup()


# ---------------------------------------------------------
# Master Intent Router & Action Dispatcher
# ---------------------------------------------------------

async def route_intent(
    text: str,
    confirmed: bool = False,
    run_context: Optional[Any] = None,
    dry_run: bool = False,
    perf_record: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Classifies user command text with the trained ML intent model.
    
    If trusted=True: dispatches directly to the corresponding desktop action.
    If trusted=False: gracefully returns fallback indicator so Gemini Realtime handles it.
    """
    global _PENDING_EMAIL_STATE, _PENDING_CALENDAR_STATE, _PENDING_REMINDER_STATE
    t_route_start = time.perf_counter()
    clean_low = text.strip().lower()

    # Priority -0.1: Screen Understanding (e.g. "what is on my screen", "which tab is open")
    if _is_screen_understanding_query(text):
        res = await execute_screen_understanding(text, dry_run=dry_run)
        return {
            "handled": True,
            "intent": "SCREEN_UNDERSTANDING",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Priority 0: Visual Product Search (e.g. "search for these glasses", "search for what i am holding")
    if _is_visual_search_query(text):
        res = await execute_visual_product_search(text, dry_run=dry_run)
        return {
            "handled": True,
            "intent": "VISUAL_PRODUCT_SEARCH",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Priority 0.1: Camera Visual Understanding Query (takes priority over camera activation)
    if _is_camera_vision_query(text):
        res = await execute_camera_vision_query(text, dry_run=dry_run)
        return {
            "handled": True,
            "intent": "CAMERA_VISION_QUERY",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # 0. Intercept multi-turn pending email conversation flow
    if _PENDING_EMAIL_STATE is not None:
        if clean_low in ("cancel", "stop", "never mind", "nevermind", "abort", "cancel email", "stop email"):
            _PENDING_EMAIL_STATE = None
            return {
                "handled": True,
                "intent": "SEND_EMAIL",
                "confidence": 1.0,
                "margin": 1.0,
                "trusted": True,
                "fallback": False,
                "result": "Email dispatch cancelled."
            }

        step = _PENDING_EMAIL_STATE.get("step")
        if step == "recipient":
            m_email = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text)
            is_myself = bool(re.search(r"\b(?:to\s+)?(?:myself|me)\b", text, re.I))
            if m_email or is_myself:
                from dotenv import load_dotenv
                load_dotenv()
                recipient = m_email.group(0) if m_email else (os.getenv("GMAIL_USER", "").strip() or "myself")
                _PENDING_EMAIL_STATE["recipient"] = recipient

                # Check if subject/body were also supplied in the same message
                m_subj = re.search(r"\bwith\s+subject\s+([^,]+?)(?:\s+(?:saying|body|that|message)\b|$)", text, re.I)
                if not m_subj:
                    m_subj = re.search(r"\bsubject\s+([^,]+?)(?:\s+(?:saying|body|that|message)\b|$)", text, re.I)
                if m_subj:
                    _PENDING_EMAIL_STATE["subject"] = m_subj.group(1).strip().strip("'\"")

                m_body = re.search(r"\b(?:saying|body|message|that)\s+(.+)$", text, re.I)
                if m_body:
                    _PENDING_EMAIL_STATE["body"] = m_body.group(1).strip().strip("'\"")

                if not _PENDING_EMAIL_STATE.get("subject"):
                    _PENDING_EMAIL_STATE["step"] = "subject"
                    return {
                        "handled": True,
                        "intent": "SEND_EMAIL",
                        "confidence": 1.0,
                        "margin": 1.0,
                        "trusted": True,
                        "fallback": False,
                        "result": "What is the subject of the email?"
                    }
                elif not _PENDING_EMAIL_STATE.get("body"):
                    _PENDING_EMAIL_STATE["step"] = "body"
                    return {
                        "handled": True,
                        "intent": "SEND_EMAIL",
                        "confidence": 1.0,
                        "margin": 1.0,
                        "trusted": True,
                        "fallback": False,
                        "result": "What would you like the email body to say?"
                    }
                else:
                    rec = _PENDING_EMAIL_STATE["recipient"]
                    subj = _PENDING_EMAIL_STATE["subject"]
                    bod = _PENDING_EMAIL_STATE["body"]
                    _PENDING_EMAIL_STATE = None
                    if dry_run:
                        res = f"[DRY-RUN] Email dispatch simulated to {rec} with subject '{subj}' and body '{bod}'."
                    else:
                        try:
                            from backend.tools import send_email
                        except ImportError:
                            from tools import send_email  # type: ignore
                        res = await send_email(context=None, to_email=rec, subject=subj, message=bod)
                    return {
                        "handled": True,
                        "intent": "SEND_EMAIL",
                        "confidence": 1.0,
                        "margin": 1.0,
                        "trusted": True,
                        "fallback": False,
                        "result": res
                    }
            else:
                # If command matches common system action prefixes or resource queries, clear pending state and allow routing
                common_switches = (
                    "ram", "cpu", "battery", "storage", "disk", "volume", "wifi", "bluetooth",
                    "time", "date", "weather", "open ", "launch ", "start ", "close ", "terminate ",
                    "mute ", "unmute ", "restart", "shutdown", "screen share"
                )
                if any(k in clean_low for k in common_switches):
                    _PENDING_EMAIL_STATE = None
                else:
                    return {
                        "handled": True,
                        "intent": "SEND_EMAIL",
                        "confidence": 1.0,
                        "margin": 1.0,
                        "trusted": True,
                        "fallback": False,
                        "result": "Please provide a valid recipient email address (e.g., user@example.com)."
                    }

        elif step == "subject":
            if clean_low in ("skip", "default", "none", "no subject"):
                subject = "NEXA Message"
            else:
                subject = text.strip()
            _PENDING_EMAIL_STATE["subject"] = subject
            _PENDING_EMAIL_STATE["step"] = "body"
            return {
                "handled": True,
                "intent": "SEND_EMAIL",
                "confidence": 1.0,
                "margin": 1.0,
                "trusted": True,
                "fallback": False,
                "result": "What would you like the email body to say?"
            }

        elif step == "body":
            if clean_low in ("skip", "default", "none", "no body"):
                body = _PENDING_EMAIL_STATE.get("subject") or "NEXA Message"
            else:
                body = text.strip()
            _PENDING_EMAIL_STATE["body"] = body

            rec = _PENDING_EMAIL_STATE["recipient"]
            subj = _PENDING_EMAIL_STATE["subject"]
            _PENDING_EMAIL_STATE = None

            if dry_run:
                res = f"[DRY-RUN] Email dispatch simulated to {rec} with subject '{subj}' and body '{body}'."
            else:
                try:
                    from backend.tools import send_email
                except ImportError:
                    from tools import send_email  # type: ignore
                res = await send_email(context=None, to_email=rec, subject=subj, message=body)

            return {
                "handled": True,
                "intent": "SEND_EMAIL",
                "confidence": 1.0,
                "margin": 1.0,
                "trusted": True,
                "fallback": False,
                "result": res
            }

    # Intercept standalone email address input even without prior pending state
    if re.fullmatch(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}", text.strip()):
        _PENDING_EMAIL_STATE = {
            "step": "subject",
            "recipient": text.strip(),
            "subject": None,
            "body": None,
        }
        return {
            "handled": True,
            "intent": "SEND_EMAIL",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": "What is the subject of the email?"
        }

    # 1. Intercept multi-turn pending calendar scheduling conversation flow
    if _PENDING_CALENDAR_STATE is not None:
        if clean_low in ("cancel", "stop", "never mind", "nevermind", "abort", "cancel meeting", "stop meeting"):
            _PENDING_CALENDAR_STATE = None
            return {
                "handled": True,
                "intent": "CREATE_CALENDAR_EVENT",
                "confidence": 1.0,
                "margin": 1.0,
                "trusted": True,
                "fallback": False,
                "result": "Calendar event creation cancelled."
            }

        common_switches = (
            "ram", "cpu", "battery", "storage", "disk", "volume", "wifi", "bluetooth",
            "open ", "launch ", "start ", "close ", "terminate ", "mute ", "unmute "
        )
        if any(clean_low.startswith(p) for p in common_switches):
            _PENDING_CALENDAR_STATE = None
        else:
            saved_date = _PENDING_CALENDAR_STATE.get("date")
            saved_summary = _PENDING_CALENDAR_STATE.get("summary", "Meeting")
            _PENDING_CALENDAR_STATE = None
            date_part = saved_date.strftime("%Y-%m-%d") if hasattr(saved_date, "strftime") else "tomorrow"
            combined_command = f"Schedule {saved_summary} on {date_part} {text.strip()}"
            res = await execute_calendar_event(combined_command, dry_run=dry_run)
            return {
                "handled": True,
                "intent": "CREATE_CALENDAR_EVENT",
                "confidence": 1.0,
                "margin": 1.0,
                "trusted": True,
                "fallback": False,
                "result": res
            }

    # 2. Intercept multi-turn pending reminder conversation flow
    if _PENDING_REMINDER_STATE is not None:
        if clean_low in ("cancel", "stop", "never mind", "nevermind", "abort", "cancel reminder", "stop reminder"):
            _PENDING_REMINDER_STATE = None
            return {
                "handled": True,
                "intent": "SET_REMINDER",
                "confidence": 1.0,
                "margin": 1.0,
                "trusted": True,
                "fallback": False,
                "result": "Reminder creation cancelled."
            }

        common_switches = (
            "ram", "cpu", "battery", "storage", "disk", "volume", "wifi", "bluetooth",
            "open ", "launch ", "start ", "close ", "terminate ", "mute ", "unmute "
        )
        if any(clean_low.startswith(p) for p in common_switches):
            _PENDING_REMINDER_STATE = None
        else:
            is_cap_or_inc, rem_prompt = _is_reminder_capability_or_incomplete(clean_low)
            if is_cap_or_inc:
                return {
                    "handled": True,
                    "intent": "SET_REMINDER",
                    "confidence": 1.0,
                    "margin": 1.0,
                    "trusted": True,
                    "fallback": False,
                    "result": rem_prompt
                }
            _PENDING_REMINDER_STATE = None
            rem_text, rem_time = _parse_reminder_text_and_time(text)
            try:
                from backend.tools import set_reminder
            except ImportError:
                from tools import set_reminder  # type: ignore
            res = await set_reminder(context=None, reminder_text=rem_text, target_time=rem_time)
            return {
                "handled": True,
                "intent": "SET_REMINDER",
                "confidence": 1.0,
                "margin": 1.0,
                "trusted": True,
                "fallback": False,
                "result": res
            }

    # 3. Intercept reminder capability queries or incomplete commands
    is_cap_or_inc, rem_prompt = _is_reminder_capability_or_incomplete(clean_low)
    if is_cap_or_inc:
        _PENDING_REMINDER_STATE = {"step": "details"}
        return {
            "handled": True,
            "intent": "SET_REMINDER",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": rem_prompt
        }

    # Intercept browser result selection (e.g. "open the first link", "open the second result", "open the first one", "the first one")
    browser_result_idx = _extract_browser_result_index(clean_low)
    if browser_result_idx is not None:
        res = await execute_browser_select_result(text, dry_run=dry_run)
        return {
            "handled": True,
            "intent": "BROWSER_SELECT_RESULT",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Intercept browser navigation & scrolling (e.g. "scroll down", "scroll up", "go back", "go forward", "refresh", "go to top")
    browser_nav_action = _extract_browser_nav_action(clean_low)
    if browser_nav_action is not None:
        res = await execute_browser_control(browser_nav_action, dry_run=dry_run)
        return {
            "handled": True,
            "intent": "BROWSER_CONTROL",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Intercept visual product search commands (e.g. "search for these glasses", "find these shoes")
    if _is_visual_search_query(text):
        res = await execute_visual_product_search(text, dry_run=dry_run)
        return {
            "handled": True,
            "intent": "VISUAL_PRODUCT_SEARCH",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Intercept explicit web-search commands (e.g. "search for python courses", "find python courses online", "search", "look up")
    if _is_explicit_web_search(clean_low):
        if perf_record is not None:
            t3 = time.perf_counter()
            perf_record["t3_intent"] = t3
            perf_record["intent_duration_ms"] = (t3 - t_route_start) * 1000.0
            perf_record["t4_routing"] = t3
            perf_record["routing_duration_ms"] = 0.0
            perf_record["category"] = "Local ML command"
        t_act_start = time.perf_counter()
        res = await execute_web_search(text, run_context, dry_run=dry_run)
        if perf_record is not None:
            t5 = time.perf_counter()
            perf_record["t5_action"] = t5
            perf_record["action_duration_ms"] = (t5 - t_act_start) * 1000.0
        return {
            "handled": True,
            "intent": "SEARCH_WEB",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # 4. Intercept opening registered applications in COMMON_APPS
    app_candidate = _extract_app_name(text)
    if app_candidate and app_candidate in COMMON_APPS and app_candidate not in ("settings", "windows settings", "system settings"):
        if perf_record is not None:
            t3 = time.perf_counter()
            perf_record["t3_intent"] = t3
            perf_record["intent_duration_ms"] = (t3 - t_route_start) * 1000.0
            perf_record["t4_routing"] = t3
            perf_record["routing_duration_ms"] = 0.0
            perf_record["category"] = "Local desktop action"
        t_act_start = time.perf_counter()
        res = await open_application(text)
        if perf_record is not None:
            t5 = time.perf_counter()
            perf_record["t5_action"] = t5
            perf_record["action_duration_ms"] = (t5 - t_act_start) * 1000.0
        return {
            "handled": True,
            "intent": "OPEN_APPLICATION",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    bundle = get_model_bundle()
    if not bundle or predict_intent_details is None:
        logging.warning("ML intent model bundle not loaded or unavailable.")
        return {
            "handled": False,
            "intent": "UNKNOWN",
            "confidence": 0.0,
            "margin": 0.0,
            "trusted": False,
            "fallback": True,
            "result": "I'm not sure I understand that request. Could you please rephrase?"
        }

    # Intercept camera turn off / close commands
    camera_off_keywords = (
        "turn off camera", "turn off the camera", "close camera", "close the camera",
        "stop camera", "stop the camera", "disable camera", "disable the camera",
        "turn camera off", "switch off camera", "deactivate camera",
        "turn off webcam", "close webcam", "stop webcam", "disable webcam", "shut off camera"
    )
    if clean_low in camera_off_keywords or any(clean_low.startswith(k + " ") for k in camera_off_keywords):
        set_camera_active_state(False)
        return {
            "handled": True,
            "intent": "TURN_OFF_CAMERA",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": "Camera viewport closed."
        }

    # Intercept application termination commands so they are never misclassified as OPEN_APPLICATION
    close_prefixes = ("close ", "exit ", "quit ", "terminate ", "kill ")
    if any(clean_low.startswith(p) for p in close_prefixes):
        res = await close_application_action(text, dry_run=dry_run)
        return {
            "handled": True,
            "intent": "CLOSE_APPLICATION",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Intercept process awareness / application inspection queries so they are never misclassified as OPEN_APPLICATION
    is_process_query = False
    proc_app_name = None
    proc_top_mem = False

    if any(k in clean_low for k in ("most memory", "highest memory", "top memory", "using the most ram", "using most memory")):
        is_process_query = True
        proc_top_mem = True
    elif any(clean_low.startswith(p) for p in ("is ", "are ", "how many ")) and any(s in clean_low for s in ("running", "open", "active", "processes", "instances")):
        is_process_query = True
        proc_app_name = text
    elif any(k in clean_low for k in ("what apps are open", "what applications are open", "what apps are running", "what applications are running", "which apps are open", "which applications are open", "list open apps", "list running apps")):
        is_process_query = True
        proc_app_name = None

    if is_process_query:
        res = await inspect_applications_action(app_name=proc_app_name, top_memory=proc_top_mem)
        return {
            "handled": True,
            "intent": "INSPECT_APPLICATIONS",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Intercept microphone unmute / mute commands (unmute checked before mute to prevent substring overlap)
    if any(k in clean_low for k in ("unmute mic", "unmute microphone", "unmute my mic", "unmute my microphone", "unmute audio input", "unmute sound input", "unmute input")):
        res = await mute_microphone(mute=False, dry_run=dry_run)
        return {
            "handled": True,
            "intent": "UNMUTE_MICROPHONE",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }
    elif any(k in clean_low for k in ("mute mic", "mute microphone", "mute my mic", "mute my microphone", "mute audio input", "mute sound input", "mute input")):
        res = await mute_microphone(mute=True, dry_run=dry_run)
        return {
            "handled": True,
            "intent": "MUTE_MICROPHONE",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Intercept system audio unmute / mute commands (unmute checked before mute to prevent substring overlap)
    if any(k in clean_low for k in ("unmute volume", "unmute audio", "unmute sound", "unmute system volume", "unmute the sound", "unmute computer", "unmute laptop", "unmute speakers")) or clean_low == "unmute":
        res = await mute_system_volume(mute=False, dry_run=dry_run)
        return {
            "handled": True,
            "intent": "UNMUTE_VOLUME",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }
    elif any(k in clean_low for k in ("mute volume", "mute audio", "mute sound", "mute system volume", "mute the sound", "mute computer", "mute laptop", "mute speakers")) or clean_low == "mute":
        res = await mute_system_volume(mute=True, dry_run=dry_run)
        return {
            "handled": True,
            "intent": "MUTE_VOLUME",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Helper function for word-boundary or multi-word phrase matching
    def _matches_kw(kw: str, src: str) -> bool:
        if " " in kw or "-" in kw:
            return kw in src
        return bool(re.search(r"\b" + re.escape(kw) + r"\b", src))

    # Intercept cancel all reminders (must be before cancel reminder and show reminders)
    if any(k in clean_low for k in ("cancel all reminders", "delete all reminders", "clear all reminders", "remove all reminders", "stop all timers", "cancel all my reminders")):
        try:
            from backend.tools import cancel_all_reminders
        except ImportError:
            from tools import cancel_all_reminders  # type: ignore
        res = await cancel_all_reminders(context=None)
        return {
            "handled": True,
            "intent": "CANCEL_ALL_REMINDERS",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Intercept cancel specific reminder (must be before show reminders)
    if any(clean_low.startswith(p) for p in ("cancel reminder", "delete reminder", "remove reminder", "stop timer", "cancel timer", "delete timer", "cancel my reminder", "delete my reminder")):
        try:
            from backend.tools import cancel_reminder
        except ImportError:
            from tools import cancel_reminder  # type: ignore
        rem_id = None
        id_match = re.search(r"\b(?:id|number|#)?\s*(\d+)\b", text, re.I)
        if id_match:
            rem_id = int(id_match.group(1))
        rem_text = re.sub(r"^(?:please\s+)?(?:cancel|delete|remove|stop)\s+(?:the\s+|my\s+)?(?:reminder|timer)\s*(?:for|to|about|#|\d+)?\s*", "", text, flags=re.I).strip()
        res = await cancel_reminder(context=None, reminder_id=rem_id, reminder_text=rem_text or None)
        return {
            "handled": True,
            "intent": "CANCEL_REMINDER",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Intercept reminder queries (show / list)
    if any(k in clean_low for k in ("show reminders", "show my reminders", "list reminders", "list my reminders", "what reminders", "view reminders", "view my reminders", "check reminders", "check my reminders", "pending reminders", "check timers")) or clean_low in ("my reminders", "reminders", "timers"):
        try:
            from backend.tools import show_reminders
        except ImportError:
            from tools import show_reminders  # type: ignore
        res = await show_reminders(context=None)
        return {
            "handled": True,
            "intent": "SHOW_REMINDERS",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Intercept set reminder / timer
    if any(clean_low.startswith(p) for p in ("remind me ", "set a reminder", "set reminder", "set a timer", "set timer", "please remind me")):
        try:
            from backend.tools import set_reminder
        except ImportError:
            from tools import set_reminder  # type: ignore

        rem_text, rem_time = _parse_reminder_text_and_time(text)
        res = await set_reminder(context=None, reminder_text=rem_text, target_time=rem_time)
        return {
            "handled": True,
            "intent": "SET_REMINDER",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Intercept explicit memory saving commands
    if any(clean_low.startswith(p) for p in ("remember that ", "remember this:", "remember this ", "save this in memory", "save to memory", "note that ")):
        try:
            from backend.tools import remember_fact
        except ImportError:
            from tools import remember_fact  # type: ignore
        fact = re.sub(
            r"^(?:please\s+)?(?:remember\s+that\s+|remember\s+this:?\s*|remember\s+|save\s+(?:this\s+)?(?:in|to)\s+memory:?\s*|note\s+that\s+)",
            "",
            text,
            flags=re.I
        ).strip()
        if fact:
            res = await remember_fact(context=None, fact=fact)
            return {
                "handled": True,
                "intent": "REMEMBER_FACT",
                "confidence": 1.0,
                "margin": 1.0,
                "trusted": True,
                "fallback": False,
                "result": res
            }

    # Intercept memory retrieval / search queries
    if any(clean_low.startswith(p) for p in ("what do you remember", "what did i tell you", "what do you know about me", "search memory", "check memory", "what are my preferences")):
        try:
            from backend.tools import search_memories
        except ImportError:
            from tools import search_memories  # type: ignore
        query = re.sub(
            r"^(?:please\s+)?(?:what\s+do\s+you\s+remember\s+(?:about\s+)?|what\s+did\s+i\s+tell\s+you\s+(?:about\s+)?|what\s+do\s+you\s+know\s+about\s+|search\s+memory\s+(?:for\s+)?|check\s+memory\s+(?:for\s+)?)",
            "",
            text,
            flags=re.I
        ).strip(" ?.")
        res = await search_memories(context=None, query=query or "user")
        return {
            "handled": True,
            "intent": "SEARCH_MEMORIES",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Intercept forget memory commands
    if any(clean_low.startswith(p) for p in ("forget that ", "forget what you remember", "forget ", "delete memory", "remove memory")):
        try:
            from backend.tools import forget_memory
        except ImportError:
            from tools import forget_memory  # type: ignore
        query = re.sub(
            r"^(?:please\s+)?(?:forget\s+that\s+|forget\s+what\s+you\s+remember\s+(?:about\s+)?|forget\s+|delete\s+memory\s+(?:about\s+)?|remove\s+memory\s+(?:about\s+)?)",
            "",
            text,
            flags=re.I
        ).strip(" ?.")
        res = await forget_memory(context=None, query=query)
        return {
            "handled": True,
            "intent": "FORGET_MEMORY",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    clean_action_text = re.sub(r"^(?:can you\s+|could you\s+|please\s+)", "", clean_low).strip()

    # Intercept email commands
    email_prefixes = ("send an email", "send email", "email ", "write an email", "shoot an email", "send mail", "email someone", "compose an email")
    if (
        clean_action_text in ("send email", "send an email", "send mail", "email someone")
        or any(clean_action_text.startswith(p) for p in email_prefixes)
        or any(clean_low.startswith(p) for p in email_prefixes)
        or "send an email to" in clean_action_text
        or "send email to" in clean_action_text
        or "send mail to" in clean_action_text
    ):
        res = await execute_send_email(text, dry_run=dry_run)
        return {
            "handled": True,
            "intent": "SEND_EMAIL",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Intercept camera visual understanding queries
    if _is_camera_vision_query(text):
        res = await execute_camera_vision_query(text, dry_run=dry_run)
        return {
            "handled": True,
            "intent": "CAMERA_VISION_QUERY",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Intercept camera control commands
    camera_keywords = (
        "turn on camera", "turn on the camera", "open camera", "open the camera",
        "start camera", "start the camera", "enable camera", "enable the camera",
        "turn camera on", "switch on camera", "activate camera", "launch camera",
        "turn on webcam", "open webcam", "start webcam", "enable webcam"
    )
    if clean_action_text in camera_keywords or any(clean_action_text.startswith(k + " ") for k in camera_keywords):
        set_camera_active_state(True)
        return {
            "handled": True,
            "intent": "TURN_ON_CAMERA",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": "Camera viewport activated."
        }

    # Intercept camera turn off / close commands
    camera_off_keywords = (
        "turn off camera", "turn off the camera", "close camera", "close the camera",
        "stop camera", "stop the camera", "disable camera", "disable the camera",
        "turn camera off", "switch off camera", "deactivate camera",
        "turn off webcam", "close webcam", "stop webcam", "disable webcam", "shut off camera"
    )
    if clean_action_text in camera_off_keywords or any(clean_action_text.startswith(k + " ") for k in camera_off_keywords):
        set_camera_active_state(False)
        return {
            "handled": True,
            "intent": "TURN_OFF_CAMERA",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": "Camera viewport closed."
        }

    # Intercept screen sharing commands
    screen_share_keywords = (
        "turn on screen sharing", "turn on screen share", "start screen share",
        "start screen sharing", "share my screen", "share the screen", "share screen",
        "screen share", "enable screen share", "enable screen sharing",
        "begin screen share", "begin screen sharing", "activate screen share",
        "start sharing my screen", "toggle screen share"
    )
    if clean_action_text in screen_share_keywords or any(clean_action_text.startswith(k + " ") for k in screen_share_keywords):
        return {
            "handled": True,
            "intent": "SCREEN_SHARE",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": "Screen sharing started."
        }

    # Intercept calendar scheduling commands
    calendar_prefixes = (
        "schedule a meeting", "schedule an event", "schedule meeting", "schedule event",
        "create a meeting", "create an event", "create meeting", "create event",
        "add a meeting", "add an event", "schedule a call", "set up a meeting",
        "book a meeting", "set a meeting"
    )
    if any(clean_low.startswith(p) for p in calendar_prefixes) or "in my calendar" in clean_low or "in google calendar" in clean_low or "on google calendar" in clean_low:
        res = await execute_calendar_event(text, dry_run=dry_run)
        return {
            "handled": True,
            "intent": "CREATE_CALENDAR_EVENT",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    # Intercept system resource, hardware status, health awareness, network connectivity, and device queries
    is_resource_query = False
    resource_keywords = (
        "ram", "memory", "cpu", "processor", "battery", "charging",
        "storage", "disk", "hard drive", "drive space", "free space",
        "running low", "low space", "low disk", "low storage",
        "heavy load", "high load", "under load", "under heavy load",
        "system status", "system health", "system info", "system information",
        "computer status", "laptop status", "how is my computer", "how is my system",
        "check my system", "check computer", "system details"
    )
    network_keywords = (
        "internet", "wifi", "wi-fi", "ssid",
        "local ip", "public ip", "external ip", "my ip", "ip address",
        "ping", "latency", "network status", "network health", "network info",
        "connection stable", "internet stable", "is my connection",
        "uploaded", "downloaded", "bandwidth", "data usage", "network usage",
        "network connection", "am i connected", "are we connected", "are we online"
    )
    device_keywords = (
        "volume level", "what is my volume", "what is the volume", "sound level",
        "audio device", "sound device", "what audio device", "which audio device", "what speaker",
        "microphone available", "microphone working", "is my microphone", "is my mic", "mic working", "mic available",
        "camera available", "camera working", "is my camera", "is my webcam", "webcam available", "webcam working",
        "audio status", "audio health", "sound status"
    )

    action_prefixes = (
        "open ", "launch ", "start ", "run ", "find ", "read ", "search ", "google ",
        "turn on", "turn off", "toggle ", "enable ", "disable ", "send ", "email ", "schedule ", "create ",
        "stop ", "disconnect ", "connect ", "close ", "shut "
    )

    clean_action = re.sub(r"^(?:can\s+you\s+|could\s+you\s+|please\s+)", "", clean_low).strip()
    is_action_command = any(clean_action.startswith(p) for p in action_prefixes)

    if not is_action_command:
        if any(_matches_kw(k, clean_low) for k in resource_keywords):
            is_resource_query = True
        elif any(_matches_kw(k, clean_low) for k in network_keywords):
            is_resource_query = True
        elif any(_matches_kw(k, clean_low) for k in device_keywords):
            is_resource_query = True

    if is_resource_query:
        res = await get_system_info(text)
        return {
            "handled": True,
            "intent": "SYSTEM_INFO",
            "confidence": 1.0,
            "margin": 1.0,
            "trusted": True,
            "fallback": False,
            "result": res
        }

    t_ml_start = time.perf_counter()
    details = predict_intent_details(text, bundle)
    t3 = time.perf_counter()
    if perf_record is not None:
        perf_record["t3_intent"] = t3
        perf_record["intent_duration_ms"] = (t3 - t_ml_start) * 1000.0
    intent = details["intent"]
    confidence = details["confidence"]
    margin = details["margin"]
    trusted = details["trusted"]

    # If ML prediction was not trusted, check explicit keywords for critical power commands or known aliases
    if not trusted:
        clean_low = text.strip().lower()
        if clean_low in ("hi", "hello", "hey", "greetings", "hi there", "hello there", "hey there"):
            intent = "GREETING"
            confidence = 1.0
            margin = 1.0
            trusted = True
        elif clean_low in ("who are you", "what is your name", "what are you", "what can you do", "help me", "what is nexa", "introduce yourself"):
            intent = "GENERAL_CONVERSATION"
            confidence = 1.0
            margin = 1.0
            trusted = True
        elif clean_low in ("thank you", "thanks", "thanks nexa", "thank you nexa", "much obliged", "many thanks", "appreciate it"):
            intent = "THANKS"
            confidence = 1.0
            margin = 1.0
            trusted = True
        elif clean_low in ("bye", "goodbye", "farewell", "see you later", "see you tomorrow", "have a great day", "have a good day", "have a nice day", "have a good evening", "have a nice evening", "have a great evening"):
            intent = "FAREWELL"
            confidence = 1.0
            margin = 1.0
            trusted = True
        elif clean_low in ("restart", "reboot", "restart computer", "restart pc", "restart the computer"):
            intent = "RESTART"
            confidence = 1.0
            margin = 1.0
            trusted = True
        elif clean_low in ("shutdown", "shut down", "power off", "turn off computer", "turn off pc", "shut down computer"):
            intent = "SHUTDOWN"
            confidence = 1.0
            margin = 1.0
            trusted = True
        elif "weather" in clean_low or any(clean_low.startswith(p) for p in ("forecast in", "temperature in", "how is the weather", "what is the weather", "what's the weather")):
            intent = "WEATHER"
            confidence = 1.0
            margin = 1.0
            trusted = True
        elif any(clean_low.startswith(p) for p in ("search the web for ", "search web for ", "google ", "search for ", "look up ")):
            intent = "SEARCH_WEB"
            confidence = 1.0
            margin = 1.0
            trusted = True
        elif any(clean_low.startswith(p) for p in ("dim ", "lower brightness", "decrease brightness", "turn down brightness", "reduce brightness")):
            intent = "DECREASE_BRIGHTNESS"
            confidence = 1.0
            margin = 1.0
            trusted = True
        elif any(clean_low.startswith(p) for p in ("brighten", "increase brightness", "raise brightness", "turn up brightness")):
            intent = "INCREASE_BRIGHTNESS"
            confidence = 1.0
            margin = 1.0
            trusted = True
        elif any(clean_low.startswith(p) for p in ("set brightness", "change brightness", "adjust brightness")):
            intent = "SET_BRIGHTNESS"
            confidence = 1.0
            margin = 1.0
            trusted = True
        elif any(clean_action_text == k or clean_action_text.startswith(k + " ") for k in (
            "turn on camera", "turn on the camera", "open camera", "open the camera",
            "start camera", "start the camera", "enable camera", "enable the camera",
            "turn camera on", "switch on camera", "activate camera", "launch camera",
            "turn on webcam", "open webcam", "start webcam", "enable webcam"
        )):
            intent = "TURN_ON_CAMERA"
            confidence = 1.0
            margin = 1.0
            trusted = True
        elif any(clean_action_text == k or clean_action_text.startswith(k + " ") for k in (
            "turn off camera", "turn off the camera", "close camera", "close the camera",
            "stop camera", "stop the camera", "disable camera", "disable the camera",
            "turn camera off", "switch off camera", "deactivate camera",
            "turn off webcam", "close webcam", "stop webcam", "disable webcam", "shut off camera"
        )):
            intent = "TURN_OFF_CAMERA"
            confidence = 1.0
            margin = 1.0
            trusted = True
        elif any(clean_action_text == k or clean_action_text.startswith(k + " ") for k in (
            "turn on screen sharing", "turn on screen share", "start screen share",
            "start screen sharing", "share my screen", "share the screen", "share screen",
            "screen share", "enable screen share", "enable screen sharing",
            "begin screen share", "begin screen sharing", "activate screen share",
            "start sharing my screen", "toggle screen share"
        )):
            intent = "SCREEN_SHARE"
            confidence = 1.0
            margin = 1.0
            trusted = True
        elif any(clean_action_text == k or clean_action_text.startswith(k + " ") for k in (
            "send email", "send an email", "send mail", "email someone", "write an email", "shoot an email"
        )) or "send an email to" in clean_action_text or "send email to" in clean_action_text:
            intent = "SEND_EMAIL"
            confidence = 1.0
            margin = 1.0
            trusted = True
        else:
            app_candidate = _extract_app_name(text)
            if app_candidate and app_candidate in COMMON_APPS:
                intent = "OPEN_APPLICATION"
                confidence = 1.0
                margin = 1.0
                trusted = True
            else:
                folder_candidate = _extract_folder_name(text)
                if folder_candidate and folder_candidate in COMMON_FOLDERS:
                    intent = "OPEN_FOLDER"
                    confidence = 1.0
                    margin = 1.0
                    trusted = True
                else:
                    file_candidate = _extract_file_name(text)
                    is_find_command = (
                        clean_low.startswith(("find ", "search disk ", "locate ", "where did i save", "where is my file")) or
                        intent == "FIND_FILE"
                    )
                    if is_find_command:
                        intent = "FIND_FILE"
                        confidence = 1.0
                        margin = 1.0
                        trusted = True
                    else:
                        file_triggers = ("open", "view", "read", "show", "access", "document", "file", "pdf", "docx", "txt", "csv", "xlsx")
                        has_file_context = any(w in clean_low for w in file_triggers) or (file_candidate and "." in file_candidate) or (intent == "OPEN_FILE")
                        if has_file_context and file_candidate and _find_files_sync(file_candidate):
                            intent = "OPEN_FILE"
                            confidence = 1.0
                            margin = 1.0
                            trusted = True

    # Low confidence fallback rule
    if not trusted:
        logging.info(f"Low confidence prediction for intent '{intent}' ({confidence:.2f}, margin {margin:.2f}). Falling back to Gemini.")
        if perf_record is not None:
            t_now = time.perf_counter()
            perf_record["t4_routing"] = t_now
            perf_record["routing_duration_ms"] = (t_now - perf_record.get("t3_intent", t_now)) * 1000.0
            perf_record["t5_action"] = t_now
            perf_record["action_duration_ms"] = 0.0
            perf_record["category"] = "Gemini fallback command"
        return {
            "handled": False,
            "intent": intent,
            "confidence": confidence,
            "margin": margin,
            "trusted": False,
            "fallback": True,
            "result": "I'm not sure I understand that request. Could you please rephrase?"
        }


    # High confidence local action execution
    if perf_record is not None:
        t_now = time.perf_counter()
        perf_record["t4_routing"] = t_now
        perf_record["routing_duration_ms"] = (t_now - perf_record.get("t3_intent", t_now)) * 1000.0

    result = ""
    try:
        t_action_start = time.perf_counter()
        if intent == "INCREASE_VOLUME":
            result = await increase_volume()
        elif intent == "DECREASE_VOLUME":
            result = await decrease_volume()
        elif intent == "INCREASE_BRIGHTNESS":
            result = await increase_brightness()
        elif intent == "DECREASE_BRIGHTNESS":
            result = await decrease_brightness()
        elif intent == "SET_BRIGHTNESS":
            result = await set_brightness(text)
        elif intent in SETTINGS_MAP:
            result = await open_settings_pane(intent)
        elif intent == "TURN_ON_WIFI":
            result = await toggle_wifi(enable=True)
        elif intent == "TURN_OFF_WIFI":
            result = await toggle_wifi(enable=False)
        elif intent == "TURN_ON_BLUETOOTH":
            result = await toggle_bluetooth(enable=True)
        elif intent == "TURN_OFF_BLUETOOTH":
            result = await toggle_bluetooth(enable=False)
        elif intent == "RESTART":
            result = await restart_system(confirmed=confirmed, dry_run=dry_run)
        elif intent == "SHUTDOWN":
            result = await shutdown_system(confirmed=confirmed, dry_run=dry_run)
        elif intent in ("GET_SYSTEM_INFO", "SYSTEM_INFO"):
            result = await get_system_info(text)
        elif intent == "GET_TIME":
            result = await get_current_time()
        elif intent == "GET_DATE":
            result = await get_current_date()
        elif intent == "OPEN_APPLICATION":
            result = await open_application(text)
        elif intent == "CLOSE_APPLICATION":
            result = await close_application_action(text, dry_run=dry_run)
        elif intent == "INSPECT_APPLICATIONS":
            result = await inspect_applications_action(text)
        elif intent == "OPEN_FOLDER":
            result = await open_folder(text)
        elif intent == "OPEN_FILE":
            result = await open_file(text)
        elif intent == "FIND_FILE":
            result = await find_file(text)
        elif intent == "SEARCH_WEB":
            result = await execute_web_search(text, run_context, dry_run=dry_run)
        elif intent == "BROWSER_SELECT_RESULT":
            result = await execute_browser_select_result(text, dry_run=dry_run)
        elif intent == "BROWSER_CONTROL":
            action = _extract_browser_nav_action(text) or "scroll_down"
            result = await execute_browser_control(action, dry_run=dry_run)
        elif intent == "WEATHER":
            result = await execute_weather(text, run_context)
        elif intent == "MUTE_VOLUME":
            result = await mute_system_volume(mute=True, dry_run=dry_run)
        elif intent == "UNMUTE_VOLUME":
            result = await mute_system_volume(mute=False, dry_run=dry_run)
        elif intent == "MUTE_MICROPHONE":
            result = await mute_microphone(mute=True, dry_run=dry_run)
        elif intent == "UNMUTE_MICROPHONE":
            result = await mute_microphone(mute=False, dry_run=dry_run)
        elif intent == "SEND_EMAIL":
            result = await execute_send_email(text, dry_run=dry_run)
        elif intent == "TURN_ON_CAMERA":
            if _is_camera_vision_query(text):
                result = await execute_camera_vision_query(text, dry_run=dry_run)
            else:
                set_camera_active_state(True)
                result = "Camera viewport activated."
        elif intent == "TURN_OFF_CAMERA":
            set_camera_active_state(False)
            result = "Camera viewport closed."
        elif intent == "CAMERA_VISION_QUERY":
            result = await execute_camera_vision_query(text, dry_run=dry_run)
        elif intent == "VISUAL_PRODUCT_SEARCH":
            result = await execute_visual_product_search(text, dry_run=dry_run)
        elif intent == "SCREEN_SHARE":
            result = "Screen sharing started."
        elif intent == "SCREEN_UNDERSTANDING":
            result = await execute_screen_understanding(text, dry_run=dry_run)
        elif intent in ("CREATE_CALENDAR_EVENT", "CALENDAR"):
            result = await execute_calendar_event(text, dry_run=dry_run)
        elif intent == "FAREWELL":
            result = "Goodbye! Have a great day!"
        elif intent == "GREETING":
            result = "Hello! How can I help you today?"
        elif intent == "THANKS":
            result = "You're welcome! Let me know if there's anything else I can do."
        elif intent == "GENERAL_CONVERSATION":
            clean_conv = text.strip().lower()
            if any(k in clean_conv for k in ("who are you", "what are you", "what is your name", "who made you")):
                result = "I am NEXA, your Windows desktop AI assistant."
            elif any(k in clean_conv for k in ("what can you do", "what are your capabilities", "help", "commands")):
                result = "I can manage your desktop applications, check hardware and network stats, control volume and brightness, send emails, schedule calendar events, set reminders, store memories, and search the web."
            else:
                result = "I am here to assist you with system tasks, applications, and productivity."
        elif intent == "SET_REMINDER":
            try:
                from backend.tools import set_reminder
            except ImportError:
                from tools import set_reminder  # type: ignore

            is_cap_or_inc, rem_prompt = _is_reminder_capability_or_incomplete(clean_low)
            if is_cap_or_inc:
                _PENDING_REMINDER_STATE = {"step": "details"}
                result = rem_prompt
            else:
                rem_text, rem_time = _parse_reminder_text_and_time(text)
                result = await set_reminder(context=None, reminder_text=rem_text, target_time=rem_time)
        elif intent == "SHOW_REMINDERS":
            try:
                from backend.tools import show_reminders
            except ImportError:
                from tools import show_reminders  # type: ignore
            result = await show_reminders(context=None)
        elif intent in ("CANCEL_REMINDER", "CANCEL_ALL_REMINDERS"):
            try:
                from backend.tools import cancel_reminder, cancel_all_reminders
            except ImportError:
                from tools import cancel_reminder, cancel_all_reminders  # type: ignore
            m_id = re.search(r"\b(\d+)\b", text)
            if "all" in text.lower():
                result = await cancel_all_reminders(context=None)
            elif m_id:
                result = await cancel_reminder(context=None, reminder_id=int(m_id.group(1)))
            else:
                result = await cancel_all_reminders(context=None)
        elif intent == "REMEMBER_FACT":
            try:
                from backend.tools import remember_fact
            except ImportError:
                from tools import remember_fact  # type: ignore
            fact = re.sub(
                r"^(?:please\s+)?(?:remember\s+that\s+|remember\s+this:?\s*|remember\s+|save\s+(?:this\s+)?(?:in|to)\s+memory:?\s*|note\s+that\s+)",
                "",
                text,
                flags=re.I
            ).strip()
            result = await remember_fact(context=None, fact=fact or text)
        elif intent == "SEARCH_MEMORIES":
            try:
                from backend.tools import search_memories
            except ImportError:
                from tools import search_memories  # type: ignore
            query = re.sub(
                r"^(?:please\s+)?(?:what\s+do\s+you\s+remember\s+(?:about\s+)?|what\s+did\s+i\s+tell\s+you\s+(?:about\s+)?|what\s+do\s+you\s+know\s+about\s+|search\s+memory\s+(?:for\s+)?|check\s+memory\s+(?:for\s+)?)",
                "",
                text,
                flags=re.I
            ).strip(" ?.")
            result = await search_memories(context=None, query=query or "user")
        elif intent == "FORGET_MEMORY":
            try:
                from backend.tools import forget_memory
            except ImportError:
                from tools import forget_memory  # type: ignore
            query = re.sub(
                r"^(?:please\s+)?(?:forget\s+that\s+|forget\s+what\s+you\s+remember\s+(?:about\s+)?|forget\s+|delete\s+memory\s+(?:about\s+)?|remove\s+memory\s+(?:about\s+)?)",
                "",
                text,
                flags=re.I
            ).strip(" ?.")
            result = await forget_memory(context=None, query=query or text)
        elif intent == "CREATE_CALENDAR_EVENT":
            result = await execute_calendar_event(text, dry_run=dry_run)
        elif intent == "SYSTEM_INFO":
            result = await get_system_info(text)
        elif intent == "CANCEL_REMINDER":
            rem_id = None
            id_match = re.search(r"\b(?:id|number|#)?\s*(\d+)\b", text, re.I)
            if id_match:
                rem_id = int(id_match.group(1))
            rem_text = re.sub(
                r"^(?:please\s+)?(?:cancel|delete|remove|stop)\s+(?:the\s+|my\s+)?(?:reminder|timer)\s*(?:for|to|about|#|\d+)?\s*",
                "",
                text,
                flags=re.I
            ).strip()
            try:
                from backend.tools import cancel_reminder
            except ImportError:
                from tools import cancel_reminder  # type: ignore
            result = await cancel_reminder(context=None, reminder_id=rem_id, reminder_text=rem_text or None)
        else:
            logging.warning(f"No desktop action handler configured for intent '{intent}'")
            return {
                "handled": False,
                "intent": intent,
                "confidence": confidence,
                "margin": margin,
                "trusted": True,
                "fallback": True,
                "result": "I'm not sure how to handle that request directly. Let me check."
            }

        t_action_end = time.perf_counter()
        if perf_record is not None:
            perf_record["t5_action"] = t_action_end
            perf_record["action_duration_ms"] = (t_action_end - t_action_start) * 1000.0
            if "category" not in perf_record:
                if intent in ("GET_TIME", "GET_DATE", "OPEN_APPLICATION", "OPEN_FILE"):
                    perf_record["category"] = "Local desktop action"
                else:
                    perf_record["category"] = "Local ML command"

        return {
            "handled": True,
            "intent": intent,
            "confidence": confidence,
            "margin": margin,
            "trusted": True,
            "fallback": False,
            "result": result
        }

    except Exception as e:
        if perf_record is not None and "t5_action" not in perf_record:
            perf_record["t5_action"] = time.perf_counter()
            perf_record["action_duration_ms"] = (perf_record["t5_action"] - t_action_start) * 1000.0
            perf_record["category"] = "Local desktop action"
        logging.error(f"Error executing desktop action for intent '{intent}': {e}")
        return {
            "handled": False,
            "intent": intent,
            "confidence": confidence,
            "margin": margin,
            "trusted": True,
            "fallback": True,
            "result": "Sorry, I encountered an issue while performing that action."
        }


# ---------------------------------------------------------
# Local Speech Intent Dispatcher (Priority 1)
# ---------------------------------------------------------

SUPPORTED_LOCAL_SPEECH_INTENTS = {
    "SET_REMINDER",
    "SHOW_REMINDERS",
    "CANCEL_REMINDER",
    "CANCEL_ALL_REMINDERS",
}


async def handle_local_speech_intent(text: str) -> Optional[Dict[str, Any]]:
    """
    Evaluates user speech text for high-confidence supported local intents (beginning with SET_REMINDER).
    
    If the utterance is a supported deterministic intent (e.g. SET_REMINDER, SHOW_REMINDERS, CANCEL_REMINDER),
    it is executed locally using existing handlers and storage, ensuring reliable execution even if Gemini Realtime
    glitches or fails to emit tool calls.
    
    If the utterance is general conversation, greeting, unsupported intent, or low-confidence, returns None
    so that Gemini Realtime voice handles it naturally without interruption.
    """
    if not text or not text.strip():
        return None

    clean_low = text.strip().lower()
    is_supported = False

    # 1. Multi-turn pending reminder state active
    global _PENDING_REMINDER_STATE
    if _PENDING_REMINDER_STATE is not None:
        is_supported = True

    # 2. Cancel all reminders
    elif any(k in clean_low for k in (
        "cancel all reminders", "delete all reminders", "clear all reminders",
        "remove all reminders", "stop all timers", "cancel all my reminders"
    )):
        is_supported = True

    # 3. Cancel specific reminder
    elif any(clean_low.startswith(p) for p in (
        "cancel reminder", "delete reminder", "remove reminder", "stop timer",
        "cancel timer", "delete timer", "cancel my reminder", "delete my reminder"
    )):
        is_supported = True

    # 4. Show reminders
    elif any(k in clean_low for k in (
        "show reminders", "show my reminders", "list reminders", "list my reminders",
        "what reminders", "view reminders", "view my reminders", "check reminders",
        "check my reminders", "pending reminders", "check timers"
    )) or clean_low in ("my reminders", "reminders", "timers"):
        is_supported = True

    # 5. Set reminder prefix / patterns
    elif any(clean_low.startswith(p) for p in (
        "remind me ", "set a reminder", "set reminder", "set a timer", "set timer", "please remind me"
    )):
        is_supported = True

    # 6. Reminder capability or incomplete command
    elif _is_reminder_capability_or_incomplete(clean_low)[0]:
        is_supported = True

    # 7. ML classifier check if not matched by explicit rules
    if not is_supported:
        bundle = get_model_bundle()
        if bundle and predict_intent_details is not None:
            details = predict_intent_details(text, bundle)
            if (
                details.get("intent") in SUPPORTED_LOCAL_SPEECH_INTENTS
                and details.get("trusted", False)
            ):
                is_supported = True

    if not is_supported:
        return None

    # Execute deterministically via master route_intent
    route_res = await route_intent(text=text)
    if route_res.get("handled") and route_res.get("intent") in SUPPORTED_LOCAL_SPEECH_INTENTS:
        return route_res

    return None


# ---------------------------------------------------------
# Local Email Approval Dispatcher (Priority 1)
# ---------------------------------------------------------

EXPLICIT_EMAIL_APPROVAL_PHRASES = (
    "yes",
    "yeah",
    "yep",
    "sure",
    "approve",
    "confirm",
    "send",
    "send it",
    "send email",
    "send the email",
    "send that email",
    "send an email",
    "go ahead",
    "go ahead and send",
    "go ahead and send it",
    "go ahead and send email",
    "go ahead and send the email",
    "go ahead and send that email",
    "go ahead and send an email",
    "i approve",
    "i approve it",
    "i approve that",
    "i approve that email",
    "i approve the email",
    "i approve that send the email",
    "i approve that so send that email",
    "i approve that so send the email",
    "i approve that send that email",
    "i approve sending that email",
    "i approve sending the email",
    "approve email",
    "approve the email",
    "approve and send",
    "approve and send email",
    "approve and send the email",
    "approve it",
    "yes send",
    "yes send it",
    "yes send the email",
    "yes send that email",
    "yes send an email",
    "yes please",
    "yes please send",
    "yes please send it",
    "yes please send the email",
    "yes please send that email",
    "yes go ahead",
    "yes go ahead and send",
    "yes go ahead and send it",
    "yes go ahead and send email",
    "yes go ahead and send the email",
    "yes go ahead and send that email",
    "yes go ahead and send an email",
    "confirm and send",
    "confirm and send email",
    "confirm and send the email",
    "confirm email",
    "confirm the email",
)

EXPLICIT_EMAIL_CANCEL_PHRASES = (
    "no",
    "nope",
    "nah",
    "cancel",
    "cancel email",
    "cancel the email",
    "cancel that email",
    "don't send",
    "dont send",
    "do not send",
    "don't send it",
    "dont send it",
    "don't send the email",
    "dont send the email",
    "don't send that email",
    "dont send that email",
    "don't send an email",
    "dont send an email",
    "discard",
    "discard email",
    "discard the email",
    "discard that email",
    "abort",
    "abort email",
    "abort the email",
    "abort that email",
    "stop",
    "never mind",
    "nevermind",
    "never mind cancel the email",
    "nevermind cancel the email",
)


def _is_explicit_email_cancellation(clean_text: str) -> bool:
    """Returns True if the utterance is an unambiguous cancellation command."""
    if not clean_text:
        return False
    if clean_text in ("no", "nope", "nah", "cancel", "discard", "abort", "stop", "nevermind", "never mind"):
        return True
    if any(clean_text == p or clean_text.startswith(p + " ") or clean_text.endswith(" " + p) for p in EXPLICIT_EMAIL_CANCEL_PHRASES):
        return True
    if clean_text.startswith(("no ", "nope ", "nah ", "dont ", "don't ")):
        return True
    return False


def _is_explicit_email_approval(clean_text: str) -> bool:
    """
    Returns True if the utterance is an unambiguous approval/send command.
    Strictly rejects any modification, condition, or hesitation keywords.
    """
    if not clean_text:
        return False

    # 1. Reject any utterance containing modification, condition, or hesitation terms
    words = set(clean_text.split())
    mod_terms = {"but", "change", "wait", "modify", "edit", "instead", "update", "replace", "except", "not", "dont", "don't"}
    if words.intersection(mod_terms):
        return False

    # 2. Exact single-word affirmations
    if clean_text in ("yes", "yeah", "yep", "sure", "approve", "confirm", "send"):
        return True

    # 3. Explicit listed phrases
    if any(clean_text == p or clean_text.startswith(p + " ") or clean_text.endswith(" " + p) for p in EXPLICIT_EMAIL_APPROVAL_PHRASES):
        return True

    # 4. Prefixed affirmations without modification terms (e.g. "yes go ahead and send an email", "yes please", "sure go ahead")
    if clean_text.startswith(("yes ", "yeah ", "yep ", "sure ", "please ")):
        return True

    return False


async def handle_local_email_approval(
    text: str,
    session_id: str,
    user_authorized: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Evaluates speech text strictly from the local microphone worker when an unexpired
    staged email exists for the session.
    
    CRITICAL SECURITY GUARANTEES:
    1. Only evaluates if an unexpired email draft exists for session_id.
    2. Only explicit, unambiguous approval phrases authorize dispatch.
    3. Modification requests (e.g. 'yes, but change the subject') are rejected (fail closed).
    4. Ambiguous phrases return None (fail closed to conversation).
    5. Tokens, passwords, and credentials are never logged or exposed.
    """
    if not text or not text.strip():
        return None

    try:
        from backend.tools import (
            has_pending_email_for_session,
            get_pending_email_for_session,
            clear_pending_email_for_session,
            dispatch_staged_email,
        )
    except ImportError:
        from tools import (  # type: ignore
            has_pending_email_for_session,
            get_pending_email_for_session,
            clear_pending_email_for_session,
            dispatch_staged_email,
        )

    clean_sid = (session_id or "").strip()
    if not clean_sid or not has_pending_email_for_session(clean_sid):
        return None

    clean_text = re.sub(r"[^\w\s]", " ", text.lower()).strip()
    clean_text = " ".join(clean_text.split())

    # Check explicit cancellation
    if _is_explicit_email_cancellation(clean_text):
        clear_pending_email_for_session(clean_sid)
        logging.info(
            "EMAIL_CONFIRMATION_RECOGNIZED: session_id=%s, intent=CANCEL_EMAIL, phrase='%s'",
            clean_sid,
            clean_text,
        )
        spoken_response = "Your email draft has been cancelled."
        logging.info(
            "EMAIL_APPROVAL_FINAL_RESPONSE: session_id=%s, status=CANCELLED, response='%s'",
            clean_sid,
            spoken_response,
        )
        return {
            "handled": True,
            "intent": "CANCEL_EMAIL",
            "status": "CANCELLED",
            "result": "Email draft cancelled. The draft has been discarded.",
            "spoken_response": spoken_response,
        }

    # Check explicit approval (strictly rejecting modification requests)
    if not _is_explicit_email_approval(clean_text):
        # Ambiguous or non-approval utterance - fail closed without dispatching
        return None

    # Retrieve staged draft
    staged = get_pending_email_for_session(clean_sid)
    if not staged:
        return {
            "handled": True,
            "intent": "APPROVE_EMAIL",
            "status": "FAILED",
            "result": "Cannot send email: No pending email draft was found for this session.",
            "spoken_response": "Cannot send email: No pending email draft was found for this session.",
        }

    token = staged.get("token", "")
    target_to = staged.get("to_email", "")

    logging.info(
        "EMAIL_CONFIRMATION_RECOGNIZED: session_id=%s, intent=APPROVE_EMAIL, phrase='%s'",
        clean_sid,
        clean_text,
    )

    dispatch_res = await dispatch_staged_email(
        session_id=clean_sid,
        confirmation_token=token,
        user_authorized=user_authorized,
    )

    lower_res = (dispatch_res or "").lower()
    if "uncertain" in lower_res:
        status = "UNCERTAIN"
        spoken_response = dispatch_res
    elif "successfully" in lower_res and not lower_res.startswith("notice:"):
        status = "SUCCESS"
        spoken_response = "Your email has been sent successfully."
    elif lower_res.startswith("notice: duplicate"):
        status = "DUPLICATE"
        spoken_response = dispatch_res
    else:
        status = "FAILED"
        spoken_response = dispatch_res

    logging.info(
        "EMAIL_APPROVAL_FINAL_RESPONSE: session_id=%s, status=%s, response='%s'",
        clean_sid,
        status,
        spoken_response,
    )

    return {
        "handled": True,
        "intent": "APPROVE_EMAIL",
        "status": status,
        "result": dispatch_res,
        "spoken_response": spoken_response,
    }


# ---------------------------------------------------------
# Local Email Recipient Verification Handler (Phase 1)
# ---------------------------------------------------------

EXPLICIT_RECIPIENT_CONFIRMATION_PHRASES = (
    "yes",
    "yeah",
    "yep",
    "correct",
    "that is correct",
    "that's correct",
    "thats correct",
    "that is right",
    "that's right",
    "thats right",
    "confirm",
    "confirmed",
    "looks good",
    "it is correct",
    "it's correct",
    "its correct",
    "yes that is correct",
    "yes that's correct",
    "yes thats correct",
    "yes correct",
    "yes it is",
    "yes that's right",
    "yes thats right",
    "proceed",
    "go ahead",
    "yes proceed",
    "yes go ahead",
)

EXPLICIT_RECIPIENT_CANCELLATION_PHRASES = (
    "no",
    "nope",
    "nah",
    "cancel",
    "cancel email",
    "cancel verification",
    "stop",
    "abort",
    "don't send",
    "dont send",
    "never mind",
    "nevermind",
    "no cancel",
    "discard",
)


def _is_explicit_recipient_cancellation(clean_text: str) -> bool:
    """Returns True if the utterance is an unambiguous cancellation command for recipient verification."""
    if not clean_text:
        return False
    if clean_text in ("no", "nope", "nah", "cancel", "discard", "abort", "stop", "nevermind", "never mind"):
        return True
    if any(clean_text == p or clean_text.startswith(p + " ") or clean_text.endswith(" " + p) for p in EXPLICIT_RECIPIENT_CANCELLATION_PHRASES):
        return True
    if clean_text.startswith(("no ", "nope ", "nah ", "dont ", "don't ")):
        return True
    return False


def _is_explicit_recipient_confirmation(clean_text: str) -> bool:
    """
    Returns True if the utterance is an unambiguous confirmation of the candidate recipient.
    Strictly rejects any modification, condition, or hesitation keywords.
    """
    if not clean_text:
        return False

    # 1. Reject any utterance containing modification, correction, or hesitation terms
    words = set(clean_text.split())
    mod_terms = {"but", "change", "wait", "modify", "edit", "instead", "update", "replace", "except", "not", "dont", "don't", "wrong", "different"}
    if words.intersection(mod_terms):
        return False

    # 2. Exact single-word affirmations
    if clean_text in ("yes", "yeah", "yep", "correct", "confirm", "proceed"):
        return True

    # 3. Explicit listed phrases
    if any(clean_text == p or clean_text.startswith(p + " ") or clean_text.endswith(" " + p) for p in EXPLICIT_RECIPIENT_CONFIRMATION_PHRASES):
        return True

    # 4. Prefixed affirmations without modification terms (e.g. "yes that is correct", "yes please", "sure that is right")
    if clean_text.startswith(("yes ", "yeah ", "yep ", "sure ")):
        return True

    return False


async def handle_local_recipient_verification(
    text: str,
    session_id: str,
    user_authorized: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Evaluates speech text strictly from the local microphone worker when an unexpired
    candidate recipient verification is pending for the session.

    SECURITY GUARANTEES:
    1. Only evaluates if an unexpired candidate recipient verification exists for session_id.
    2. Recipient confirmation only verifies candidate address and stages draft; it NEVER dispatches SMTP.
    3. Corrections update candidate address and reset verification to False, requiring explicit re-confirmation.
    4. Cancellation discards the candidate draft without staging.
    5. Ambiguous utterances fail closed and re-prompt the candidate address.
    """
    if not text or not text.strip():
        return None

    try:
        from backend.tools import (
            has_pending_recipient_verification_for_session,
            get_pending_recipient_verification_for_session,
            update_pending_recipient_for_session,
            confirm_pending_recipient_for_session,
            cancel_pending_recipient_verification_for_session,
        )
    except ImportError:
        from tools import (  # type: ignore
            has_pending_recipient_verification_for_session,
            get_pending_recipient_verification_for_session,
            update_pending_recipient_for_session,
            confirm_pending_recipient_for_session,
            cancel_pending_recipient_verification_for_session,
        )

    clean_sid = (session_id or "").strip()
    if not clean_sid or not has_pending_recipient_verification_for_session(clean_sid):
        return None

    pending = get_pending_recipient_verification_for_session(clean_sid)
    if not pending:
        return None

    candidate_to = pending.get("candidate_to", "")

    # 1. Check if the user is providing a new / corrected email address
    m_email = re.search(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}", text)
    if m_email:
        new_address = m_email.group(0).strip()
        success, prompt_str = update_pending_recipient_for_session(clean_sid, new_address)
        if success:
            logging.info(
                "RECIPIENT_VERIFICATION_CORRECTED: session_id=%s, previous_to=%s, new_to=%s",
                clean_sid,
                candidate_to,
                new_address,
            )
            spoken_response = f"I've updated the recipient to {new_address}. Is this address correct? Please answer YES to proceed, provide a correction, or say CANCEL."
            return {
                "handled": True,
                "intent": "CORRECT_RECIPIENT",
                "status": "CORRECTED",
                "candidate_recipient": new_address,
                "spoken_response": spoken_response,
                "result": prompt_str,
            }

    clean_text = re.sub(r"[^\w\s]", " ", text.lower()).strip()
    clean_text = " ".join(clean_text.split())

    # 2. Check explicit cancellation
    if _is_explicit_recipient_cancellation(clean_text):
        cancel_pending_recipient_verification_for_session(clean_sid)
        logging.info(
            "RECIPIENT_VERIFICATION_CANCELLED: session_id=%s, phrase='%s'",
            clean_sid,
            clean_text,
        )
        spoken_response = "Recipient verification cancelled. The email draft has been discarded."
        return {
            "handled": True,
            "intent": "CANCEL_RECIPIENT_VERIFICATION",
            "status": "CANCELLED",
            "spoken_response": spoken_response,
            "result": "Recipient verification cancelled. Email draft discarded.",
        }

    # 3. Check explicit confirmation
    if _is_explicit_recipient_confirmation(clean_text):
        ok, staged, summary = confirm_pending_recipient_for_session(clean_sid, user_authorized=user_authorized)
        if ok and staged:
            logging.info(
                "RECIPIENT_VERIFICATION_CONFIRMED: session_id=%s, verified_to=%s",
                clean_sid,
                candidate_to,
            )
            spoken_response = (
                f"Recipient confirmed as {candidate_to}. I have prepared and staged your email draft for review. "
                "Would you like me to send this email? Please answer YES to send or NO to cancel."
            )
            return {
                "handled": True,
                "intent": "CONFIRM_RECIPIENT",
                "status": "VERIFIED",
                "verified_recipient": candidate_to,
                "spoken_response": spoken_response,
                "result": summary,
                "staged_draft": staged,
            }

    # 4. Ambiguous or unrecognized utterance - fail closed and re-prompt candidate address
    logging.info(
        "RECIPIENT_VERIFICATION_REJECTED: session_id=%s, text='%s', candidate_to=%s",
        clean_sid,
        clean_text,
        candidate_to,
    )
    spoken_response = f"Please confirm if the recipient address '{candidate_to}' is correct by answering YES, provide a corrected email address, or say CANCEL."
    return {
        "handled": True,
        "intent": "RECIPIENT_VERIFICATION_AMBIGUOUS",
        "status": "AMBIGUOUS",
        "candidate_recipient": candidate_to,
        "spoken_response": spoken_response,
        "result": f"Ambiguous response. Recipient '{candidate_to}' not verified. Answer YES to confirm, provide correct address, or say CANCEL.",
    }

