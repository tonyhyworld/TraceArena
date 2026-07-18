import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.replay import settle


class IncidentResponseReplayTest(unittest.TestCase):
    def test_fixture_records_rejection_and_resolves(self):
        fixture = json.loads((Path(__file__).parent / "fixture.json").read_text(encoding="utf-8"))
        result = settle(fixture)
        rejected = [event for event in result["events"] if not event["accepted"]]
        self.assertEqual(rejected[0]["reason"], "passing_health_check_required")
        self.assertEqual(result["settlement"]["incident_status"], "resolved")
        self.assertEqual(result["settlement"]["service_health"], 100)


if __name__ == "__main__":
    unittest.main()
