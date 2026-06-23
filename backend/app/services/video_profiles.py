"""HDR tone-mapping defaults and projector output profiles."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


OUTPUT_PROFILES: list[dict[str, Any]] = [
    {
        "id": "lumagen-auto",
        "name": "Lumagen-style SDR BT.2020 projector",
        "manufacturer": "Lumagen",
        "category": "Reference",
        "description": "Dynamic HDR to SDR BT.2020 mapping with conservative projector defaults.",
        "target_nits": 100,
        "gamma": "2.4",
        "color_space": "bt2020",
        "output_container": "sdr2020",
        "max_light_multiplier": 6.0,
        "dynamic_pad": 4,
        "desaturation": "auto",
        "low_display_ratio": 31,
    },
    {
        "id": "barco-cinema-laser",
        "name": "Barco cinema laser projector",
        "manufacturer": "Barco",
        "category": "Cinema projector",
        "description": "High-stability laser output, SDR BT.2020 container, DCI-style gamma.",
        "target_nits": 108,
        "gamma": "2.4",
        "color_space": "bt2020",
        "output_container": "sdr2020",
        "max_light_multiplier": 5.0,
        "dynamic_pad": 3,
        "desaturation": "auto",
        "low_display_ratio": 28,
    },
    {
        "id": "christie-rgb-laser",
        "name": "Christie RGB laser projector",
        "manufacturer": "Christie",
        "category": "Cinema projector",
        "description": "Wide-gamut laser profile with a little more highlight headroom.",
        "target_nits": 120,
        "gamma": "2.4",
        "color_space": "bt2020",
        "output_container": "sdr2020",
        "max_light_multiplier": 4.5,
        "dynamic_pad": 3,
        "desaturation": "low",
        "low_display_ratio": 25,
    },
    {
        "id": "epson-home-cinema",
        "name": "Epson home cinema projector",
        "manufacturer": "Epson",
        "category": "Home theater projector",
        "description": "Lamp/laser home-theater tuning for lower peak brightness screens.",
        "target_nits": 80,
        "gamma": "2.4",
        "color_space": "bt2020",
        "output_container": "sdr2020",
        "max_light_multiplier": 6.0,
        "dynamic_pad": 5,
        "desaturation": "auto",
        "low_display_ratio": 36,
    },
    {
        "id": "panasonic-laser-projector",
        "name": "Panasonic laser projector",
        "manufacturer": "Panasonic",
        "category": "Presentation/cinema projector",
        "description": "Bright laser profile for larger screens and multipurpose rooms.",
        "target_nits": 130,
        "gamma": "2.4",
        "color_space": "bt2020",
        "output_container": "sdr2020",
        "max_light_multiplier": 4.0,
        "dynamic_pad": 3,
        "desaturation": "low",
        "low_display_ratio": 24,
    },
    {
        "id": "jvc-dila",
        "name": "JVC D-ILA theater projector",
        "manufacturer": "JVC",
        "category": "Home theater projector",
        "description": "Contrast-first profile that protects black floor and midtones.",
        "target_nits": 90,
        "gamma": "2.4",
        "color_space": "bt2020",
        "output_container": "sdr2020",
        "max_light_multiplier": 6.0,
        "dynamic_pad": 4,
        "desaturation": "auto",
        "low_display_ratio": 34,
    },
    {
        "id": "sony-sxrd",
        "name": "Sony SXRD theater projector",
        "manufacturer": "Sony",
        "category": "Home theater projector",
        "description": "Balanced SDR BT.2020 profile for SXRD home theater projectors.",
        "target_nits": 95,
        "gamma": "2.4",
        "color_space": "bt2020",
        "output_container": "sdr2020",
        "max_light_multiplier": 5.5,
        "dynamic_pad": 4,
        "desaturation": "auto",
        "low_display_ratio": 32,
    },
    {
        "id": "generic-sdr2020-projector",
        "name": "Generic SDR BT.2020 projector",
        "manufacturer": "Generic",
        "category": "Projector",
        "description": "Safe default when a display is calibrated for SDR gamma 2.4 and BT.2020 input.",
        "target_nits": 100,
        "gamma": "2.4",
        "color_space": "bt2020",
        "output_container": "sdr2020",
        "max_light_multiplier": 6.0,
        "dynamic_pad": 4,
        "desaturation": "auto",
        "low_display_ratio": 31,
    },
    {
        "id": "custom",
        "name": "Custom output profile",
        "manufacturer": "Custom",
        "category": "User profile",
        "description": "Use the settings below as the source of truth.",
        "target_nits": 100,
        "gamma": "2.4",
        "color_space": "bt2020",
        "output_container": "sdr2020",
        "max_light_multiplier": 6.0,
        "dynamic_pad": 4,
        "desaturation": "auto",
        "low_display_ratio": 31,
    },
]

PROFILE_BY_ID = {p["id"]: p for p in OUTPUT_PROFILES}
DEFAULT_PROFILE_ID = "lumagen-auto"

DEFAULT_TONE_MAPPING: dict[str, Any] = {
    "enabled": True,
    "mode": "dynamic",
    "output_profile_id": DEFAULT_PROFILE_ID,
    "target_container": "sdr2020",
    "target_nits": 100,
    "gamma": "2.4",
    "color_space": "bt2020",
    "max_light_multiplier": 6.0,
    "dynamic_pad": 4,
    "desaturation": "auto",
    "low_display_ratio": 31,
    "max_cll_mode": "auto",
    "max_cll_fallback_nits": 1000,
    "static_crossover_nits": 1000,
    "hdr_metadata": "strip",
    "custom_profile": {},
}

DEFAULT_VIDEO_MODE: dict[str, Any] = {
    "match_policy": "frame_rate",
    "base_output_profile_id": DEFAULT_PROFILE_ID,
    "resolution": "profile",
    "frame_rate": "source",
    "dynamic_range": "source",
}

TONE_MAPPING_MODES = {"dynamic", "static", "passthrough"}
TARGET_CONTAINERS = {"sdr2020", "sdr709", "hdr10"}
GAMMAS = {"2.2", "2.35", "2.4", "2.6", "pq"}
COLOR_SPACES = {"bt2020", "p3", "rec709"}
DESATURATION_LEVELS = {"off", "auto", "low", "medium", "high"}
MAX_CLL_MODES = {"auto", "always"}
HDR_METADATA_MODES = {"strip", "pass_through"}
MATCH_POLICIES = {"none", "frame_rate", "dynamic_range", "both"}
RESOLUTIONS = {"profile", "source", "3840x2160", "4096x2160", "1920x1080"}
FRAME_RATES = {"source", "23.976", "24", "25", "29.97", "30", "50", "59.94", "60"}
DYNAMIC_RANGES = {"source", "sdr", "hdr"}


def output_profiles() -> list[dict[str, Any]]:
    return deepcopy(OUTPUT_PROFILES)


def profile_for(profile_id: str | None) -> dict[str, Any]:
    return deepcopy(PROFILE_BY_ID.get(profile_id or "", PROFILE_BY_ID[DEFAULT_PROFILE_ID]))


def default_tone_mapping() -> dict[str, Any]:
    return deepcopy(DEFAULT_TONE_MAPPING)


def default_video_mode() -> dict[str, Any]:
    return deepcopy(DEFAULT_VIDEO_MODE)


def effective_output_profile(tone_mapping: dict[str, Any] | None) -> dict[str, Any]:
    settings = normalize_tone_mapping(tone_mapping)
    profile = profile_for(settings.get("output_profile_id"))
    if settings.get("output_profile_id") == "custom" and isinstance(settings.get("custom_profile"), dict):
        custom = settings["custom_profile"]
        for key in (
            "name", "manufacturer", "description", "target_nits", "gamma", "color_space",
            "output_container", "max_light_multiplier", "dynamic_pad", "desaturation",
            "low_display_ratio",
        ):
            if key in custom:
                profile[key] = custom[key]
    return profile


def normalize_tone_mapping(value: Any) -> dict[str, Any]:
    data = default_tone_mapping()
    if isinstance(value, dict):
        for key in data:
            if key in value:
                data[key] = value[key]

    data["enabled"] = _as_bool(data.get("enabled"), DEFAULT_TONE_MAPPING["enabled"])
    data["mode"] = _allowed_str(data.get("mode"), TONE_MAPPING_MODES, DEFAULT_TONE_MAPPING["mode"])
    data["output_profile_id"] = _allowed_str(
        data.get("output_profile_id"),
        set(PROFILE_BY_ID),
        DEFAULT_PROFILE_ID,
    )
    data["target_container"] = _allowed_str(
        data.get("target_container"),
        TARGET_CONTAINERS,
        DEFAULT_TONE_MAPPING["target_container"],
    )
    data["target_nits"] = _as_int(data.get("target_nits"), 100, 20, 1000)
    data["gamma"] = _allowed_str(data.get("gamma"), GAMMAS, DEFAULT_TONE_MAPPING["gamma"])
    data["color_space"] = _allowed_str(
        data.get("color_space"),
        COLOR_SPACES,
        DEFAULT_TONE_MAPPING["color_space"],
    )
    data["max_light_multiplier"] = _as_float(data.get("max_light_multiplier"), 6.0, 1.0, 12.0)
    data["dynamic_pad"] = _as_int(data.get("dynamic_pad"), 4, 0, 7)
    data["desaturation"] = _allowed_str(
        data.get("desaturation"),
        DESATURATION_LEVELS,
        DEFAULT_TONE_MAPPING["desaturation"],
    )
    data["low_display_ratio"] = _as_int(data.get("low_display_ratio"), 31, 0, 100)
    data["max_cll_mode"] = _allowed_str(
        data.get("max_cll_mode"),
        MAX_CLL_MODES,
        DEFAULT_TONE_MAPPING["max_cll_mode"],
    )
    data["max_cll_fallback_nits"] = _as_int(data.get("max_cll_fallback_nits"), 1000, 100, 10000)
    data["static_crossover_nits"] = _as_int(data.get("static_crossover_nits"), 1000, 100, 10000)
    data["hdr_metadata"] = _allowed_str(
        data.get("hdr_metadata"),
        HDR_METADATA_MODES,
        DEFAULT_TONE_MAPPING["hdr_metadata"],
    )
    if not isinstance(data.get("custom_profile"), dict):
        data["custom_profile"] = {}
    return data


def normalize_video_mode(value: Any) -> dict[str, Any]:
    data = default_video_mode()
    if isinstance(value, dict):
        for key in data:
            if key in value:
                data[key] = value[key]

    data["match_policy"] = _allowed_str(
        data.get("match_policy"),
        MATCH_POLICIES,
        DEFAULT_VIDEO_MODE["match_policy"],
    )
    data["base_output_profile_id"] = _allowed_str(
        data.get("base_output_profile_id"),
        set(PROFILE_BY_ID),
        DEFAULT_PROFILE_ID,
    )
    data["resolution"] = _allowed_str(data.get("resolution"), RESOLUTIONS, DEFAULT_VIDEO_MODE["resolution"])
    data["frame_rate"] = _allowed_str(data.get("frame_rate"), FRAME_RATES, DEFAULT_VIDEO_MODE["frame_rate"])
    data["dynamic_range"] = _allowed_str(
        data.get("dynamic_range"),
        DYNAMIC_RANGES,
        DEFAULT_VIDEO_MODE["dynamic_range"],
    )
    return data


def _allowed_str(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip()
    return text if text in allowed else default


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
    return default


def _as_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = default
    return min(max(number, low), high)


def _as_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, low), high)
