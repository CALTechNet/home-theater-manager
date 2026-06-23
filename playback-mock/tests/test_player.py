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
