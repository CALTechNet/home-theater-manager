"""Playback engines for the control service.

The service keeps the Phase 1 API stable while allowing deployments to switch
from the in-memory simulator to a host-side ffmpeg runner with:

    HTM_PLAYBACK_DRIVER=ffmpeg

Output devices can be overridden with JSON environment variables when the
installer discovers exact ffmpeg targets:

    HTM_VIDEO_OUTPUTS_JSON='[{"id":"decklink:0","name":"DeckLink","type":"sdi",
      "ffmpeg_args":["-f","decklink","DeckLink SDI"]}]'
    HTM_AUDIO_OUTPUTS_JSON='[{"id":"hdmi-0","name":"HDMI","type":"hdmi",
      "ffmpeg_args":["-f","alsa","hw:0,3"]}]'
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


DEFAULT_IDLE = {"mode": "black", "logo_path": None, "scale": "fit"}


@dataclass(frozen=True)
class OutputDevice:
    id: str
    name: str
    type: str
    ffmpeg_args: tuple[str, ...] = ()
    embedded_audio: bool = False

    def api_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "type": self.type}


def _tuple_args(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return ()
    return tuple(value)


def _devices_from_env(name: str, defaults: list[OutputDevice]) -> list[OutputDevice]:
    raw = os.getenv(name)
    if not raw:
        return defaults
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return defaults
    devices: list[OutputDevice] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            dev_id = str(item.get("id", "")).strip()
            dev_name = str(item.get("name", dev_id)).strip()
            dev_type = str(item.get("type", "")).strip()
            if not dev_id or not dev_name or not dev_type:
                continue
            devices.append(
                OutputDevice(
                    id=dev_id,
                    name=dev_name,
                    type=dev_type,
                    ffmpeg_args=_tuple_args(item.get("ffmpeg_args")),
                    embedded_audio=bool(item.get("embedded_audio", False)),
                )
            )
    return devices or defaults


def _default_video_outputs() -> list[OutputDevice]:
    decklink_name = os.getenv("HTM_DECKLINK_DEVICE", "Blackmagic DeckLink SDI")
    fbdev = os.getenv("HTM_FBDEV_DEVICE", "/dev/fb0")
    return [
        OutputDevice(
            id="decklink:0",
            name=decklink_name,
            type="sdi",
            ffmpeg_args=("-f", "decklink", decklink_name),
            embedded_audio=True,
        ),
        OutputDevice(
            id="gpu:hdmi-0",
            name="GPU HDMI-0",
            type="hdmi",
            ffmpeg_args=("-f", "fbdev", fbdev),
        ),
        OutputDevice(
            id="gpu:dp-0",
            name="GPU DisplayPort-0",
            type="displayport",
            ffmpeg_args=("-f", "fbdev", fbdev),
        ),
    ]


def _default_audio_outputs() -> list[OutputDevice]:
    return [
        OutputDevice(
            id="sdi-embedded",
            name="SDI embedded audio (DeckLink)",
            type="sdi",
            embedded_audio=True,
        ),
        OutputDevice(
            id="hdmi-0",
            name="GPU HDMI-0 audio",
            type="hdmi",
            ffmpeg_args=("-f", "alsa", os.getenv("HTM_HDMI_ALSA_DEVICE", "default")),
        ),
        OutputDevice(
            id="spdif-0",
            name="S/PDIF optical",
            type="spdif",
            ffmpeg_args=("-f", "alsa", os.getenv("HTM_SPDIF_ALSA_DEVICE", "default")),
        ),
    ]


@dataclass
class DeviceCatalog:
    video: list[OutputDevice] = field(default_factory=lambda: _devices_from_env(
        "HTM_VIDEO_OUTPUTS_JSON", _default_video_outputs()
    ))
    audio: list[OutputDevice] = field(default_factory=lambda: _devices_from_env(
        "HTM_AUDIO_OUTPUTS_JSON", _default_audio_outputs()
    ))

    def video_by_id(self, ids: list[str]) -> list[OutputDevice]:
        by_id = {d.id: d for d in self.video}
        return [by_id[i] for i in ids if i in by_id]

    def audio_by_id(self, dev_id: str | None) -> OutputDevice | None:
        if not dev_id:
            return None
        return next((d for d in self.audio if d.id == dev_id), None)

    def outputs(self) -> dict:
        return {
            "video": [d.api_dict() for d in self.video],
            "audio": [d.api_dict() for d in self.audio],
        }


class PlaybackEngine(Protocol):
    def load(self, showing_id: int, items: list[dict], outputs: dict | None) -> dict: ...
    def configure(self, outputs: dict) -> dict: ...
    def start(self) -> dict: ...
    def pause(self) -> dict: ...
    def resume(self) -> dict: ...
    def stop(self) -> dict: ...
    def snapshot(self) -> dict: ...
    def outputs(self) -> dict: ...


class SimulatedPlayer:
    """Thread-safe playback state with a simulated clock."""

    def __init__(self, catalog: DeviceCatalog | None = None) -> None:
        self.catalog = catalog or DeviceCatalog()
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.state = "IDLE"
        self.showing_id: int | None = None
        self.items: list[dict] = []
        self.outputs_config: dict | None = None
        self.idle_screen: dict = DEFAULT_IDLE.copy()
        self.index = 0
        self.position = 0.0
        self._last_tick = time.monotonic()

    def _advance(self) -> None:
        now = time.monotonic()
        if self.state == "PLAYING":
            self.position += now - self._last_tick
        self._last_tick = now

    def snapshot(self) -> dict:
        with self.lock:
            self._advance()
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict:
        current = None
        if self.items and self.index < len(self.items):
            current = self.items[self.index].get("path")
        return {
            "state": self.state.lower(),
            "showing_id": self.showing_id,
            "position_seconds": round(self.position, 1),
            "current_item": current,
            "outputs": self.outputs_config,
            "idle_screen": self.idle_screen,
        }

    def load(self, showing_id: int, items: list[dict], outputs: dict | None) -> dict:
        with self.lock:
            self.reset()
            self.showing_id = showing_id
            self.items = items
            self.outputs_config = outputs
            if outputs and outputs.get("idle_screen"):
                self.idle_screen = outputs["idle_screen"]
            self.state = "LOADED"
            return self._snapshot_locked()

    def configure(self, outputs: dict) -> dict:
        with self.lock:
            self.outputs_config = outputs
            self.idle_screen = outputs.get("idle_screen", DEFAULT_IDLE.copy())
            return self._snapshot_locked()

    def start(self) -> dict:
        with self.lock:
            if self.state in ("LOADED", "PAUSED"):
                self.state = "PLAYING"
                self._last_tick = time.monotonic()
            return self._snapshot_locked()

    def pause(self) -> dict:
        with self.lock:
            self._advance()
            if self.state == "PLAYING":
                self.state = "PAUSED"
            return self._snapshot_locked()

    def resume(self) -> dict:
        with self.lock:
            if self.state == "PAUSED":
                self.state = "PLAYING"
                self._last_tick = time.monotonic()
            return self._snapshot_locked()

    def stop(self) -> dict:
        with self.lock:
            prior = self.showing_id
            outputs = self.outputs_config
            idle_screen = self.idle_screen
            self.reset()
            self.outputs_config = outputs
            self.idle_screen = idle_screen
            snap = self._snapshot_locked()
            snap["showing_id"] = prior
            return snap

    def outputs(self) -> dict:
        return self.catalog.outputs()


class FfmpegPlayer:
    """Host-side ffmpeg player with idle screen ownership of selected outputs."""

    def __init__(
        self,
        catalog: DeviceCatalog | None = None,
        ffmpeg_bin: str | None = None,
        popen=subprocess.Popen,
    ) -> None:
        self.catalog = catalog or DeviceCatalog()
        self.ffmpeg_bin = ffmpeg_bin or os.getenv("HTM_FFMPEG_BIN", "ffmpeg")
        self._popen = popen
        self.lock = threading.RLock()
        self.state = "IDLE"
        self.showing_id: int | None = None
        self.items: list[dict] = []
        self.outputs_config: dict | None = None
        self.idle_screen: dict = DEFAULT_IDLE.copy()
        self.index = 0
        self.position = 0.0
        self._last_tick = time.monotonic()
        self._play_proc: subprocess.Popen | None = None
        self._idle_proc: subprocess.Popen | None = None
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()

    def outputs(self) -> dict:
        return self.catalog.outputs()

    def load(self, showing_id: int, items: list[dict], outputs: dict | None) -> dict:
        with self.lock:
            self._stop_playback_locked()
            self.showing_id = showing_id
            self.items = items
            self.outputs_config = outputs
            self.idle_screen = (outputs or {}).get("idle_screen", DEFAULT_IDLE.copy())
            self.index = 0
            self.position = 0.0
            self.state = "LOADED"
            self._start_idle_locked()
            return self._snapshot_locked()

    def configure(self, outputs: dict) -> dict:
        with self.lock:
            self.outputs_config = outputs
            self.idle_screen = outputs.get("idle_screen", DEFAULT_IDLE.copy())
            if self.state in ("IDLE", "LOADED"):
                self._start_idle_locked()
            return self._snapshot_locked()

    def start(self) -> dict:
        with self.lock:
            if self.state == "PAUSED":
                self._resume_locked()
                return self._snapshot_locked()
            if self.state != "LOADED" or not self.items:
                return self._snapshot_locked()
            self._stop_idle_locked()
            self._stop_event.clear()
            self.state = "PLAYING"
            self.position = 0.0
            self._last_tick = time.monotonic()
            self._worker = threading.Thread(target=self._play_playlist, daemon=True)
            self._worker.start()
            return self._snapshot_locked()

    def pause(self) -> dict:
        with self.lock:
            self._advance_locked()
            if self.state == "PLAYING":
                if self._play_proc and self._play_proc.poll() is None:
                    self._play_proc.send_signal(signal.SIGSTOP)
                self.state = "PAUSED"
            return self._snapshot_locked()

    def resume(self) -> dict:
        with self.lock:
            self._resume_locked()
            return self._snapshot_locked()

    def stop(self) -> dict:
        with self.lock:
            prior = self.showing_id
            self._stop_playback_locked()
            self.state = "IDLE"
            self.showing_id = None
            self.items = []
            self.index = 0
            self.position = 0.0
            self._start_idle_locked()
            snap = self._snapshot_locked()
            snap["showing_id"] = prior
            return snap

    def snapshot(self) -> dict:
        with self.lock:
            self._advance_locked()
            return self._snapshot_locked()

    def build_media_command(self, path: str, outputs: dict | None = None) -> list[str]:
        outputs = outputs or self.outputs_config or {}
        video_devices = self.catalog.video_by_id(outputs.get("video_outputs") or [])
        audio_device = self.catalog.audio_by_id(outputs.get("audio_output"))
        audio_mode = outputs.get("audio_mode", "passthrough")
        cmd = [self.ffmpeg_bin, "-hide_banner", "-nostdin", "-re", "-i", path]
        for device in video_devices:
            cmd.extend(["-map", "0:v:0", *self._video_output_args(device)])
            if audio_device and audio_device.embedded_audio and device.embedded_audio:
                cmd.extend(["-map", "0:a:0?", *self._audio_codec_args(audio_mode)])
            else:
                cmd.append("-an")
            cmd.extend(device.ffmpeg_args)
        if audio_device and audio_device.ffmpeg_args and not audio_device.embedded_audio:
            cmd.extend(["-map", "0:a:0?", "-vn", *self._audio_codec_args(audio_mode)])
            cmd.extend(audio_device.ffmpeg_args)
        if not video_devices and not (audio_device and audio_device.ffmpeg_args):
            cmd.extend(["-f", "null", "-"])
        return cmd

    def build_idle_command(self, outputs: dict | None = None) -> list[str] | None:
        outputs = outputs or self.outputs_config or {}
        video_devices = self.catalog.video_by_id(outputs.get("video_outputs") or [])
        if not video_devices:
            return None
        idle = outputs.get("idle_screen") or self.idle_screen or DEFAULT_IDLE
        mode = idle.get("mode", "black")
        logo_path = idle.get("logo_path")
        cmd = [self.ffmpeg_bin, "-hide_banner", "-nostdin", "-re"]
        if mode == "logo" and logo_path and Path(str(logo_path)).exists():
            cmd.extend(["-loop", "1", "-i", str(logo_path)])
            vf = self._idle_logo_filter(idle.get("scale", "fit"))
        else:
            cmd.extend(["-f", "lavfi", "-i", "color=c=black:s=3840x2160:r=30000/1001"])
            vf = "format=yuv422p"
        for device in video_devices:
            cmd.extend(["-map", "0:v:0", "-vf", vf, "-an", *device.ffmpeg_args])
        return cmd

    def _play_playlist(self) -> None:
        while True:
            with self.lock:
                if self._stop_event.is_set() or self.index >= len(self.items):
                    break
                item = self.items[self.index]
                self.position = 0.0
                self._last_tick = time.monotonic()
                self._play_proc = self._popen(self.build_media_command(str(item.get("path", ""))))
            proc = self._play_proc
            while proc and proc.poll() is None:
                if self._stop_event.wait(0.2):
                    self._terminate(proc)
                    break
            with self.lock:
                self._advance_locked()
                self._play_proc = None
                if self._stop_event.is_set():
                    break
                self.index += 1
        with self.lock:
            if not self._stop_event.is_set():
                self.state = "IDLE"
                self.showing_id = None
                self.items = []
                self.index = 0
                self.position = 0.0
                self._start_idle_locked()

    def _resume_locked(self) -> None:
        if self.state == "PAUSED":
            if self._play_proc and self._play_proc.poll() is None:
                self._play_proc.send_signal(signal.SIGCONT)
            self.state = "PLAYING"
            self._last_tick = time.monotonic()

    def _advance_locked(self) -> None:
        now = time.monotonic()
        if self.state == "PLAYING":
            self.position += now - self._last_tick
        self._last_tick = now

    def _snapshot_locked(self) -> dict:
        current = None
        if self.items and self.index < len(self.items):
            current = self.items[self.index].get("path")
        return {
            "state": self.state.lower(),
            "showing_id": self.showing_id,
            "position_seconds": round(self.position, 1),
            "current_item": current,
            "outputs": self.outputs_config,
            "idle_screen": self.idle_screen,
        }

    def _start_idle_locked(self) -> None:
        self._stop_idle_locked()
        cmd = self.build_idle_command()
        if cmd:
            self._idle_proc = self._popen(cmd)

    def _stop_idle_locked(self) -> None:
        if self._idle_proc and self._idle_proc.poll() is None:
            self._terminate(self._idle_proc)
        self._idle_proc = None

    def _stop_playback_locked(self) -> None:
        self._stop_event.set()
        if self._play_proc and self._play_proc.poll() is None:
            self._terminate(self._play_proc)
        self._play_proc = None

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    @staticmethod
    def _audio_codec_args(audio_mode: str) -> list[str]:
        if audio_mode == "pcm":
            return ["-c:a", "pcm_s16le"]
        return ["-c:a", "copy"]

    @staticmethod
    def _video_output_args(device: OutputDevice) -> list[str]:
        if device.type == "sdi" or device.id.startswith("decklink:"):
            return ["-pix_fmt", "uyvy422"]
        return ["-pix_fmt", "bgra"]

    @staticmethod
    def _idle_logo_filter(scale: str) -> str:
        if scale == "fill":
            return "scale=3840:2160:force_original_aspect_ratio=increase,crop=3840:2160,format=yuv422p"
        return "scale=3840:2160:force_original_aspect_ratio=decrease,pad=3840:2160:(ow-iw)/2:(oh-ih)/2:black,format=yuv422p"


def create_player() -> PlaybackEngine:
    driver = os.getenv("HTM_PLAYBACK_DRIVER", "mock").lower()
    if driver == "ffmpeg":
        return FfmpegPlayer()
    return SimulatedPlayer()
