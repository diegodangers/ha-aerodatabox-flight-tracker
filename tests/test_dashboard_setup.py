"""Pure dashboard installation guard tests without a running HA instance."""
import ast
from pathlib import Path
import unittest

source = Path(__file__).resolve().parents[1] / "custom_components/skyledger/dashboard_setup.py"
tree = ast.parse(source.read_text())
function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "should_create_dashboard")
namespace = {"DASHBOARD_PATH": "skyledger-flights", "LEGACY_PATH": "upcoming-flights"}
exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)


class DashboardGuardTests(unittest.TestCase):
    def test_fresh_install(self):
        self.assertTrue(namespace["should_create_dashboard"]({"lovelace"}))

    def test_existing_legacy_dashboard_preserved(self):
        self.assertFalse(namespace["should_create_dashboard"]({"upcoming-flights"}))

    def test_existing_skyledger_dashboard_preserved(self):
        self.assertFalse(namespace["should_create_dashboard"]({"skyledger-flights"}))

    def test_unrelated_dashboards_do_not_block_install(self):
        self.assertTrue(namespace["should_create_dashboard"]({"home-mobile", "lovelace"}))
