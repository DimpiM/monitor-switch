"""Parser tests against output captured from real hardware.

The fixtures below are verbatim ``ddcutil`` output from a Samsung Odyssey G9 on a
Raspberry Pi Zero 2 W. They matter because this monitor is the awkward case the
whole profile mechanism exists for — if the parsers handle it, they handle the
well-behaved ones.
"""

import pytest

from monitorctl.ddc import DDCError, _parse_detect, _parse_terse_getvcp
from monitorctl.features import CONTINUOUS, SELECT, parse_capabilities
from monitorctl.profiles import Profile, build_feature_set

DETECT = """\
Display 1
   I2C bus:  /dev/i2c-2
   DRM connector:           card0-HDMI-A-1
   EDID synopsis:
      Mfg id:               SAM - Samsung Electric Company
      Model:                LC49G95T
      Product code:         28754  (0x7052)
      Serial number:        REDACTED
      Binary serial number: 1129860430 (0x43584d4e)
      Model year:           2245
   VCP version:         2.1
"""

CAPABILITIES = """\
Model: FALCON
MCCS version: 2.0
Commands:
   Op Code: 01 (VCP Request)
VCP Features:
   Feature: 10 (Brightness)
   Feature: 12 (Contrast)
   Feature: 14 (Select color preset)
      Values:
         01: sRGB
         04: 5000 K
         05: 6500 K
         0b: User 1
   Feature: 60 (Input Source)
      Values:
         01: VGA-1
         03: DVI-1
   Feature: 62 (Audio speaker volume)
   Feature: C0 (Display usage time)
   Feature: DC (Display Mode)
      Values:
         00: Standard/Default mode
         02: Mixed
   Feature: FF (Manufacturer specific feature)
"""


class TestTerseGetvcp:
    def test_non_continuous(self):
        assert _parse_terse_getvcp("VCP 60 SNC x04\n", 0x60) == (0x04, None)

    def test_continuous_returns_maximum(self):
        assert _parse_terse_getvcp("VCP 10 C 60 100\n", 0x10) == (60, 100)

    def test_rejects_mismatched_code(self):
        with pytest.raises(DDCError):
            _parse_terse_getvcp("VCP 10 C 60 100\n", 0x60)

    def test_rejects_garbage(self):
        with pytest.raises(DDCError):
            _parse_terse_getvcp("Maximum DDC retries exceeded", 0x60)


class TestDetect:
    def test_extracts_identity(self):
        info = _parse_detect(DETECT)
        assert info.mfg == "SAM"
        assert info.model == "LC49G95T"
        assert info.vcp_version == "2.1"
        assert info.connector == "card0-HDMI-A-1"

    def test_normalises_product_code_to_hex(self):
        assert _parse_detect(DETECT).product_code == "0x7052"


class TestCapabilities:
    def test_continuous_feature_without_values(self):
        features = parse_capabilities(CAPABILITIES)
        brightness = features.get("brightness")
        assert brightness.type == CONTINUOUS
        assert brightness.vcp == 0x10

    def test_select_feature_gets_its_values(self):
        preset = parse_capabilities(CAPABILITIES).get("color_preset")
        assert preset.type == SELECT
        assert [o.write for o in preset.options] == [0x01, 0x04, 0x05, 0x0B]
        assert preset.option_by_id("srgb").label == "sRGB"

    def test_write_equals_read_when_auto_detected(self):
        preset = parse_capabilities(CAPABILITIES).get("color_preset")
        assert all(o.write == o.read for o in preset.options)

    def test_input_source_is_marked_for_fast_polling(self):
        assert parse_capabilities(CAPABILITIES).get("input_source").fast_poll

    def test_unknown_code_is_skipped_by_default(self):
        """Reading an unknown code costs ~860 ms per poll and rarely pays off."""
        assert parse_capabilities(CAPABILITIES).get("vcp_ff") is None

    def test_unknown_code_can_be_surfaced_on_request(self):
        unknown = parse_capabilities(CAPABILITIES, include_unknown=True).get("vcp_ff")
        assert unknown is not None
        assert unknown.readonly

    def test_sensor_features_are_categorised(self):
        assert parse_capabilities(CAPABILITIES).get("usage_hours").category == "sensor"

    def test_select_without_declared_values_stays_settable(self):
        """A profile must be able to supply values the monitor did not list.

        Forcing read-only here would survive the profile overlay and silently
        disable the very feature the profile just repaired.
        """
        features = parse_capabilities(
            "VCP Features:\n   Feature: 8D (Audio Mute)\n"
        )
        assert features.get("mute").readonly is False

    def test_static_features_are_flagged(self):
        features = parse_capabilities(
            "VCP Features:\n   Feature: C9 (Display firmware level)\n"
        )
        assert features.get("firmware_level").static


class TestProfileOverlay:
    """The reason this project has profiles at all."""

    def profile(self):
        return Profile(
            name="test",
            features={
                "input_source": {
                    "vcp": 0x60,
                    "type": "select",
                    "options": [
                        {"id": "dp1", "label": "DisplayPort 1",
                         "write": 0x0F, "read": 0x03},
                        {"id": "dp2", "label": "DisplayPort 2",
                         "write": 0x10, "read": 0x04},
                        {"id": "hdmi", "label": "HDMI",
                         "write": 0x11, "read": 0x01, "guard": "local_video"},
                    ],
                },
                "contrast": False,
            },
        )

    def test_profile_replaces_the_lying_capabilities_values(self):
        features = build_feature_set(CAPABILITIES, self.profile())
        options = features.get("input_source").options
        assert [o.id for o in options] == ["dp1", "dp2", "hdmi"]

    def test_write_and_read_values_stay_distinct(self):
        features = build_feature_set(CAPABILITIES, self.profile())
        dp2 = features.get("input_source").option_by_id("dp2")
        assert (dp2.write, dp2.read) == (0x10, 0x04)

    def test_reverse_lookup_uses_the_read_value(self):
        features = build_feature_set(CAPABILITIES, self.profile())
        assert features.get("input_source").option_by_read(0x04).id == "dp2"
        assert features.get("input_source").option_by_read(0x10) is None

    def test_guard_survives_the_overlay(self):
        features = build_feature_set(CAPABILITIES, self.profile())
        assert features.get("input_source").option_by_id("hdmi").guard == "local_video"

    def test_false_removes_a_feature(self):
        assert build_feature_set(CAPABILITIES, self.profile()).get("contrast") is None

    def test_untouched_features_survive(self):
        features = build_feature_set(CAPABILITIES, self.profile())
        assert features.get("brightness") is not None

    def test_local_overrides_beat_the_profile(self):
        features = build_feature_set(
            CAPABILITIES, self.profile(), {"brightness": {"label": "Panel brightness"}}
        )
        assert features.get("brightness").label == "Panel brightness"

    def test_profile_can_introduce_an_undeclared_feature(self):
        features = build_feature_set(
            CAPABILITIES, None, {"volume_alt": {"vcp": 0x64, "label": "Alt volume"}}
        )
        assert features.get("volume_alt").vcp == 0x64


class TestShippedProfiles:
    def test_reference_profile_matches_its_monitor(self):
        from monitorctl.profiles import load_profiles, select_profile

        info = _parse_detect(DETECT)
        profile = select_profile(info, load_profiles())
        assert profile is not None
        assert "LC49G95T" in profile.name

    def test_generic_profile_never_matches_automatically(self):
        from monitorctl.profiles import load_profiles

        generic = next(p for p in load_profiles() if p.name == "generic")
        assert not generic.matches(_parse_detect(DETECT))

    def test_reference_profile_carries_the_measured_values(self):
        from monitorctl.profiles import load_profiles, select_profile

        profile = select_profile(_parse_detect(DETECT), load_profiles())
        features = build_feature_set(CAPABILITIES, profile)
        source = features.get("input_source")
        assert source.option_by_id("dp1").write == 0x0F
        assert source.option_by_id("dp1").read == 0x03
        assert source.option_by_id("dp2").write == 0x10
        assert source.option_by_id("dp2").read == 0x04
        assert source.option_by_id("hdmi").guard == "local_video"

    def test_reference_profile_keeps_power_read_only(self):
        from monitorctl.profiles import load_profiles, select_profile

        profile = select_profile(_parse_detect(DETECT), load_profiles())
        features = build_feature_set(CAPABILITIES, profile)
        assert features.get("power").readonly

    def test_capabilities_multiplier_is_raised_for_this_monitor(self):
        from monitorctl.profiles import load_profiles, select_profile

        profile = select_profile(_parse_detect(DETECT), load_profiles())
        assert profile.settings.capabilities_sleep_multiplier == 8
