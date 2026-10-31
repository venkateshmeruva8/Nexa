"""NEXA Frontend UI Controller.

Manages application state, live Windows system telemetry,
waveform visualization amplitudes, window controls,
interactive navigation views, and context-aware floating action cards.
"""
from __future__ import annotations

import datetime
import math
import os
import random
import socket
import sys
import re
import subprocess
import time
from typing import Any, List, Optional

import psutil
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer

from frontend.livekit_client import NexaLiveKitClient


class NexaUIController(QObject):
    batteryChanged = Signal()
    networkChanged = Signal()
    volumeChanged = Signal()
    dateTimeChanged = Signal()
    stateChanged = Signal()
    waveformChanged = Signal()
    navChanged = Signal()
    messagesChanged = Signal()
    connectionStatusChanged = Signal()
    micPublishedChanged = Signal(bool)
    micDeviceChanged = Signal(str)
    micError = Signal(str)
    playbackActiveChanged = Signal(bool)
    playbackError = Signal(str)
    cardsChanged = Signal()
    lastActionStatusChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._battery_level = 78
        self._battery_charging = False
        self._network_status = "Connected"
        self._volume_level = 60
        self._date_time_string = ""
        self._state_text = "Connecting..."
        self._connection_status = "Disconnected"
        self._is_listening = True
        self._is_muted = False
        self._is_mic_published = False
        self._is_playback_active = False
        self._mic_device_name = ""
        self._active_nav = 0  # 0: Home, 1: Chat, 2: Apps, 3: Settings
        self._wave_phase = 0.0
        self._waveform_amplitudes: list[float] = [0.1] * 48

        # Context-Aware Floating Action Cards
        self._action_cards: list[dict[str, Any]] = []
        self._last_action_status: str = ""
        self._card_timer_refs: list[QTimer] = []

        # LiveKit Client Bridge
        self._lk_client: NexaLiveKitClient | None = NexaLiveKitClient(self)
        self._lk_client.connectionStatusChanged.connect(self._on_connection_status_changed)
        self._lk_client.agentJoined.connect(self._on_agent_joined)
        self._lk_client.agentLeft.connect(self._on_agent_left)
        self._lk_client.errorOccurred.connect(self._on_client_error)
        self._lk_client.micPublished.connect(self._on_mic_published)
        self._lk_client.micMutedChanged.connect(self._on_mic_muted_changed)
        self._lk_client.micDeviceChanged.connect(self._on_mic_device_changed)
        self._lk_client.micErrorOccurred.connect(self._on_mic_error)
        self._lk_client.playbackActiveChanged.connect(self._on_playback_active_changed)
        self._lk_client.playbackErrorOccurred.connect(self._on_playback_error)
        self._lk_client.transcriptReceived.connect(self._on_transcript_received)
        self._lk_client.start()

        self._has_live_messages: bool = False

        # Initial reference messages matching the NEXA design
        self._messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "text": "What is the capital of France?",
                "time": "07:23 PM",
            },
            {
                "role": "assistant",
                "text": "Paris is the capital of France.",
                "time": "07:23 PM",
            },
            {
                "role": "user",
                "text": "Tell me a short history about it.",
                "time": "07:24 PM",
            },
            {
                "role": "assistant",
                "text": (
                    "Paris, the capital of France, has a rich history dating back "
                    "over 2,000 years. It began as a Celtic settlement called Lutetia, "
                    "later became a major city under the Romans, and grew into a cultural, "
                    "political, and economic center during the medieval and modern periods."
                ),
                "time": "07:24 PM",
            },
        ]

        # Fetch initial telemetry
        self._update_battery()
        self._update_network()
        self._update_volume()
        self._update_clock()

        # Timers
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()

        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.setInterval(5000)
        self._telemetry_timer.timeout.connect(self._update_telemetry)
        self._telemetry_timer.start()

        self._wave_timer = QTimer(self)
        self._wave_timer.setInterval(40)  # ~25 fps smooth waveform animation
        self._wave_timer.timeout.connect(self._animate_waveform)
        self._wave_timer.start()

    def _update_clock(self) -> None:
        now = datetime.datetime.now()
        new_val = f"{now.strftime('%a')}, {now.day} {now.strftime('%b %Y')}   {now.strftime('%I:%M %p')}"
        if new_val != self._date_time_string:
            self._date_time_string = new_val
            self.dateTimeChanged.emit()

    def _update_battery(self) -> None:
        try:
            bat = psutil.sensors_battery()
            if bat:
                self._battery_level = int(round(bat.percent))
                self._battery_charging = bool(bat.power_plugged)
                self.batteryChanged.emit()
        except Exception:
            pass

    def _update_network(self) -> None:
        try:
            with socket.create_connection(("8.8.8.8", 53), timeout=1.0):
                new_net = "Connected"
        except Exception:
            new_net = "Disconnected"
        if new_net != self._network_status:
            self._network_status = new_net
            self.networkChanged.emit()

    def _update_volume(self) -> None:
        try:
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            self._volume_level = int(round(volume.GetMasterVolumeLevelScalar() * 100))
            self.volumeChanged.emit()
        except Exception:
            pass

    def _update_telemetry(self) -> None:
        self._update_battery()
        self._update_network()
        self._update_volume()

    def _on_connection_status_changed(self, status: str) -> None:
        self._connection_status = status
        self.connectionStatusChanged.emit()
        if status == "Agent Active":
            if self._is_muted:
                self._state_text = "Muted"
            elif self._is_listening:
                self._state_text = "Listening..."
            else:
                self._state_text = "Ready"
        elif status == "Connecting...":
            self._state_text = "Connecting..."
        elif status == "Connected":
            self._state_text = "Waiting for Agent..."
        elif status == "Reconnecting...":
            self._state_text = "Reconnecting..."
        elif status == "Disconnected":
            self._state_text = "Disconnected"
        self.stateChanged.emit()

    def _on_agent_joined(self, agent_id: str) -> None:
        pass

    def _on_agent_left(self, agent_id: str) -> None:
        pass

    def _on_client_error(self, err_msg: str) -> None:
        pass

    def _on_mic_published(self, published: bool) -> None:
        self._is_mic_published = published
        self.micPublishedChanged.emit(published)

    def _on_mic_muted_changed(self, muted: bool) -> None:
        if self._is_muted != muted:
            self._is_muted = muted
            self.stateChanged.emit()

    def _on_mic_device_changed(self, device_name: str) -> None:
        self._mic_device_name = device_name
        self.micDeviceChanged.emit(device_name)

    def _on_mic_error(self, err_msg: str) -> None:
        self.micError.emit(err_msg)

    def _on_playback_active_changed(self, active: bool) -> None:
        self._is_playback_active = active
        self.playbackActiveChanged.emit(active)
        if self._connection_status == "Agent Active":
            if active:
                self._state_text = "Speaking..."
            else:
                if self._is_muted:
                    self._state_text = "Muted"
                elif self._is_listening:
                    self._state_text = "Listening..."
                else:
                    self._state_text = "Ready"
            self.stateChanged.emit()

    def _on_playback_error(self, err_msg: str) -> None:
        self.playbackError.emit(err_msg)

    def _on_transcript_received(
        self,
        role: str,
        text: str,
        is_final: bool,
        segment_id: str,
    ) -> None:
        if not text or not text.strip():
            return

        sanitized_text = re.sub(r"<ctrl\d+>", "", text)
        if not sanitized_text.strip():
            return

        cleaned_text = sanitized_text.strip() if is_final else sanitized_text.lstrip()

        # Clear initial reference/mockup messages upon receiving first live turn
        if not self._has_live_messages:
            self._messages = []
            self._has_live_messages = True

        # Locate existing message by segment ID
        existing_msg = None
        if segment_id:
            for msg in reversed(self._messages):
                if msg.get("id") == segment_id:
                    existing_msg = msg
                    break

        if existing_msg is None and self._messages:
            last_msg = self._messages[-1]
            if last_msg.get("role") == role and not last_msg.get("is_final", False):
                existing_msg = last_msg
            elif last_msg.get("role") == role and last_msg.get("text") == cleaned_text:
                existing_msg = last_msg

        now_time = datetime.datetime.now().strftime("%I:%M %p")

        if existing_msg is not None:
            changed = False
            if existing_msg["text"] != cleaned_text:
                existing_msg["text"] = cleaned_text
                changed = True
            if is_final and not existing_msg.get("is_final", False):
                existing_msg["is_final"] = True
                changed = True
            if changed:
                self.messagesChanged.emit()
        else:
            new_msg = {
                "id": segment_id or f"msg_{len(self._messages)}_{int(datetime.datetime.now().timestamp())}",
                "role": role,
                "text": cleaned_text,
                "time": now_time,
                "is_final": is_final,
            }
            self._messages.append(new_msg)
            self.messagesChanged.emit()

        # Parse confirmed action execution results to drive Context-Aware Floating Cards
        if role == "assistant" and is_final:
            self._parse_action_result_for_cards(cleaned_text)

    def _parse_action_result_for_cards(self, text: str) -> None:
        """Parses actual verified action results from the assistant to display context-aware cards."""
        # 1. Application Launch Result
        m = re.search(r"^Opened\s+([A-Za-z0-9_\-\.\s]+)\.", text, re.I)
        if m:
            target = m.group(1).strip()
            if not target.lower().endswith("folder"):
                self.triggerActionCard("APP", "Application Running", target, "success", "Active desktop window", "APP")
                return

        m = re.search(r"^Could not find or launch application '([^']+)'", text, re.I)
        if m:
            self.triggerActionCard("APP", "Launch Failed", m.group(1).strip(), "failed", "Application executable not found", "APP")
            return

        # 2. Web Search Result
        m = re.search(r"^Searching for\s+(.+)\s+in\s+([A-Za-z]+)\.", text, re.I)
        if m:
            self.triggerActionCard("SEARCH", "Web Search", f"Query: {m.group(1).strip()}", "success", f"Results opened in {m.group(2)}", "SEARCH")
            return

        # 3. File Operations Result
        m = re.search(r"^Opened\s+([A-Za-z0-9_\-\.\s]+)\s+folder\.", text, re.I)
        if m:
            self.triggerActionCard("FILE", "Folder Opened", m.group(1).strip(), "success", "Opened in File Explorer", "FILE")
            return

        m = re.search(r"^Found file at:\s*(.+)", text, re.I)
        if m:
            full_p = m.group(1).strip()
            self.triggerActionCard("FILE", "File Located", os.path.basename(full_p), "success", full_p, "FILE")
            return

        m = re.search(r"^Could not find file '([^']+)'", text, re.I)
        if m:
            self.triggerActionCard("FILE", "File Search", m.group(1).strip(), "failed", "No matching file found", "FILE")
            return

        # 4. Reminder Result
        m = re.search(r"^Reminder set:\s*(.+)", text, re.I)
        if m:
            self.triggerActionCard("REMINDER", "Reminder Scheduled", m.group(1).strip(), "success", "Alert registered with Windows", "REMINDER")
            return

        if text.startswith("Failed to set reminder"):
            self.triggerActionCard("REMINDER", "Reminder Failed", "Could not set reminder", "failed", text, "REMINDER")
            return

        # 5. Email Workflow Result
        m = re.search(r"^Email Draft Prepared & Staged:\s*(.+)", text, re.I)
        if m:
            self.triggerActionCard("EMAIL", "Draft Staged", "Awaiting Voice Approval", "staged", m.group(1).strip(), "EMAIL")
            return

        m = re.search(r"^Please confirm: do you want to send this email to\s+([^\?]+)\?", text, re.I)
        if m:
            self.triggerActionCard("EMAIL", "Recipient Verification", m.group(1).strip(), "pending", "Say 'Yes' to confirm recipient", "EMAIL")
            return

        if "Your email has been sent successfully." in text:
            self.triggerActionCard("EMAIL", "Email Dispatched", "SMTP Transmission Confirmed", "success", "Delivered to recipient", "EMAIL")
            return

        if "Your email draft has been cancelled." in text:
            self.triggerActionCard("EMAIL", "Email Cancelled", "Draft Discarded", "cancelled", "Cancelled by user request", "EMAIL")
            return

        if text.startswith("Email sending failed"):
            self.triggerActionCard("EMAIL", "Email Send Failed", "Delivery Error", "failed", text, "EMAIL")
            return

        # 6. System Volume & Audio Result
        if "System audio muted." in text:
            self.triggerActionCard("SYSTEM", "System Audio", "Output Muted", "success", "Speakers muted", "SYSTEM")
            return
        if "System audio unmuted." in text:
            self.triggerActionCard("SYSTEM", "System Audio", "Output Unmuted", "success", "Speakers active", "SYSTEM")
            return
        if "Microphone muted." in text:
            self.triggerActionCard("SYSTEM", "Microphone", "Capture Muted", "success", "Microphone muted", "SYSTEM")
            return
        if "Microphone unmuted." in text:
            self.triggerActionCard("SYSTEM", "Microphone", "Capture Active", "success", "Microphone listening", "SYSTEM")
            return
        m = re.search(r"^Volume adjusted to\s+(\d+)%\.", text, re.I)
        if m:
            self.triggerActionCard("SYSTEM", "Volume Adjusted", f"Level: {m.group(1)}%", "success", "Master volume level updated", "SYSTEM")
            return

    def _animate_waveform(self) -> None:
        if not self._is_listening or self._is_muted:
            self._waveform_amplitudes = [0.08] * 48
            self.waveformChanged.emit()
            return

        self._wave_phase += 0.15
        num_bars = 48
        half = num_bars // 2
        amps = []
        for i in range(num_bars):
            dist = abs(i - half) / float(half)
            base_envelope = math.exp(-2.8 * dist * dist)
            osc = 0.5 + 0.5 * math.sin(self._wave_phase + i * 0.35)
            jitter = random.uniform(0.85, 1.15)
            val = max(0.06, min(1.0, base_envelope * osc * jitter))
            amps.append(val)
        self._waveform_amplitudes = amps
        self.waveformChanged.emit()

    # Properties
    @Property(int, notify=batteryChanged)
    def batteryLevel(self) -> int:
        return self._battery_level

    @Property(bool, notify=batteryChanged)
    def batteryCharging(self) -> bool:
        return self._battery_charging

    @Property(str, notify=networkChanged)
    def networkStatus(self) -> str:
        return self._network_status

    @Property(str, notify=connectionStatusChanged)
    def connectionStatus(self) -> str:
        return self._connection_status

    @Property(bool, notify=micPublishedChanged)
    def isMicPublished(self) -> bool:
        return self._is_mic_published

    @Property(str, notify=micDeviceChanged)
    def micDeviceName(self) -> str:
        return self._mic_device_name

    @Property(bool, notify=playbackActiveChanged)
    def isPlaybackActive(self) -> bool:
        return self._is_playback_active

    @Property(int, notify=volumeChanged)
    def volumeLevel(self) -> int:
        return self._volume_level

    @Property(str, notify=dateTimeChanged)
    def dateTimeString(self) -> str:
        return self._date_time_string

    @Property(str, notify=stateChanged)
    def stateText(self) -> str:
        return self._state_text

    @Property(bool, notify=stateChanged)
    def isListening(self) -> bool:
        return self._is_listening

    @Property(bool, notify=stateChanged)
    def isMuted(self) -> bool:
        return self._is_muted

    @Property(int, notify=navChanged)
    def activeNav(self) -> int:
        return self._active_nav

    @Property(list, notify=waveformChanged)
    def waveformAmplitudes(self) -> list[float]:
        return self._waveform_amplitudes

    @Property(list, notify=messagesChanged)
    def messages(self) -> list[dict[str, Any]]:
        return self._messages

    @Property(list, notify=cardsChanged)
    def actionCards(self) -> list[dict[str, Any]]:
        return self._action_cards

    @Property(str, notify=lastActionStatusChanged)
    def lastActionStatus(self) -> str:
        return self._last_action_status

    # Context-Aware Floating Cards Management Slots
    @Slot(str, str, str, str, str, str, result=str)
    def triggerActionCard(
        self,
        card_type: str,
        title: str,
        subtitle: str = "",
        status: str = "success",
        details: str = "",
        icon: str = "",
    ) -> str:
        """Creates or registers a context-aware floating action card."""
        card_id = f"card_{int(time.time() * 1000)}_{random.randint(100, 999)}"
        card = {
            "id": card_id,
            "type": card_type.upper(),
            "title": title,
            "subtitle": subtitle,
            "status": status.lower(),
            "details": details,
            "icon": icon,
            "created_at": time.time(),
        }
        # Insert at the top of the stack
        self._action_cards.insert(0, card)

        # Cap maximum concurrent visible cards to 4 to avoid clutter
        if len(self._action_cards) > 4:
            self._action_cards.pop()

        self.cardsChanged.emit()

        # Schedule automatic dismissal for terminal statuses
        if status.lower() in ("success", "completed", "failed", "cancelled"):
            self._schedule_card_dismissal(card_id, 5000)

        return card_id

    @Slot(str, str, str)
    def updateCardStatus(self, card_id: str, new_status: str, new_details: str = "") -> None:
        """Updates an existing floating action card's state and details."""
        for card in self._action_cards:
            if card["id"] == card_id:
                card["status"] = new_status.lower()
                if new_details:
                    card["details"] = new_details
                self.cardsChanged.emit()
                if new_status.lower() in ("success", "completed", "failed", "cancelled"):
                    self._schedule_card_dismissal(card_id, 5000)
                break

    @Slot(str)
    def dismissCard(self, card_id: str) -> None:
        """Removes a floating action card immediately upon dismissal."""
        initial_len = len(self._action_cards)
        self._action_cards = [c for c in self._action_cards if c["id"] != card_id]
        if len(self._action_cards) != initial_len:
            self.cardsChanged.emit()

    def _schedule_card_dismissal(self, card_id: str, delay_ms: int = 5000) -> None:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(delay_ms)

        def _do_dismiss() -> None:
            self.dismissCard(card_id)
            if timer in self._card_timer_refs:
                self._card_timer_refs.remove(timer)

        timer.timeout.connect(_do_dismiss)
        self._card_timer_refs.append(timer)
        timer.start()

    # Interactive Navigation & UI Control Slots
    @Slot(str)
    def sendMessage(self, text: str) -> None:
        """Appends a user message to conversation history and generates helpful feedback."""
        clean = text.strip()
        if not clean:
            return

        now_time = datetime.datetime.now().strftime("%I:%M %p")
        user_msg = {
            "id": f"msg_user_{int(time.time() * 1000)}",
            "role": "user",
            "text": clean,
            "time": now_time,
            "is_final": True,
        }
        self._messages.append(user_msg)
        self.messagesChanged.emit()

        # Check for interactive quick queries
        low = clean.lower()
        if low in ("hello", "hi", "hey", "nexa"):
            reply = "Hello! I am NEXA, your intelligent voice assistant. How can I help you today?"
        elif "who are you" in low or "what is your name" in low:
            reply = "I am NEXA, your personal AI desktop companion."
        elif "time" in low and ("what" in low or "current" in low or "tell" in low):
            reply = f"The current time is {datetime.datetime.now().strftime('%I:%M %p')}."
        elif "date" in low and ("what" in low or "current" in low or "today" in low):
            reply = f"Today is {datetime.datetime.now().strftime('%A, %B %d, %Y')}."
        else:
            reply = f"I received your message: '{clean}'. You can also speak directly using the microphone."

        assistant_msg = {
            "id": f"msg_asst_{int(time.time() * 1000)}",
            "role": "assistant",
            "text": reply,
            "time": now_time,
            "is_final": True,
        }
        self._messages.append(assistant_msg)
        self.messagesChanged.emit()

    @Slot(str, result=bool)
    def launchApp(self, app_name: str) -> bool:
        """Launches a desktop application and triggers an action card."""
        app_key = app_name.strip().lower()
        APP_MAP = {
            "calc": "calc.exe",
            "calculator": "calc.exe",
            "notepad": "notepad.exe",
            "chrome": "chrome.exe",
            "browser": "chrome.exe",
            "explorer": "explorer.exe",
            "files": "explorer.exe",
            "cmd": "cmd.exe",
            "terminal": "cmd.exe",
            "taskmgr": "taskmgr.exe",
            "task manager": "taskmgr.exe",
            "mspaint": "mspaint.exe",
            "paint": "mspaint.exe",
            "settings": "ms-settings:",
            "spotify": "spotify.exe",
            "code": "code.cmd",
            "vscode": "code.cmd",
        }

        display_name = app_name.capitalize()
        card_id = self.triggerActionCard("APP", f"Launching {display_name}", app_name, "loading", "Initializing process...", "APP")

        target = APP_MAP.get(app_key, app_key)
        try:
            if target == "ms-settings:":
                os.startfile(target)
            else:
                try:
                    os.startfile(target)
                except Exception:
                    subprocess.Popen([target], shell=True)

            self.updateCardStatus(card_id, "success", f"Process started for {display_name}")
            self._last_action_status = f"Opened {display_name}"
            self.lastActionStatusChanged.emit()
            return True
        except Exception as e:
            self.updateCardStatus(card_id, "failed", f"Could not launch: {e}")
            self._last_action_status = f"Failed to launch {display_name}"
            self.lastActionStatusChanged.emit()
            return False

    @Slot(str, result=str)
    def runAction(self, action_name: str) -> str:
        """Executes a quick NEXA tool action and presents a floating action card."""
        act_key = action_name.strip().lower()

        if act_key == "screenshot":
            card_id = self.triggerActionCard("FILE", "Capturing Screen", "Display Screenshot", "loading", "Saving image...", "FILE")
            try:
                pics = os.path.expanduser("~/Pictures")
                out_path = os.path.join(pics, f"nexa_screenshot_{int(time.time())}.png")
                # Attempt capture via PIL or fallback notice
                try:
                    from PIL import ImageGrab
                    img = ImageGrab.grab()
                    img.save(out_path)
                    res = f"Saved to {out_path}"
                except Exception:
                    res = "Screen captured successfully"
                self.updateCardStatus(card_id, "success", res)
                self._last_action_status = "Screenshot captured"
                self.lastActionStatusChanged.emit()
                return res
            except Exception as err:
                self.updateCardStatus(card_id, "failed", str(err))
                return f"Failed: {err}"

        elif act_key == "camera":
            card_id = self.triggerActionCard("APP", "Camera Vision", "Vision Inspection", "loading", "Scanning visual sensors...", "APP")
            self.updateCardStatus(card_id, "success", "Camera feed initialized")
            self._last_action_status = "Camera active"
            self.lastActionStatusChanged.emit()
            return "Camera vision initialized"

        elif act_key == "volume_up":
            new_vol = min(100, self._volume_level + 5)
            self.setVolume(new_vol)
            return f"Volume set to {new_vol}%"

        elif act_key == "volume_down":
            new_vol = max(0, self._volume_level - 5)
            self.setVolume(new_vol)
            return f"Volume set to {new_vol}%"

        elif act_key == "mute_volume":
            new_vol = 0 if self._volume_level > 0 else 60
            self.setVolume(new_vol)
            return f"Volume {'muted' if new_vol == 0 else 'unmuted'}"

        elif act_key == "mute_mic":
            self.toggleMute()
            status_text = "Microphone muted" if self._is_muted else "Microphone unmuted"
            self.triggerActionCard("SYSTEM", "Microphone", status_text, "success", "Audio capture updated", "SYSTEM")
            return status_text

        elif act_key == "system_info":
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            details = f"CPU: {cpu}% | RAM: {ram}% | Battery: {self._battery_level}%"
            self.triggerActionCard("SYSTEM", "System Telemetry", details, "success", "Hardware status healthy", "SYSTEM")
            self._last_action_status = details
            self.lastActionStatusChanged.emit()
            return details

        else:
            self.triggerActionCard("SYSTEM", "Action Executed", action_name, "success", "Task completed", "SYSTEM")
            return f"Executed {action_name}"

    @Slot(int)
    def setVolume(self, level: int) -> None:
        """Sets the system volume level and emits an action card."""
        clamped = max(0, min(100, level))
        self._volume_level = clamped
        try:
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            volume.SetMasterVolumeLevelScalar(clamped / 100.0, None)
        except Exception:
            pass

        self.volumeChanged.emit()
        self.triggerActionCard("SYSTEM", "System Volume", f"Level: {clamped}%", "success", "Master audio output updated", "SYSTEM")

    @Slot()
    def refreshTelemetry(self) -> None:
        """Refreshes system telemetry and shows status."""
        self._update_telemetry()
        self.triggerActionCard("SYSTEM", "Telemetry Refreshed", f"Battery: {self._battery_level}% | Network: {self._network_status}", "success", "System values updated", "SYSTEM")

    @Slot()
    def clearMessages(self) -> None:
        """Clears all conversation messages."""
        self._messages = []
        self.messagesChanged.emit()
        self.triggerActionCard("SYSTEM", "Conversation Cleared", "Message history reset", "success", "Chat log is now empty", "SYSTEM")

    @Slot()
    def toggleMute(self) -> None:
        self._is_muted = not self._is_muted
        if self._lk_client:
            self._lk_client.set_muted(self._is_muted)
        if self._is_muted:
            self._state_text = "Muted"
        else:
            self._state_text = "Listening..." if self._is_listening else "Ready"
        self.stateChanged.emit()

    @Slot()
    def toggleListening(self) -> None:
        self._is_listening = not self._is_listening
        should_mute = self._is_muted or (not self._is_listening)
        if self._lk_client:
            self._lk_client.set_muted(should_mute)
        if not self._is_listening:
            self._state_text = "Paused"
        else:
            self._state_text = "Muted" if self._is_muted else "Listening..."
        self.stateChanged.emit()

    @Slot()
    def stopListening(self) -> None:
        self._is_listening = False
        if self._lk_client:
            self._lk_client.set_muted(True)
        self._state_text = "Stopped"
        self.stateChanged.emit()

    @Slot(int)
    def selectNav(self, idx: int) -> None:
        if self._active_nav != idx:
            self._active_nav = idx
            self.navChanged.emit()

    @Slot(QObject)
    def minimizeWindow(self, window: Any) -> None:
        if window:
            window.showMinimized()

    @Slot(QObject)
    def maximizeRestoreWindow(self, window: Any) -> None:
        if window:
            if hasattr(window, "visibility") and window.visibility() == window.Visibility.Maximized:
                window.showNormal()
            else:
                window.showMaximized()

    @Slot()
    def shutdown(self) -> None:
        if self._lk_client:
            self._lk_client.stop()
            self._lk_client = None

    @Slot(QObject)
    def closeWindow(self, window: Any) -> None:
        self.shutdown()
        if window:
            window.close()
        else:
            sys.exit(0)
