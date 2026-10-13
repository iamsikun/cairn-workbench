"""Fields, unread state, discovery summaries and personal "For you" matching on a small fixture."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cairn_catalog import discovery, entities, first_seen, insights, personalize, preferences

SNAPSHOT = "2026-10-12"
# id, journal, date, status, volume, issue, title, [(name, author id)]
PAPERS = [
    (
        "e1",
        "aer",
        "2026-09-01",
        "issue_assigned",
        "116",
        "9",
        "Large Language Models and Wage Dynamics",
        [("Jane Smith", "openalex:A1"), ("Bob Lee", "openalex:A2")],
    ),
    (
        "e2",
        "aer",
        "2026-09-01",
        "issue_assigned",
        "116",
        "9",
        "Firm Wealth Dynamics",
        [("Jane Smith", "openalex:A1")],
    ),
    (
        "e3",
        "aer",
        "2026-08-15",
        "online_first",
        None,
        None,
        "Wealth Inequality and Wealth Taxes",
        [("New Person", "openalex:A3")],
    ),
    (
        "b1",
        "mnsc",
        "2026-08-20",
        "online_first",
        None,
        None,
        "Recommender Systems for Retail",
        [("Ann Ng", "openalex:A4")],
    ),
    (
        "b2",
        "mnsc",
        "2025-11-01",
        "issue_assigned",
        "71",
        "11",
        "Assortment Optimization",
        [("Ann Ng", "openalex:A4")],
    ),
    (
        "old",
        "aer",
        "2020-01-01",
        "issue_assigned",
        "110",
        "1",
        "Wage Dynamics",
        [("Jane Smith", "openalex:A1")],
    ),
    (
        "x1",
        "prl",
        "2026-09-10",
        "online_first",
        None,
        None,
        "Transformers in Plasma",
        [("John Doe", "unresolved-author:x")],
    ),
]
AUTHORS = [
    ("openalex:A1", "Jane Smith", "source_identified"),
    ("openalex:A2", "Bob Lee", "source_identified"),
    ("openalex:A3", "New Person", "source_identified"),
    ("openalex:A4", "Ann Ng", "source_identified"),
    ("openalex:A9", "Ann Ng", "source_identified"),
    ("unresolved-author:x", "John Doe", "unresolved_credit"),
]


def fixture():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE journals(id TEXT,title TEXT,abbreviation TEXT);
    CREATE TABLE papers(id TEXT,title TEXT,journal_id TEXT,entry_type TEXT,date TEXT,record_json TEXT);
    CREATE TABLE publication_events(paper_id TEXT,basis TEXT,date TEXT,date_lower TEXT,date_upper TEXT,precision TEXT,provider TEXT);
    CREATE TABLE author_entities(id TEXT,display_name TEXT,identity_status TEXT,publication_count INTEGER);
    CREATE TABLE author_identifiers(identifier TEXT,author_id TEXT);
    CREATE TABLE author_aliases(author_id TEXT,name TEXT,normalized_name TEXT,provider TEXT);
    CREATE TABLE authorships(paper_id TEXT,position INTEGER,author_id TEXT);
    CREATE TABLE institution_entities(id TEXT,display_name TEXT,identity_status TEXT,publication_count INTEGER,openalex_id TEXT);
    CREATE TABLE institution_aliases(institution_id TEXT,name TEXT,normalized_name TEXT);
    CREATE TABLE affiliations(paper_id TEXT,position INTEGER,institution_id TEXT);
    CREATE TABLE paper_first_seen(paper_id TEXT PRIMARY KEY,first_seen TEXT);
    CREATE VIRTUAL TABLE entity_names USING fts5(kind UNINDEXED,entity_id UNINDEXED,name);
    CREATE VIRTUAL TABLE paper_search USING fts5(paper_id UNINDEXED,title,authors,abstract,journal,tokenize='unicode61 remove_diacritics 2');
    INSERT INTO journals VALUES('aer','American Economic Review','AER'),('mnsc','Management Science','MNSC'),('prl','Physical Review Letters','PRL');
    INSERT INTO institution_entities VALUES('ror:000000001','Washington University in St. Louis','source_identified',2,NULL);
    INSERT INTO institution_aliases VALUES('ror:000000001','Washington University in St. Louis','washington university in st louis');
    """)
    titles = {
        "aer": "American Economic Review",
        "mnsc": "Management Science",
        "prl": "Physical Review Letters",
    }
    for pid, journal, day, status, volume, issue, title, authors in PAPERS:
        record = dict(
            id=pid,
            journal_id=journal,
            journal=titles[journal],
            title=title,
            authors=[a[0] for a in authors],
            date=day,
            date_precision="day",
            published_online=day if status == "online_first" else None,
            published_print=None,
            field_sources={},
            publication_status=status,
            publication_status_evidence="fixture",
            volume=volume,
            issue=issue,
            issue_id=f"{journal}:v{volume}:i{issue}" if volume else None,
            entry_type="article_or_other",
            year=int(day[:4]),
        )
        con.execute(
            "INSERT INTO papers VALUES(?,?,?,?,?,?)",
            (pid, title, journal, "article_or_other", day, json.dumps(record)),
        )
        con.execute(
            "INSERT INTO publication_events VALUES(?,?,?,?,?,?,?)",
            (pid, "issue", day, day, day, "day", "fixture"),
        )
        con.execute(
            "INSERT INTO paper_search VALUES(?,?,?,?,?)",
            (pid, title, "; ".join(a[0] for a in authors), "", titles[journal]),
        )
        con.execute(
            "INSERT INTO paper_first_seen VALUES(?,?)",
            (pid, "2026-10-12" if pid == "e1" else "2026-10-01"),
        )
        for n, (_, author) in enumerate(authors, 1):
            con.execute("INSERT INTO authorships VALUES(?,?,?)", (pid, n, author))
    for author, name, status in AUTHORS:
        count = con.execute(
            "SELECT COUNT(*) FROM authorships WHERE author_id=?", (author,)
        ).fetchone()[0]
        con.execute("INSERT INTO author_entities VALUES(?,?,?,?)", (author, name, status, count))
        con.execute(
            "INSERT INTO author_aliases VALUES(?,?,?,?)",
            (author, name, entities.normalized_name(name), "fixture"),
        )
        con.execute("INSERT INTO entity_names VALUES(?,?,?)", ("author", author, name))
    con.executemany(
        "INSERT INTO affiliations VALUES(?,?,?)",
        [("e1", 1, "ror:000000001"), ("e1", 2, "ror:000000001"), ("e3", 1, "ror:000000001")],
    )
    return con


class FirstSeenTests(unittest.TestCase):
    def test_seed_then_keep_first_dates(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "coverage.json").write_text(json.dumps({"as_of": "2026-10-05"}))
            write = lambda records: (root / "papers.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in records)
            )
            write(
                [
                    {
                        "id": "a",
                        "sources": [
                            {"retrieved_at": "2026-10-03T01:00:00+00:00"},
                            {"retrieved_at": "2026-10-04T01:00:00+00:00"},
                        ],
                    },
                    {"id": "b", "sources": []},
                ]
            )
            self.assertEqual(first_seen.update(root, root)["seeded"], True)
            write(
                [
                    {"id": "a", "sources": [{"retrieved_at": "2026-10-12T01:00:00+00:00"}]},
                    {"id": "c", "sources": []},
                ]
            )
            report = first_seen.update(root, root, snapshot="2026-10-12")
            ledger = {
                json.loads(line)["id"]: json.loads(line)["first_seen"]
                for line in (root / "first-seen.jsonl").read_text().splitlines()
            }
            self.assertEqual(ledger, {"a": "2026-10-03", "c": "2026-10-12"})
            self.assertEqual((report["seeded"], report["new"]), (False, 1))
            with sqlite3.connect(root / "catalog.sqlite") as con:
                self.assertEqual(dict(con.execute("SELECT * FROM paper_first_seen")), ledger)


class FieldFeedTests(unittest.TestCase):
    def setUp(self):
        self.con = fixture()

    def test_field_overview_counts_issues_and_unread(self):
        result = discovery.recent_query(
            self.con,
            "2026-07-13",
            SNAPSHOT,
            group_by="field",
            seen=json.dumps({"economics": "2026-10-05"}),
        )
        fields = {f["field"]: f for f in result["fields"]}
        self.assertEqual(
            [f["field"] for f in result["fields"]], [f["id"] for f in discovery.fields()]
        )
        self.assertEqual((fields["economics"]["total"], fields["economics"]["new_total"]), (3, 1))
        self.assertEqual(
            fields["economics"]["issues"],
            [
                dict(
                    issue_id="aer:v116:i9",
                    journal_id="aer",
                    volume="116",
                    issue="9",
                    volume_series=None,
                    total=2,
                    date="2026-09-01",
                )
            ],
        )
        self.assertEqual((fields["business"]["total"], fields["business"]["new_total"]), (1, 0))
        self.assertEqual(fields["physics"]["journals"][0]["abbreviation"], "PRL")
        fresh = discovery.recent_query(
            self.con,
            "2026-07-13",
            SNAPSHOT,
            group_by="field",
            seen=json.dumps({"economics": "2026-10-05"}),
            new_only="1",
        )
        self.assertEqual(fresh["total"], 1)

    def test_field_filter_on_journal_pages(self):
        result = discovery.recent_query(
            self.con, "2025-10-13", SNAPSHOT, group_by="journal", field="business"
        )
        self.assertEqual(
            [(g["journal_id"], g["field"], g["total"]) for g in result["groups"]],
            [("mnsc", "business", 2)],
        )
        with self.assertRaises(ValueError):
            discovery.recent_query(self.con, "2025-10-13", SNAPSHOT, field="nonsense")
        for seen in ["[]", '{"economics": 5}', "{"]:
            with self.subTest(seen=seen), self.assertRaises(ValueError):
                discovery.recent_query(self.con, "2025-10-13", SNAPSHOT, seen=seen)


class InsightTests(unittest.TestCase):
    def test_active_new_and_institutions(self):
        result = insights.build(fixture(), SNAPSHOT)
        econ = result["fields"]["economics"]["3m"]
        self.assertEqual(
            [(a["name"], a["count"]) for a in econ["active_authors"]], [("Jane Smith", 2)]
        )
        self.assertEqual(econ["active_authors"][0]["spark"][-1], 2)
        # Jane Smith published in 2020, so only first-time authors are new.
        self.assertEqual(sorted(a["name"] for a in econ["new_authors"]), ["Bob Lee", "New Person"])
        self.assertEqual(
            [(i["name"], i["count"], i["previous"]) for i in econ["institutions"]],
            [("Washington University in St. Louis", 2, 0)],
        )
        self.assertEqual(econ["affiliation_coverage"], round(2 / 3, 3))
        self.assertNotIn("unresolved-author:x", json.dumps(result["fields"]["physics"]))
        self.assertEqual(result["fields"]["business"]["12m"]["papers"], 2)

    def test_rising_terms_skip_editorials_series_and_copies(self):
        current = [
            (f"p{i}", f"Frontiers in Operations: Pricing with Privacy Constraints {i}")
            for i in range(3)
        ]
        current += [
            (f"d{i}", "Contribution to the Discussion of Privacy Auditing") for i in range(5)
        ]
        current += [
            (f"q{i}", title)
            for i, title in enumerate(
                [
                    "Dynamic pricing and consumer privacy",
                    "Privacy in two-sided markets",
                    "Differential privacy for platforms",
                ]
            )
        ]
        baseline = [(f"b{i}", "Inventory control") for i in range(20)]
        terms = {t["term"]: t for t in insights.rising_terms(current, baseline)}
        self.assertIn("privacy", terms)
        self.assertNotIn("frontiers", terms)
        self.assertNotIn("contribution", terms)
        self.assertNotIn("auditing", terms)
        # The three near-identical series titles count once.
        self.assertEqual(terms["privacy"]["count"], 4)


class PersonalizeTests(unittest.TestCase):
    TOPICS = {
        "recommendation-systems": dict(
            slug="recommendation-systems",
            title="Recommendation systems",
            aliases=["Recommender systems", "RS"],
            broader=["artificial-intelligence"],
        ),
        "artificial-intelligence": dict(
            slug="artificial-intelligence", title="Artificial Intelligence", aliases=[], broader=[]
        ),
    }

    def build(self, **prefs):
        base = dict(
            fields={"physics": "mute"},
            for_you=dict(keywords=["language model"]),
            people=["Jane Smith", "Ann Ng", "John Doe", "Nobody Here"],
            institutions=["Washington University in St. Louis"],
        )
        return personalize.build(fixture(), {**base, **prefs}, self.TOPICS, SNAPSHOT)

    def test_matches_scores_and_follows(self):
        result = self.build()
        reasons = {
            i: sorted((r["type"], r["label"]) for r in s["reasons"])
            for i, s in result["scores"].items()
        }
        self.assertEqual(
            reasons["e1"],
            [
                ("institution", "Washington University in St. Louis"),
                ("keyword", "language model"),
                ("person", "Jane Smith"),
            ],
        )
        self.assertEqual(result["scores"]["e1"]["score"], 6)
        self.assertEqual(reasons["b1"], [("topic", "Recommendation systems")])
        self.assertEqual(result["for_you"][0], "e1")
        # Broad parent topics and short aliases are skipped; muted fields never reach "For you".
        topics = {t["slug"]: t for t in result["topics"]}
        self.assertEqual(
            {k: t["status"] for k, t in topics.items()},
            {"recommendation-systems": "used", "artificial-intelligence": "broad"},
        )
        self.assertEqual(topics["recommendation-systems"]["matches"], 1)
        self.assertEqual(result["preferences"]["keywords"], ["language model"])
        self.assertNotIn("RS", [t["text"] for t in result["terms"]])
        self.assertNotIn("x1", result["for_you"])
        people = {p["label"]: p for p in result["people"]}
        self.assertEqual(
            (people["Jane Smith"]["status"], people["Jane Smith"]["papers"]),
            ("resolved", ["e1", "e2"]),
        )
        self.assertEqual(people["Ann Ng"]["status"], "needs_choice")
        self.assertEqual(
            sorted(c["id"] for c in people["Ann Ng"]["candidates"]), ["openalex:A4", "openalex:A9"]
        )
        self.assertEqual(
            (people["John Doe"]["status"], people["John Doe"]["name_only"]), ("name_only", ["x1"])
        )
        self.assertEqual(people["Nobody Here"]["status"], "not_found")
        self.assertEqual(result["institutions"][0]["papers"], ["e1", "e3"])
        self.assertEqual(result["papers"]["e1"]["first_seen"], "2026-10-12")
        self.assertTrue(any("Ann Ng" in w for w in result["warnings"]))

    def test_explicit_ids_and_tier_weights(self):
        result = self.build(
            fields={"physics": "skim"},
            people=[{"name": "Ann Ng", "ids": ["openalex:A4"]}, "John Doe"],
            institutions=[],
        )
        self.assertEqual(result["people"][0]["papers"], ["b1", "b2"])
        # Unverified name matches count half, and a skim field halves again.
        self.assertEqual(result["scores"]["x1"]["score"], 0.75)
        self.assertEqual(self.build(journals={"aer": "mute"})["scores"]["e1"]["score"], 0)

    def test_topic_choices(self):
        # An excluded topic adds no reasons but still shows its would-be matches; a listed broad topic is used.
        result = self.build(
            for_you=dict(
                exclude_topics=["recommendation-systems"],
                include_topics=["artificial-intelligence"],
            )
        )
        topics = {t["slug"]: t for t in result["topics"]}
        self.assertEqual(
            (
                topics["recommendation-systems"]["status"],
                topics["recommendation-systems"]["matches"],
            ),
            ("excluded", 1),
        )
        self.assertEqual(topics["artificial-intelligence"]["status"], "used")
        self.assertNotIn("b1", result["scores"])
        off = self.build(for_you=dict(cairn_topics=False))
        self.assertEqual({t["status"] for t in off["topics"]}, {"off"})

    def test_bad_keyword_is_reported(self):
        result = self.build(for_you=dict(keywords=['"unclosed']))
        self.assertTrue(any("unclosed" in w for w in result["warnings"]))


class PreferenceEditTests(unittest.TestCase):
    TOPICS = {"transformers": {}, "mathematics": {}, "linear-algebra": {"broader": ["mathematics"]}}

    def test_round_trip_keeps_values_and_unknown_keys(self):
        prefs = dict(
            fields={"economics": "core", "physics": "mute"},
            journals={"prl": "mute"},
            for_you=dict(
                keywords=["causal inference", 'a: "quoted" phrase'],
                cairn_topics=True,
                exclude_topics=["x"],
                include_topics=[],
                include_broad_topics=False,
                extra=1,
            ),
            people=["Jane Smith", {"name": "Ann Ng", "ids": ["openalex:A4"]}],
            institutions=[],
            notes={"k": "v"},
        )
        text = preferences.render(prefs)
        self.assertIn("# People to follow.", text)
        loaded = preferences.yaml.safe_load(text)
        self.assertEqual(
            loaded["people"], [{"name": "Jane Smith"}, {"name": "Ann Ng", "ids": ["openalex:A4"]}]
        )
        self.assertEqual(
            {k: v for k, v in loaded.items() if k != "people"},
            {k: v for k, v in prefs.items() if k != "people"},
        )

    def test_follow_choose_unfollow(self):
        prefs = {"people": ["Ann Ng"]}
        apply = lambda change: preferences.apply(prefs, change, self.TOPICS)
        apply({"action": "follow", "kind": "author", "name": "Jane Smith", "id": "openalex:A1"})
        apply({"action": "follow", "kind": "author", "name": "Jane Smith", "id": "openalex:A1"})
        apply({"action": "choose", "kind": "author", "label": "Ann Ng", "id": "openalex:A4"})
        apply({"action": "choose", "kind": "author", "label": "Ann Ng", "id": "openalex:A9"})
        self.assertEqual(
            prefs["people"],
            [
                {"name": "Ann Ng", "ids": ["openalex:A4", "openalex:A9"]},
                {"name": "Jane Smith", "ids": ["openalex:A1"]},
            ],
        )
        apply({"action": "unfollow", "kind": "author", "id": "openalex:A9", "label": "Ann Ng"})
        apply(
            {"action": "unfollow", "kind": "author", "id": "orcid:0000-0001", "label": "Jane Smith"}
        )
        self.assertEqual(prefs["people"], [{"name": "Ann Ng", "ids": ["openalex:A4"]}])
        apply({"action": "follow", "kind": "institution", "name": "MIT"})
        self.assertEqual(prefs["institutions"], [{"name": "MIT"}])

    def test_keywords_topics_tiers_and_validation(self):
        prefs = {}
        apply = lambda change: preferences.apply(prefs, change, self.TOPICS)
        apply({"action": "keyword_add", "text": " causal inference "})
        apply({"action": "keyword_add", "text": "Causal Inference"})
        apply({"action": "topic", "slug": "transformers", "include": False})
        apply({"action": "topic", "slug": "mathematics", "include": True})
        apply({"action": "topic", "slug": "linear-algebra", "include": True})
        apply({"action": "tier", "field": "physics", "tier": "mute"})
        self.assertEqual(
            prefs["for_you"],
            {
                "keywords": ["causal inference"],
                "exclude_topics": ["transformers"],
                "include_topics": ["mathematics"],
            },
        )
        self.assertEqual(prefs["fields"], {"physics": "mute"})
        apply({"action": "keyword_remove", "text": "causal inference"})
        self.assertEqual(prefs["for_you"]["keywords"], [])
        for change in [
            {"action": "tier", "field": "physics", "tier": "loud"},
            {"action": "topic", "slug": "unknown", "include": True},
            {"action": "follow", "kind": "author", "name": "x", "id": "javascript:alert(1)"},
            {"action": "follow", "kind": "robot", "name": "x"},
            {"action": "keyword_add", "text": "a\nb"},
            {"action": "drop_tables"},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                apply(change)
        with self.assertRaises(LookupError):
            apply({"action": "choose", "kind": "author", "label": "Nobody", "id": "openalex:A1"})

    def test_save_writes_backup(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "preferences.yaml"
            path.write_text("people: []\n")
            preferences.save(path, {"people": ["Jane Smith"]})
            self.assertEqual(
                preferences.yaml.safe_load(path.read_text())["people"], [{"name": "Jane Smith"}]
            )
            self.assertEqual(path.with_name("preferences.yaml.bak").read_text(), "people: []\n")


if __name__ == "__main__":
    unittest.main()
