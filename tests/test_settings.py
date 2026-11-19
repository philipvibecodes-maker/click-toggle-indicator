"""Check saved settings and actual Input Remapper routing without real devices."""

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from settings import DEFAULTS, appearance_args, load_settings, save_settings, validate_settings


class SettingsTests(unittest.TestCase):
    def test_round_trip_and_invalid_settings_leave_file_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            self.assertEqual(load_settings(path), DEFAULTS)
            expected = {**DEFAULTS, "boundary": 25, "left_color": "#ff0000", "right_y": -20}
            save_settings(expected, path)
            self.assertEqual(load_settings(path), expected)
            with self.assertRaises(ValueError):
                save_settings({"boundary": 50}, path)
            self.assertEqual(load_settings(path), expected)

    def test_reject_invalid_types_and_ranges(self):
        for values in ({"boundary": True}, {"bottom_right_only": 1}, {"size": 100},
                       {"opacity": float("nan")}, {"left_color": "red"},
                       {"corner_top": 50}, {"right_x": 1.5}, {"unknown": 1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_settings(values)
        args = appearance_args({"left_color": "#ff0000", "right_color": "#00ff00", "right_y": -40})
        self.assertIn("--right-color", args)
        self.assertIn("-40", args)


class PresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import configure_input_remapper as remapper
            from evdev import AbsInfo, ecodes
            from inputremapper.configs.mapping import Mapping
            from inputremapper.configs.preset import Preset
            from inputremapper.injection.context import Context
            from inputremapper.injection.global_uinputs import global_uinputs
            from inputremapper.input_event import InputEvent
            from inputremapper.configs.system_mapping import system_mapping
        except ImportError as error:
            raise unittest.SkipTest(f"Input Remapper required: {error}")
        # These presets use Linux KEY_Fxx names, independent of desktop layouts.
        with patch.object(system_mapping, "_use_xmodmap_symbols"):
            system_mapping.populate()
        cls.remapper, cls.ecodes, cls.AbsInfo = remapper, ecodes, AbsInfo
        cls.Mapping, cls.Preset, cls.Context = Mapping, Preset, Context
        cls.global_uinputs, cls.InputEvent = global_uinputs, InputEvent

    def route_click(self, values, x, y):
        preset = self.Preset()
        for mapping in self.remapper.build_preset(values):
            for event in mapping["input_combination"]:
                event["origin_hash"] = "test"
            preset.add(self.Mapping(**mapping))
        source = Mock()
        source.capabilities.return_value = {self.ecodes.EV_ABS: [
            (axis, self.AbsInfo(0, 0, 1000, 0, 0, 1))
            for axis in (self.ecodes.ABS_X, self.ecodes.ABS_Y)]}
        forward = Mock()
        context = self.Context(preset, {"test": source}, {"test": forward})
        writes = []
        with patch.object(self.global_uinputs, "write", side_effect=lambda event, _target: writes.append(event)):
            for kind, code, value in ((3, 0, x), (3, 1, y), (1, 272, 1), (1, 272, 0)):
                event = self.InputEvent(0, 0, kind, code, value, origin_hash="test")
                for callback in context.get_notify_callbacks(event):
                    callback(event, source=source)
        presses = [code for kind, code, value in writes if kind == 1 and value == 1]
        releases = [code for kind, code, value in writes if kind == 1 and value == 0]
        self.assertEqual(presses, releases, "Every remapped press must release")
        self.assertEqual(len(presses), 1, f"A click must produce exactly one key: {writes}")
        return presses[0]

    def test_regions_through_real_remapper_pipeline(self):
        # Exercise positive thresholds, exclusions, and mixed-axis combinations.
        for boundary in (0.5, 25, 49.5, 50.5, 75, 99.5):
            for corner in (False, True):
                for top in ((25, 85) if corner else (85,)):
                    values = {**DEFAULTS, "boundary": boundary,
                              "bottom_right_only": corner, "corner_top": top}
                    for x, y in ((0, 0), (100, 900), (500, 500), (900, 100), (1000, 1000)):
                        with self.subTest(boundary=boundary, corner=corner, top=top, x=x, y=y):
                            expected = self.ecodes.KEY_F19 if x > boundary * 10 and (not corner or y > top * 10) else self.ecodes.KEY_F24
                            self.assertEqual(self.route_click(values, x, y), expected)

    def test_injector_actions_wait_for_confirmed_states(self):
        group = SimpleNamespace(key="test")
        daemon = Mock()
        with patch("inputremapper.daemon.Daemon.connect", return_value=daemon), patch.object(self.remapper.time, "sleep"):
            daemon.get_state.side_effect = ["STARTING", "RUNNING"]
            self.remapper.daemon_action(group, True)
            self.assertEqual(daemon.get_state.call_count, 2)
            daemon.get_state.reset_mock()
            daemon.get_state.side_effect = ["RUNNING", "STOPPED"]
            self.remapper.daemon_action(group, False)
            self.assertEqual(daemon.get_state.call_count, 2)
            daemon.get_state.side_effect = ["NO_GRAB"]
            with self.assertRaisesRegex(RuntimeError, "NO_GRAB"):
                self.remapper.daemon_action(group, True)

    def test_owned_custom_presets_can_be_updated_but_edits_are_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            group = SimpleNamespace(key="test", name="Test Touchpad")
            with patch.object(self.remapper, "CONFIG_PATH", str(root)), patch.object(
                    self.remapper, "SELECTION_PATH", root / "device.json"):
                path = self.remapper.install(group, False, {**DEFAULTS, "boundary": 25})
                self.remapper.install(group, False, {**DEFAULTS, "boundary": 75})
                modified = json.loads(path.read_text())
                modified[0]["output_symbol"] = "KEY_F20"
                path.write_text(json.dumps(modified))
                with self.assertRaises(RuntimeError):
                    self.remapper.install(group, False, DEFAULTS)
                self.assertEqual(json.loads(path.read_text()), modified)


if __name__ == "__main__":
    unittest.main()
