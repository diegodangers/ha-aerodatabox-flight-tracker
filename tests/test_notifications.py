"""Test native notification routing without a Home Assistant connection."""
import importlib.util
from datetime import datetime
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "custom_components" / "aerodatabox_flights" / "notifications.py"
spec = importlib.util.spec_from_file_location("flight_notifications_test", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

RECORD = {"flight_number": "DL2084", "metadata": {"departure_airport": "ATL", "arrival_airport": "DTW"}}


class NotificationTests(unittest.TestCase):
    def test_quiet_hours(self):
        for hour in [0, 6, 22, 23]:
            self.assertFalse(module.in_alexa_hours(datetime(2026, 10, 31, hour)))
        for hour in [7, 9, 21]:
            self.assertTrue(module.in_alexa_hours(datetime(2026, 10, 31, hour)))

    def test_route_and_channels(self):
        actions = module.notification_plan(
            RECORD, "takeoff", datetime(2026, 10, 31, 9),
            ["notify.phone_a", "notify.phone_a"], ["media_player.echo"],
            ["android_tv_fire_tv_192_168_68_72"],
        )
        self.assertEqual(len(actions), 3)
        self.assertEqual(actions[0]["data"]["entity_id"], ["notify.phone_a"])
        self.assertIn("ATL to DTW has taken off", actions[0]["data"]["message"])
        self.assertEqual(actions[1]["service"], "alexa_media")
        self.assertEqual(actions[2]["domain"], "notify")

    def test_alexa_only_suppressed_at_night(self):
        actions = module.notification_plan(
            RECORD, "landing", datetime(2026, 10, 31, 23),
            ["notify.phone_a"], ["media_player.echo"], ["android_tv_fire_tv_192_168_68_72"],
        )
        self.assertEqual([a["service"] for a in actions], ["send_message", "android_tv_fire_tv_192_168_68_72"])

    def test_tv_filtered_when_off(self):
        actions = module.notification_plan(
            RECORD, "takeoff", datetime(2026, 10, 31, 12),
            ["notify.diego_2", "notify.keris_iphone"],
            ["media_player.living_room_alexa"],
            ["android_tv_fire_tv_192_168_68_72"], tv_is_on=False,
        )
        self.assertEqual([a["service"] for a in actions], ["send_message", "alexa_media"])
        self.assertEqual(len(actions[0]["data"]["entity_id"]), 2)

    def test_enabled_for_coordinated_cutover(self):
        self.assertTrue(module.NATIVE_ALERTS_ENABLED)
