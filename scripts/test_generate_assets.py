import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

import generate_assets


class GenerateAssetsTests(unittest.TestCase):
    def test_parse_graphql_stats_aggregates_languages_and_monthly_activity(self) -> None:
        payload = {
            "data": {
                "user": {
                    "createdAt": "2018-06-27T05:02:49Z",
                    "followers": {"totalCount": 16},
                    "contributionsCollection": {
                        "contributionCalendar": {
                            "totalContributions": 420,
                            "weeks": [
                                {
                                    "contributionDays": [
                                        {"date": "2026-10-01", "contributionCount": 12},
                                        {"date": "2026-10-02", "contributionCount": 8},
                                        {"date": "2026-11-10", "contributionCount": 55},
                                    ]
                                }
                            ],
                        }
                    },
                    "repositories": {
                        "totalCount": 4,
                        "nodes": [
                            {
                                "name": "a",
                                "stargazerCount": 2,
                                "languages": {
                                    "edges": [
                                        {"size": 600, "node": {"name": "Python", "color": "#3572A5"}},
                                        {"size": 400, "node": {"name": "C", "color": "#555555"}},
                                    ]
                                },
                            },
                            {"name": "b", "stargazerCount": 3, "languages": {"edges": []}},
                        ],
                    },
                }
            }
        }
        stats = generate_assets.parse_graphql_stats(payload, login="mop4r")
        self.assertEqual(stats.since_year, 2018)
        self.assertEqual(stats.followers, 16)
        self.assertEqual(stats.public_repos, 4)
        self.assertEqual(stats.total_stars, 5)
        self.assertEqual(stats.total_contributions, 420)
        self.assertEqual(stats.languages[0], ("Python", 60.0, "#3572A5"))
        self.assertEqual(stats.languages[1], ("C", 40.0, "#555555"))
        self.assertEqual(stats.monthly_counts, (("Oct", 20), ("Nov", 55)))

    def test_generate_all_produces_valid_self_contained_svgs_and_escapes_xml(self) -> None:
        stats = generate_assets.ProfileStats(
            login='mop4r<script>"&',
            since_year=2018,
            public_repos=5,
            total_stars=2,
            followers=16,
            total_contributions=123,
            languages=(("Python", 70.0, "#3572A5"), ("C", 30.0, "#555555")),
            monthly_counts=(("Oct", 40), ("Nov", 83)),
        )
        now = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            files = generate_assets.generate_all(out, stats, now)
            self.assertEqual(len(files), 12)
            for path in files:
                text = path.read_text(encoding="utf-8")
                # Todo SVG deve ser XML válido e sem recursos externos (R169)
                root = ET.fromstring(text)
                self.assertTrue(root.tag.endswith("svg"))
                self.assertNotIn("<image", text)
                self.assertNotIn("https://", text)
                self.assertNotIn('href="http', text)
                self.assertNotIn("<script>", text)


if __name__ == "__main__":
    unittest.main()
