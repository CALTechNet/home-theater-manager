import json

from app import player as player_mod
from app.player import DeviceCatalog, FfmpegPlayer, OutputDevice, SimulatedPlayer


def _catalog():
    return DeviceCatalog(
        video=[
            OutputDevice(
                id="decklink:0",
                name="DeckLink Studio",
                type="sdi",
                ffmpeg_args=("-f", "decklink", "DeckLink Studio"),
                embedded_audio=True,
            ),
            OutputDevice(
                id="gpu:hdmi-0",
                name="Projector HDMI",
                type="hdmi",
                ffmpeg_args=("-f", "fbdev", "/dev/fb1"),
            ),
        ],
        audio=[
            OutputDevice(
                id="sdi-embedded",
                name="SDI embedded",
                type="sdi",
                embedded_audio=True,
            ),
            OutputDevice(
                id="hdmi-0",
                name="Receiver HDMI",
                type="hdmi",
                ffmpeg_args=("-f", "alsa", "hw:0,3"),
            ),
        ],
    )


def _contains_slice(cmd, expected):
    width = len(expected)
    return any(cmd[i:i + width] == expected for i in range(len(cmd) - width + 1))


def test_media_command_embeds_sdi_audio_in_decklink_output():
    player = FfmpegPlayer(catalog=_catalog(), ffmpeg_bin="ffmpeg")
    cmd = player.build_media_command(
        "/mnt/media/movie.mkv",
        {
            "video_outputs": ["decklink:0"],
            "audio_output": "sdi-embedded",
            "audio_mode": "pcm",
        },
    )

    assert cmd == [
        "ffmpeg", "-hide_banner", "-nostdin", "-re", "-i", "/mnt/media/movie.mkv",
        "-map", "0:v:0", "-pix_fmt", "uyvy422",
        "-map", "0:a:0?", "-c:a", "pcm_s16le",
        "-f", "decklink", "DeckLink Studio",
    ]


def test_media_command_routes_selected_video_and_external_audio_outputs():
    player = FfmpegPlayer(catalog=_catalog(), ffmpeg_bin="ffmpeg")
    cmd = player.build_media_command(
        "/mnt/media/trailer.mov",
        {
            "video_outputs": ["decklink:0", "gpu:hdmi-0"],
            "audio_output": "hdmi-0",
            "audio_mode": "passthrough",
        },
    )

    assert cmd.count("-map") == 3
    assert _contains_slice(
        cmd,
        ["-map", "0:v:0", "-pix_fmt", "uyvy422", "-an", "-f", "decklink", "DeckLink Studio"],
    )
    assert _contains_slice(
        cmd,
        ["-map", "0:v:0", "-pix_fmt", "bgra", "-an", "-f", "fbdev", "/dev/fb1"],
    )
    assert cmd[-8:] == ["-map", "0:a:0?", "-vn", "-c:a", "copy", "-f", "alsa", "hw:0,3"]


def test_media_command_tone_maps_hdr_only():
    player = FfmpegPlayer(catalog=_catalog(), ffmpeg_bin="ffmpeg")
    outputs = {
        "video_outputs": ["decklink:0"],
        "audio_output": "sdi-embedded",
        "audio_mode": "pcm",
        "tone_mapping": {
            "enabled": True,
            "mode": "dynamic",
            "target_container": "sdr2020",
            "target_nits": 100,
            "max_light_multiplier": 6,
            "desaturation": "auto",
        },
    }

    hdr = player.build_media_command("/mnt/media/hdr.mkv", outputs, item={"is_hdr10": True})
    sdr = player.build_media_command("/mnt/media/sdr.mkv", outputs, item={"is_hdr10": False})

    assert "-vf" in hdr
    assert any("tonemap=tonemap=hable" in part for part in hdr)
    assert "-vf" not in sdr


def test_idle_command_uses_black_when_requested():
    player = FfmpegPlayer(catalog=_catalog(), ffmpeg_bin="ffmpeg")
    cmd = player.build_idle_command(
        {
            "video_outputs": ["decklink:0"],
            "idle_screen": {"mode": "black", "logo_path": None, "scale": "fit"},
        },
    )

    assert cmd is not None
    assert "color=c=black:s=3840x2160:r=30000/1001" in cmd
    assert cmd[-3:] == ["-f", "decklink", "DeckLink Studio"]


def test_idle_command_uses_logo_filter_when_logo_exists(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"not decoded by command builder")
    player = FfmpegPlayer(catalog=_catalog(), ffmpeg_bin="ffmpeg")

    cmd = player.build_idle_command(
        {
            "video_outputs": ["gpu:hdmi-0"],
            "idle_screen": {"mode": "logo", "logo_path": str(logo), "scale": "fill"},
        },
    )

    assert cmd is not None
    assert ["-loop", "1", "-i", str(logo)] == cmd[4:8]
    assert any("crop=3840:2160" in part for part in cmd)
    assert cmd[-3:] == ["-f", "fbdev", "/dev/fb1"]


def test_simulated_player_keeps_idle_screen_after_stop():
    player = SimulatedPlayer(catalog=_catalog())
    outputs = {
        "video_outputs": ["decklink:0"],
        "audio_output": "sdi-embedded",
        "audio_mode": "pcm",
        "idle_screen": {"mode": "logo", "logo_path": "/runtime/logo.png", "scale": "fit"},
    }

    player.load(10, [{"path": "/mnt/media/movie.mkv"}], outputs)
    snap = player.stop()

    assert snap["showing_id"] == 10
    assert player.snapshot()["idle_screen"] == outputs["idle_screen"]


def test_snapshot_splits_display_and_playback_paths():
    player = SimulatedPlayer(catalog=_catalog())
    player.load(10, [{
        "path": "/mnt/media/Movie.mkv",
        "display_path": "/home/htm/Movie.mkv",
    }], None)
    player.start()

    snap = player.snapshot()

    assert snap["current_item"] == "/home/htm/Movie.mkv"
    assert snap["current_path"] == "/mnt/media/Movie.mkv"


def _kms_catalog():
    return DeviceCatalog(
        video=[
            OutputDevice(
                id="gpu:DP-1", name="GPU DP-1", type="displayport",
                drm_connector="DP-1", drm_device="/dev/dri/card1",
            ),
        ],
        audio=[
            OutputDevice(id="hdmi-0", name="HDMI", type="hdmi",
                         ffmpeg_args=("-f", "alsa", "hw:0,3")),
        ],
    )


def test_connector_type_mapping():
    assert player_mod._connector_type("HDMI-A-1") == "hdmi"
    assert player_mod._connector_type("DP-1") == "displayport"
    assert player_mod._connector_type("VGA-1") == "vga"
    assert player_mod._connector_type("eDP-1") == "edp"


def test_discovers_video_outputs_from_hardware_json(tmp_path, monkeypatch):
    hw = tmp_path / "hardware.json"
    hw.write_text(json.dumps({"connectors": [
        {"name": "DP-1", "status": "connected", "card": "card1", "device": "/dev/dri/card1"},
        {"name": "HDMI-A-1", "status": "disconnected", "card": "card1"},
    ]}))
    monkeypatch.setenv("HTM_HARDWARE_FILE", str(hw))
    monkeypatch.delenv("HTM_HAS_DECKLINK", raising=False)

    by_id = {d.id: d for d in player_mod._discovered_video_outputs()}
    assert by_id["gpu:DP-1"].type == "displayport"
    assert by_id["gpu:DP-1"].drm_connector == "DP-1"
    assert by_id["gpu:DP-1"].drm_device == "/dev/dri/card1"
    assert by_id["gpu:DP-1"].is_kms
    # Disconnected connectors are still listed (label notes the state); device
    # falls back to the card path when an explicit one isn't recorded.
    assert "disconnected" in by_id["gpu:HDMI-A-1"].name
    assert by_id["gpu:HDMI-A-1"].drm_device == "/dev/dri/card1"


def test_output_api_includes_drm_connector_metadata():
    dev = OutputDevice(
        id="gpu:DP-1", name="GPU DP-1", type="displayport",
        drm_connector="DP-1", drm_device="/dev/dri/card1",
    )
    assert dev.api_dict() == {
        "id": "gpu:DP-1",
        "name": "GPU DP-1",
        "type": "displayport",
        "drm_connector": "DP-1",
        "drm_device": "/dev/dri/card1",
    }


def test_output_api_includes_alsa_device_metadata():
    dev = OutputDevice(
        id="alsa:0,3", name="HDMI 0", type="hdmi",
        ffmpeg_args=("-f", "alsa", "hw:0,3"),
    )
    assert dev.api_dict() == {
        "id": "alsa:0,3",
        "name": "HDMI 0",
        "type": "hdmi",
        "alsa_device": "hw:0,3",
    }


def test_discovers_audio_outputs_from_hardware_json(tmp_path, monkeypatch):
    hw = tmp_path / "hardware.json"
    hw.write_text(json.dumps({"audio_outputs": [
        {
            "id": "alsa:0,3",
            "name": "HDMI 0",
            "type": "hdmi",
            "card": 0,
            "device": 3,
            "alsa_device": "hw:0,3",
            "card_name": "HDA Intel HDMI",
        },
        {
            "id": "alsa:2,0",
            "name": "USB Audio",
            "type": "usb",
            "card": 2,
            "device": 0,
            "alsa_device": "hw:2,0",
            "card_name": "STUDIO XL",
        },
    ]}))
    monkeypatch.setenv("HTM_HARDWARE_FILE", str(hw))
    monkeypatch.delenv("HTM_HAS_DECKLINK", raising=False)

    by_id = {d.id: d for d in player_mod._discovered_audio_outputs()}
    assert by_id["alsa:0,3"].name == "HDMI 0 - HDA Intel HDMI (hw:0,3)"
    assert by_id["alsa:0,3"].type == "hdmi"
    assert by_id["alsa:0,3"].ffmpeg_args == ("-f", "alsa", "hw:0,3")
    assert by_id["alsa:2,0"].type == "usb"


def test_device_catalog_uses_discovered_audio_outputs(tmp_path, monkeypatch):
    hw = tmp_path / "hardware.json"
    hw.write_text(json.dumps({
        "connectors": [{"name": "HDMI-A-1", "status": "connected", "card": "card1"}],
        "audio_outputs": [{
            "id": "alsa:0,3",
            "name": "HDMI 0",
            "type": "hdmi",
            "alsa_device": "hw:0,3",
        }],
    }))
    monkeypatch.setenv("HTM_HARDWARE_FILE", str(hw))
    monkeypatch.delenv("HTM_HAS_DECKLINK", raising=False)
    monkeypatch.delenv("HTM_AUDIO_OUTPUTS_JSON", raising=False)
    monkeypatch.delenv("HTM_VIDEO_OUTPUTS_JSON", raising=False)

    outputs = DeviceCatalog().outputs()

    assert outputs["video"][0]["id"] == "gpu:HDMI-A-1"
    assert outputs["audio"] == [{
        "id": "alsa:0,3",
        "name": "HDMI 0 (hw:0,3)",
        "type": "hdmi",
        "alsa_device": "hw:0,3",
    }]


def test_simulated_player_reload_outputs_rebuilds_catalog(tmp_path, monkeypatch):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps({"audio_outputs": [{
        "id": "alsa:0,3", "name": "HDMI 0", "type": "hdmi", "alsa_device": "hw:0,3",
    }]}))
    second.write_text(json.dumps({"audio_outputs": [{
        "id": "alsa:2,0", "name": "USB Audio", "type": "usb", "alsa_device": "hw:2,0",
    }]}))
    monkeypatch.delenv("HTM_AUDIO_OUTPUTS_JSON", raising=False)
    monkeypatch.delenv("HTM_VIDEO_OUTPUTS_JSON", raising=False)
    monkeypatch.delenv("HTM_HAS_DECKLINK", raising=False)
    monkeypatch.setenv("HTM_HARDWARE_FILE", str(first))
    player = SimulatedPlayer()

    assert player.outputs()["audio"][0]["id"] == "alsa:0,3"

    monkeypatch.setenv("HTM_HARDWARE_FILE", str(second))

    assert player.reload_outputs()["audio"][0]["id"] == "alsa:2,0"


def test_discovery_includes_decklink_when_present(tmp_path, monkeypatch):
    hw = tmp_path / "hardware.json"
    hw.write_text(json.dumps({"connectors": [{"name": "DP-1", "status": "connected", "card": "card1"}]}))
    monkeypatch.setenv("HTM_HARDWARE_FILE", str(hw))
    monkeypatch.setenv("HTM_HAS_DECKLINK", "true")
    ids = [d.id for d in player_mod._discovered_video_outputs()]
    assert "decklink:0" in ids and "gpu:DP-1" in ids


def test_kms_media_command_uses_mpv_drm():
    player = FfmpegPlayer(catalog=_kms_catalog(), ffmpeg_bin="ffmpeg")
    cmds = player.media_commands("/mnt/media/movie.mkv", {
        "video_outputs": ["gpu:DP-1"], "audio_output": "hdmi-0", "audio_mode": "pcm",
    })
    assert len(cmds) == 1
    cmd = cmds[0]
    assert cmd[0] == "mpv"
    assert "--vo=drm" in cmd
    assert "--drm-connector=DP-1" in cmd
    assert "--drm-device=/dev/dri/card1" in cmd
    assert "--audio-device=alsa/hw:0,3" in cmd
    assert cmd[-2:] == ["--", "/mnt/media/movie.mkv"]
    assert not any("audio-spdif" in a for a in cmd)  # pcm decodes, no bitstream


def test_kms_media_command_can_use_same_hdmi_interface_for_audio_and_video():
    catalog = DeviceCatalog(
        video=[
            OutputDevice(
                id="gpu:HDMI-A-1", name="GPU HDMI-A-1", type="hdmi",
                drm_connector="HDMI-A-1", drm_device="/dev/dri/card1",
            ),
        ],
        audio=[
            OutputDevice(
                id="alsa:0,3", name="HDMI 0", type="hdmi",
                ffmpeg_args=("-f", "alsa", "hw:0,3"),
            ),
        ],
    )
    player = FfmpegPlayer(catalog=catalog, ffmpeg_bin="ffmpeg")
    cmds = player.media_commands("/mnt/media/movie.mkv", {
        "video_outputs": ["gpu:HDMI-A-1"],
        "audio_output": "alsa:0,3",
        "audio_mode": "pcm",
    })

    assert len(cmds) == 1
    assert "--drm-connector=HDMI-A-1" in cmds[0]
    assert "--audio-device=alsa/hw:0,3" in cmds[0]


def test_kms_media_command_passthrough_adds_spdif():
    player = FfmpegPlayer(catalog=_kms_catalog(), ffmpeg_bin="ffmpeg")
    cmds = player.media_commands("/m/x.mkv", {"video_outputs": ["gpu:DP-1"]})  # default passthrough
    assert any(a.startswith("--audio-spdif=") for a in cmds[0])


def test_kms_idle_black_command():
    player = FfmpegPlayer(catalog=_kms_catalog(), ffmpeg_bin="ffmpeg")
    cmds = player.idle_commands({
        "video_outputs": ["gpu:DP-1"],
        "idle_screen": {"mode": "black", "logo_path": None, "scale": "fit"},
    })
    assert len(cmds) == 1
    cmd = cmds[0]
    assert cmd[0] == "mpv"
    assert "--no-audio" in cmd
    assert "--osc=no" in cmd
    assert "--osd-level=0" in cmd
    assert "--loop-file=inf" in cmd
    assert cmd[-2:] == ["--", str(player_mod.BLACK_FRAME)]


def test_kms_idle_logo_command(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"x")
    player = FfmpegPlayer(catalog=_kms_catalog(), ffmpeg_bin="ffmpeg")
    cmds = player.idle_commands({
        "video_outputs": ["gpu:DP-1"],
        "idle_screen": {"mode": "logo", "logo_path": str(logo), "scale": "fill"},
    })
    cmd = cmds[0]
    assert cmd[-2:] == ["--", str(logo)]
    assert "--panscan=1.0" in cmd  # fill crops to cover
    assert "--loop-file=inf" in cmd


def test_media_commands_mix_ffmpeg_and_mpv():
    catalog = DeviceCatalog(
        video=[
            OutputDevice(id="decklink:0", name="SDI", type="sdi",
                         ffmpeg_args=("-f", "decklink", "SDI"), embedded_audio=True),
            OutputDevice(id="gpu:DP-1", name="DP", type="displayport",
                         drm_connector="DP-1", drm_device="/dev/dri/card1"),
        ],
        audio=[OutputDevice(id="sdi-embedded", name="SDI a", type="sdi", embedded_audio=True)],
    )
    player = FfmpegPlayer(catalog=catalog, ffmpeg_bin="ffmpeg")
    cmds = player.media_commands("/m/x.mkv", {
        "video_outputs": ["decklink:0", "gpu:DP-1"],
        "audio_output": "sdi-embedded", "audio_mode": "pcm",
    })
    assert len(cmds) == 2
    assert cmds[0][0] == "ffmpeg" and "decklink" in cmds[0]
    assert "DP-1" not in cmds[0]  # KMS device not handled by ffmpeg
    assert cmds[1][0] == "mpv" and "--drm-connector=DP-1" in cmds[1]


def test_media_commands_omit_ffmpeg_when_only_kms():
    player = FfmpegPlayer(catalog=_kms_catalog(), ffmpeg_bin="ffmpeg")
    cmds = player.media_commands("/m/x.mkv", {"video_outputs": ["gpu:DP-1"]})
    assert len(cmds) == 1 and cmds[0][0] == "mpv"


def test_env_catalog_overrides_devices(monkeypatch):
    monkeypatch.setenv(
        "HTM_VIDEO_OUTPUTS_JSON",
        '[{"id":"decklink:1","name":"SDI 2","type":"sdi",'
        '"embedded_audio":true,"ffmpeg_args":["-f","decklink","SDI 2"]}]',
    )
    monkeypatch.setenv(
        "HTM_AUDIO_OUTPUTS_JSON",
        '[{"id":"avr","name":"AVR","type":"hdmi","ffmpeg_args":["-f","alsa","hw:1,7"]}]',
    )

    catalog = DeviceCatalog()

    assert catalog.outputs()["video"] == [{"id": "decklink:1", "name": "SDI 2", "type": "sdi"}]
    assert catalog.audio_by_id("avr").ffmpeg_args == ("-f", "alsa", "hw:1,7")


def test_create_player_defaults_to_ffmpeg(monkeypatch):
    monkeypatch.delenv("HTM_PLAYBACK_DRIVER", raising=False)

    assert isinstance(player_mod.create_player(), FfmpegPlayer)

    monkeypatch.setenv("HTM_PLAYBACK_DRIVER", "simulated")

    assert isinstance(player_mod.create_player(), SimulatedPlayer)
