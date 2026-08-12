import unittest
from unittest.mock import patch

from hdpcg.cli import _build_config, build_parser, cmd_generate


class TestCli(unittest.TestCase):
    def test_documented_generate_command_builds_config(self):
        args = build_parser().parse_args(["generate"])
        config = _build_config(args)
        self.assertEqual(config["cpSatNumWorkers"], 1)
        self.assertEqual(config["generatorMode"], "hdpcg_incremental")

    def test_package_does_not_claim_unrequested_global_validation(self):
        args = build_parser().parse_args(["generate"])
        etg = {
            "nodes": [{"id": "S", "type": "Start"}, {"id": "G", "type": "Goal"}],
            "edges": [{"id": "E0", "from": "S", "to": "G", "length": 10}],
        }
        level = {
            "meta": {"component_generation": {"selection_stats": {"local_validation_calls": 1}}},
            "etg": etg,
            "platforms": [],
            "enemies": [],
            "keys": [],
            "locks": [],
            "checkpoints": [],
            "mapping": {"node": {}, "edge": {}},
            "anchors": {},
        }
        captured = {}

        def capture_package(_level, report, _options):
            captured.update(report)
            return {"validation": report}

        with (
            patch("hdpcg.cli.create_etg", return_value=etg),
            patch("hdpcg.cli.generate_level", return_value=level),
            patch("hdpcg.cli.build_export_package", side_effect=capture_package),
            patch("hdpcg.cli.write_json"),
            patch("pathlib.Path.mkdir"),
        ):
            cmd_generate(args)
        self.assertEqual(captured["status"], "not_run")
        self.assertEqual(captured["scope"], "generation_time_local")
        self.assertIsNone(captured["topology"])
        self.assertEqual(captured["generation_diagnostics"]["local_validation_calls"], 1)

    def test_package_contains_requested_global_validation(self):
        args = build_parser().parse_args(["generate", "--global-topology"])
        etg = {
            "nodes": [{"id": "S", "type": "Start"}, {"id": "G", "type": "Goal"}],
            "edges": [{"id": "E0", "from": "S", "to": "G", "length": 10}],
        }
        level = {
            "meta": {},
            "etg": etg,
            "platforms": [],
            "enemies": [],
            "keys": [],
            "locks": [],
            "checkpoints": [],
            "mapping": {"node": {}, "edge": {}},
            "anchors": {},
        }
        topology = {"ok": False, "reason": "unreachable"}
        captured = {}

        def capture_package(_level, report, _options):
            captured.update(report)
            return {"validation": report}

        with (
            patch("hdpcg.cli.create_etg", return_value=etg),
            patch("hdpcg.cli.generate_level", return_value=level),
            patch("hdpcg.cli.validate_global_topology", return_value=topology),
            patch("hdpcg.cli.build_export_package", side_effect=capture_package),
            patch("hdpcg.cli.write_json"),
            patch("pathlib.Path.mkdir"),
        ):
            cmd_generate(args)
        self.assertEqual(captured["status"], "failed")
        self.assertEqual(captured["scope"], "global_5d")
        self.assertEqual(captured["issues"], ["unreachable"])
        self.assertEqual(captured["topology"], topology)

    def test_package_marks_generation_without_validation(self):
        args = build_parser().parse_args(["generate", "--no-topology-validate"])
        etg = {
            "nodes": [{"id": "S", "type": "Start"}, {"id": "G", "type": "Goal"}],
            "edges": [{"id": "E0", "from": "S", "to": "G", "length": 10}],
        }
        level = {
            "meta": {},
            "etg": etg,
            "platforms": [],
            "enemies": [],
            "keys": [],
            "locks": [],
            "checkpoints": [],
            "mapping": {"node": {}, "edge": {}},
            "anchors": {},
        }
        captured = {}

        def capture_package(_level, report, _options):
            captured.update(report)
            return {"validation": report}

        with (
            patch("hdpcg.cli.create_etg", return_value=etg),
            patch("hdpcg.cli.generate_level", return_value=level),
            patch("hdpcg.cli.build_export_package", side_effect=capture_package),
            patch("hdpcg.cli.write_json"),
            patch("pathlib.Path.mkdir"),
        ):
            cmd_generate(args)
        self.assertEqual(captured["scope"], "generation_only")
        self.assertIn("local_validation_disabled", captured["warnings"])


if __name__ == "__main__":
    unittest.main()
