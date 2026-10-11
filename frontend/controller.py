"""NEXA Frontend UI Controller.

Manages application state, live Windows system telemetry,
waveform visualization amplitudes, and window controls.
"""
from __future__ import annotations

import datetime
import math
import random
import socket
import sys
import re
from typing import Any, List

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
        self._active_nav = 0  # 0: Home, 1: Chat, 2: Grid, 3: Settings
        self._wave_phase = 0.0
        self._waveform_amplitudes: list[float] = [0.1] * 48

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

        # Initial reference messages matching exactly the user-provided design
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

        # Fallback correlation: if no segment ID match, check if last message has same role and is not final,
        # or if it has the same role and exact same text (to prevent duplicate turn emission)
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
