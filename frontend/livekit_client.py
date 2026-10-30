"""NEXA LiveKit Client Bridge.

Manages connection to LiveKit Cloud, agent dispatch, participant tracking,
microphone audio capture/publishing, assistant audio stream consumption and
native playback, and room lifecycle on dedicated worker threads off the Qt UI thread.
"""
from __future__ import annotations

import asyncio
import gc
import json
import logging
import os
import queue
import threading
import uuid
from typing import Optional
import time

from PySide6.QtCore import QObject, Signal, Slot
from dotenv import load_dotenv
from livekit import api, rtc
import numpy as np
import sounddevice as sd

logger = logging.getLogger("nexa.livekit_client")


class NexaAudioPlayer:
    """Consumes raw PCM audio chunks and outputs to the desktop sound device.

    Runs on a dedicated worker thread with an internal buffer queue to prevent
    blocking the asyncio event loop or the Qt GUI event loop.
    """

    def __init__(self, sample_rate: int = 48000, num_channels: int = 1) -> None:
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self._queue: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=300)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="NexaAudioPlayerThread",
            daemon=True,
        )
        self._thread.start()

    def play_chunk(self, data: bytes) -> None:
        if self._stop_event.is_set():
            return
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(data)
            except Exception:
                pass

    def clear(self) -> None:
        """Clear buffered audio instantly (used on interruption or track change)."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _run(self) -> None:
        try:
            with sd.RawOutputStream(
                samplerate=self.sample_rate,
                channels=self.num_channels,
                dtype="int16",
            ) as stream:
                while not self._stop_event.is_set():
                    try:
                        chunk = self._queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    if chunk is None:
                        break
                    if not self._stop_event.is_set():
                        stream.write(chunk)
        except Exception as e:
            logger.error("Audio playback device error: %s", e)
        finally:
            self.clear()

    def stop(self) -> None:
        self._stop_event.set()
        self.clear()
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
            self._thread = None


class NexaLiveKitClient(QObject):
    connectionStatusChanged = Signal(str)
    agentJoined = Signal(str)
    agentLeft = Signal(str)
    errorOccurred = Signal(str)
    micPublished = Signal(bool)
    micMutedChanged = Signal(bool)
    micDeviceChanged = Signal(str)
    micErrorOccurred = Signal(str)
    playbackStarted = Signal()
    playbackStopped = Signal()
    playbackActiveChanged = Signal(bool)
    playbackErrorOccurred = Signal(str)
    transcriptReceived = Signal(str, str, bool, str)

    def __init__(
        self,
        parent: Optional[QObject] = None,
        room_name: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        load_dotenv()

        self._room_name = (
            room_name
            or os.environ.get("LIVEKIT_ROOM_NAME")
            or os.environ.get("NEXA_ROOM_NAME")
            or f"nexa-desktop-{uuid.uuid4().hex[:8]}"
        )
        user_name = os.environ.get("USER_NAME", "User").strip()
        safe_user = "".join(c for c in user_name.lower() if c.isalnum() or c in "-_") or "user"
        self._participant_identity = f"{safe_user}-{uuid.uuid4().hex[:6]}"
        self._participant_name = f"{user_name} (Desktop)"

        self._status: str = "Disconnected"
        self._agent_participant: Optional[rtc.RemoteParticipant] = None
        self._room: Optional[rtc.Room] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._is_running = False

        # Audio capture & track publishing
        self._platform_audio: Optional[rtc.PlatformAudio] = None
        self._audio_source: Optional[rtc.PlatformAudioSource] = None
        self._audio_track: Optional[rtc.LocalAudioTrack] = None
        self._track_publication: Optional[rtc.LocalTrackPublication] = None
        self._is_muted: bool = False
        self._mic_device_name: str = ""

        # Audio playback
        self._player: Optional[NexaAudioPlayer] = None
        self._audio_stream: Optional[rtc.AudioStream] = None
        self._playback_task: Optional[asyncio.Task] = None
        self._subscribed_audio_track: Optional[rtc.Track] = None
        self._is_playing: bool = False

    @property
    def status(self) -> str:
        return self._status

    @property
    def room_name(self) -> str:
        return self._room_name

    @property
    def is_agent_active(self) -> bool:
        return self._agent_participant is not None

    @property
    def is_muted(self) -> bool:
        if self._audio_track:
            return self._audio_track.muted
        return self._is_muted

    @property
    def is_mic_published(self) -> bool:
        return self._track_publication is not None

    @property
    def mic_device_name(self) -> str:
        return self._mic_device_name

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    def _set_status(self, new_status: str) -> None:
        if self._status != new_status:
            self._status = new_status
            logger.info("Connection status: %s", new_status)
            self.connectionStatusChanged.emit(new_status)

    @staticmethod
    def _is_agent(participant: Optional[rtc.RemoteParticipant]) -> bool:
        if not participant:
            return False
        identity = (participant.identity or "").lower()
        name = (participant.name or "").lower()
        kind = getattr(participant, "kind", None)
        if kind == 4 or getattr(kind, "name", "") == "AGENT":
            return True
        if "agent" in identity or "agent" in name:
            return True
        return False

    def set_muted(self, muted: bool) -> None:
        """Update mute state thread-safely."""
        self._is_muted = muted
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._apply_mute, muted)

    def _apply_mute(self, muted: bool) -> None:
        if self._audio_track:
            try:
                if muted:
                    self._audio_track.mute()
                else:
                    self._audio_track.unmute()
                logger.info("Microphone mute set to %s", self._audio_track.muted)
                self.micMutedChanged.emit(self._audio_track.muted)
            except Exception as e:
                logger.warning("Failed to update mic mute state: %s", e)
        else:
            self.micMutedChanged.emit(muted)

    def start(self) -> None:
        """Start the background LiveKit worker thread and connect."""
        if self._thread and self._thread.is_alive():
            logger.warning("LiveKit client thread is already running.")
            return

        self._is_running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="NexaLiveKitClientThread",
            daemon=True,
        )
        self._thread.start()

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.create_task(self._connect_async())
            self._loop.run_forever()
        except Exception as e:
            logger.error("Unexpected error in LiveKit worker loop: %s", e)
        finally:
            try:
                pending = [t for t in asyncio.all_tasks(self._loop) if not t.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            self._loop.close()
            logger.debug("LiveKit event loop closed.")

    async def _connect_async(self) -> None:
        self._set_status("Connecting...")

        url = os.environ.get("LIVEKIT_URL")
        api_key = os.environ.get("LIVEKIT_API_KEY")
        api_secret = os.environ.get("LIVEKIT_API_SECRET")
        agent_name = os.environ.get("LIVEKIT_AGENT_NAME", "nexa")

        if not url or not api_key or not api_secret:
            err_msg = "Missing LiveKit credentials (LIVEKIT_URL, LIVEKIT_API_KEY, or LIVEKIT_API_SECRET)."
            logger.error(err_msg)
            self._set_status("Disconnected")
            self.errorOccurred.emit(err_msg)
            return

        # Audio playout is handled natively by rtc.PlatformAudio WebRTC ADM.
        # NexaAudioPlayer is omitted to prevent duplicate sounddevice playback.

        # 1. Dispatch named agent to room
        try:
            lk_api = api.LiveKitAPI(url=url, api_key=api_key, api_secret=api_secret)
            dispatch_req = api.CreateAgentDispatchRequest(
                agent_name=agent_name,
                room=self._room_name,
            )
            await lk_api.agent_dispatch.create_dispatch(dispatch_req)
            logger.info("Dispatched agent '%s' to room '%s'", agent_name, self._room_name)
            await lk_api.aclose()
        except Exception as dispatch_err:
            logger.warning("Agent dispatch request notice: %s", dispatch_err)

        # 2. Mint client token
        try:
            token = (
                api.AccessToken(api_key, api_secret)
                .with_identity(self._participant_identity)
                .with_name(self._participant_name)
                .with_grants(api.VideoGrants(room_join=True, room=self._room_name))
                .to_jwt()
            )
        except Exception as tok_err:
            logger.error("Failed to mint LiveKit access token: %s", tok_err)
            self._set_status("Disconnected")
            self.errorOccurred.emit(f"Token generation failed: {tok_err}")
            return

        # 3. Create Room and bind listeners
        self._room = rtc.Room(loop=self._loop)

        @self._room.on("connected")
        def _on_connected() -> None:
            if not self._agent_participant:
                self._set_status("Connected")

        @self._room.on("reconnecting")
        def _on_reconnecting() -> None:
            self._set_status("Reconnecting...")

        @self._room.on("reconnected")
        def _on_reconnected() -> None:
            self._check_existing_participants()

        @self._room.on("disconnected")
        def _on_disconnected(reason=None) -> None:
            logger.info("Room disconnected (reason: %s)", reason)
            self._agent_participant = None
            self._set_status("Disconnected")
            self._stop_consuming_track()
            asyncio.create_task(self._unpublish_microphone())

        @self._room.on("participant_connected")
        def _on_participant_connected(participant: rtc.RemoteParticipant) -> None:
            logger.info("Participant joined: %s (%s)", participant.identity, participant.name)
            if self._is_agent(participant):
                self._agent_participant = participant
                self._set_status("Agent Active")
                self.agentJoined.emit(participant.identity or participant.name or "agent")
                asyncio.create_task(self._publish_microphone())

        @self._room.on("participant_disconnected")
        def _on_participant_disconnected(participant: rtc.RemoteParticipant) -> None:
            logger.info("Participant left: %s", participant.identity)
            if self._is_agent(participant):
                self._agent_participant = None
                self._set_status("Connected")
                self.agentLeft.emit(participant.identity or participant.name or "agent")
                self._stop_consuming_track()
                asyncio.create_task(self._unpublish_microphone())

        @self._room.on("track_subscribed")
        def _on_track_subscribed(
            track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            logger.info(
                "Track subscribed: sid=%s, kind=%s, from=%s",
                track.sid,
                track.kind,
                participant.identity,
            )
            if self._is_agent(participant) and track.kind == rtc.TrackKind.KIND_AUDIO:
                self._start_consuming_track(track)

        @self._room.on("track_unsubscribed")
        def _on_track_unsubscribed(
            track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            logger.info("Track unsubscribed: sid=%s", track.sid)
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                self._stop_consuming_track()

        # Register text stream handler for LiveKit transcriptions
        try:
            self._room.register_text_stream_handler(
                "lk.transcription",
                self._on_transcription_text_stream,
            )
            logger.info("Registered text stream handler for 'lk.transcription'")
        except Exception as handler_err:
            logger.warning("Could not register text stream handler: %s", handler_err)

        # 4. Connect to Room
        try:
            await self._room.connect(url, token)
            logger.info("Connected to LiveKit room '%s'", self._room_name)
            self._check_existing_participants()
        except Exception as conn_err:
            logger.error("Failed to connect to LiveKit room: %s", conn_err)
            self._set_status("Disconnected")
            self.errorOccurred.emit(f"Connection error: {conn_err}")

    def _check_existing_participants(self) -> None:
        if not self._room:
            return
        for p in self._room.remote_participants.values():
            if self._is_agent(p):
                self._agent_participant = p
                self._set_status("Agent Active")
                self.agentJoined.emit(p.identity or p.name or "agent")
                asyncio.create_task(self._publish_microphone())
                for pub in p.track_publications.values():
                    if pub.track and pub.track.kind == rtc.TrackKind.KIND_AUDIO:
                        self._start_consuming_track(pub.track)
                return
        if not self._agent_participant:
            self._set_status("Connected")

    def _start_consuming_track(self, track: rtc.Track) -> None:
        if (
            self._subscribed_audio_track == track
            and self._playback_task
            and not self._playback_task.done()
        ):
            return
        self._stop_consuming_track()
        self._subscribed_audio_track = track
        if self._loop and self._loop.is_running():
            self._playback_task = self._loop.create_task(self._consume_audio_stream(track))

    async def _consume_audio_stream(self, track: rtc.Track) -> None:
        stream = None
        last_speech_time = 0.0
        try:
            stream = rtc.AudioStream.from_track(
                track=track,
                sample_rate=48000,
                num_channels=1,
            )
            self._audio_stream = stream
            logger.info("Started audio stream for track: %s", track.sid)
            async for event in stream:
                frame_data = bytes(event.frame._data)
                samples = np.frombuffer(frame_data, dtype=np.int16)
                peak = int(np.max(np.abs(samples))) if len(samples) > 0 else 0

                now = time.monotonic()
                if peak > 150:
                    last_speech_time = now
                    if not self._is_playing:
                        self._is_playing = True
                        logger.info("Assistant speech started.")
                        self.playbackStarted.emit()
                        self.playbackActiveChanged.emit(True)
                elif self._is_playing and (now - last_speech_time > 0.45):
                    self._is_playing = False
                    logger.info("Assistant speech ended.")
                    self.playbackStopped.emit()
                    self.playbackActiveChanged.emit(False)

                # Audio frames are rendered natively by WebRTC ADM; stream is retained for VAD/UI state.
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Audio stream error: %s", e)
            self.playbackErrorOccurred.emit(str(e))
        finally:
            if self._is_playing:
                self._is_playing = False
                self.playbackStopped.emit()
                self.playbackActiveChanged.emit(False)
            if stream:
                try:
                    await stream.aclose()
                except Exception:
                    pass
            if self._audio_stream == stream:
                self._audio_stream = None

    def _stop_consuming_track(self) -> None:
        if self._player:
            self._player.clear()
        if self._playback_task and not self._playback_task.done():
            self._playback_task.cancel()
            self._playback_task = None
        self._subscribed_audio_track = None
        if self._is_playing:
            self._is_playing = False
            self.playbackStopped.emit()
            self.playbackActiveChanged.emit(False)

    def _determine_role(self, participant_identity: str) -> str:
        if not participant_identity:
            return "assistant"
        if participant_identity == self._participant_identity:
            return "user"
        if self._agent_participant and participant_identity == self._agent_participant.identity:
            return "assistant"
        if "agent" in participant_identity.lower():
            return "assistant"
        return "assistant"

    def _on_transcription_text_stream(
        self,
        reader: rtc.TextStreamReader,
        participant_identity: str,
    ) -> None:
        if self._loop and self._loop.is_running():
            self._loop.create_task(
                self._consume_text_stream(reader, participant_identity)
            )

    async def _consume_text_stream(
        self,
        reader: rtc.TextStreamReader,
        participant_identity: str,
    ) -> None:
        try:
            attrs = reader.info.attributes or {}
            attr_role = attrs.get("role", "").lower().strip()
            if attr_role in ("user", "assistant"):
                role = attr_role
            else:
                role = self._determine_role(participant_identity)
            segment_id = attrs.get("lk.segment_id") or reader.info.stream_id or str(uuid.uuid4())
            accumulated_text = ""

            async for chunk in reader:
                if not chunk:
                    continue
                text_chunk = chunk
                if chunk.startswith("{") and chunk.endswith("}\n"):
                    try:
                        data = json.loads(chunk)
                        if isinstance(data, dict) and "text" in data:
                            text_chunk = data["text"]
                    except Exception:
                        pass
                accumulated_text += text_chunk
                curr_attrs = reader.info.attributes or {}
                is_final = curr_attrs.get("lk.transcription_final") == "true"
                self.transcriptReceived.emit(role, accumulated_text, is_final, segment_id)

            final_attrs = reader.info.attributes or {}
            is_final = final_attrs.get("lk.transcription_final", "true") == "true"
            if accumulated_text.strip():
                logger.info(
                    "TRANSCRIPTION_STREAM_RECEIVED: topic=%s, sender=%s, role=%s, is_final=%s, chars=%d",
                    reader.info.topic,
                    participant_identity,
                    role,
                    is_final,
                    len(accumulated_text),
                )
                self.transcriptReceived.emit(role, accumulated_text, is_final, segment_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Error consuming transcription text stream: %s", e)
        finally:
            try:
                reader.close()
            except Exception:
                pass

    async def _publish_microphone(self) -> None:
        """Capture and publish local microphone audio track."""
        if not self._room or not self._room.isconnected:
            logger.debug("Cannot publish microphone: room is not connected.")
            return
        if not self._agent_participant:
            logger.debug("Cannot publish microphone: agent is not present.")
            return
        if self._track_publication is not None:
            return

        try:
            if not self._platform_audio:
                self._platform_audio = rtc.PlatformAudio()
            devices = self._platform_audio.recording_devices()
            if not devices:
                err = "No microphone recording devices found."
                logger.warning(err)
                self.micErrorOccurred.emit(err)
                return

            self._mic_device_name = devices[0].name
            self.micDeviceChanged.emit(self._mic_device_name)
            logger.info("Using recording device: %s", self._mic_device_name)

            self._audio_source = self._platform_audio.create_audio_source(
                rtc.PlatformAudioOptions(
                    echo_cancellation=True,
                    noise_suppression=True,
                    auto_gain_control=True,
                )
            )
            self._audio_track = rtc.LocalAudioTrack.create_audio_track(
                "microphone", self._audio_source
            )

            # Apply current mute state
            if self._is_muted:
                self._audio_track.mute()
            else:
                self._audio_track.unmute()

            opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
            self._track_publication = await self._room.local_participant.publish_track(
                self._audio_track, opts
            )
            # Ensure the newly bound WebRTC transceiver applies the initial mute state
            if self._is_muted:
                self._audio_track.mute()
            else:
                self._audio_track.unmute()

            logger.info(
                "Published microphone track (SID: %s, source: %s, muted: %s)",
                self._track_publication.sid,
                self._track_publication.source,
                self._audio_track.muted,
            )
            self.micPublished.emit(True)
            self.micMutedChanged.emit(self._audio_track.muted)
        except rtc.PlatformAudioError as pa_err:
            err = f"Platform audio error: {pa_err}"
            logger.error(err)
            self.micErrorOccurred.emit(err)
        except rtc.PublishTrackError as pub_err:
            err = f"Failed to publish microphone track: {pub_err}"
            logger.error(err)
            self.micErrorOccurred.emit(err)
        except Exception as e:
            err = f"Unexpected microphone error: {e}"
            logger.error(err)
            self.micErrorOccurred.emit(err)

    async def _unpublish_microphone(self) -> None:
        """Safely unpublish the microphone track and release audio hardware."""
        if self._room and self._track_publication:
            try:
                await self._room.local_participant.unpublish_track(
                    self._track_publication.sid
                )
                logger.info("Unpublished microphone track.")
            except Exception as e:
                logger.debug("Error unpublishing microphone track: %s", e)
            self._track_publication = None

        if self._audio_track:
            self._audio_track = None

        if self._audio_source:
            try:
                self._audio_source.close()
            except Exception as e:
                logger.debug("Error closing audio source: %s", e)
            self._audio_source = None

        if self._platform_audio:
            try:
                self._platform_audio.close()
            except Exception as e:
                logger.debug("Error closing platform audio: %s", e)
            self._platform_audio = None

        self.micPublished.emit(False)

    def stop(self) -> None:
        """Cleanly disconnect from the room, release audio, and terminate the worker thread."""
        if not self._is_running:
            return
        self._is_running = False

        if self._loop and self._loop.is_running():
            async def _cleanup_and_disconnect() -> None:
                self._stop_consuming_track()
                if self._player:
                    self._player.stop()
                    self._player = None
                await self._unpublish_microphone()
                if self._room:
                    try:
                        await self._room.disconnect()
                    except Exception as e:
                        logger.debug("Error while disconnecting room: %s", e)
                    self._room = None
                    gc.collect()

            future = asyncio.run_coroutine_threadsafe(
                _cleanup_and_disconnect(), self._loop
            )
            try:
                future.result(timeout=4.0)
            except Exception as e:
                logger.debug("Disconnect future error: %s", e)

            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
            self._thread = None

        self._agent_participant = None
        self._set_status("Disconnected")
        logger.info("LiveKit client disconnected and stopped cleanly.")
