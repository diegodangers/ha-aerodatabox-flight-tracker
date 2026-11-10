"""Selected flight-alert recipients: validation only, no delivery."""
import importlib.util
from pathlib import Path
import unittest

source = Path(__file__).resolve().parents[1] / "custom_components/skyledger/notification_config.py"
spec = importlib.util.spec_from_file_location("flight_notification_config_test", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RecipientTests(unittest.TestCase):
    def test_selected_targets_and_quiet_hours(self):
        data = module.selected_recipients(
            ["notify.mobile_app_a", "notify.mobile_app_a"],
            ["media_player.parlor_echo"],
            ["android_tv_fire_tv_192_168_68_72"],
        )
        self.assertEqual(data["phones"], ["notify.mobile_app_a"])
        self.assertEqual(data["alexas"], ["media_player.parlor_echo"])
        self.assertEqual(data["alexa_quiet_start"], "22:00")
        self.assertEqual(data["alexa_quiet_end"], "07:00")

    def test_no_broadcast_defaults(self):
        data = module.selected_recipients()
        self.assertEqual(data["phones"], [])
        self.assertEqual(data["alexas"], [])
        self.assertEqual(data["tv_services"], [])

    def test_rejects_unexpected_domains(self):
        with self.assertRaises(ValueError):
            module.selected_recipients(["person.diego"], [], [])
        with self.assertRaises(ValueError):
            module.selected_recipients([], ["notify.phone"], [])
