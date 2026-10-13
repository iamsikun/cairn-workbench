import unittest

from cairn_catalog.discovery import first_publication, journal_pages


class FirstPublicationTests(unittest.TestCase):
    def test_issue_assignment_does_not_reset_online_first_date(self):
        first = {"published_online": "2026-07-19", "date": "2026-07-19", "date_precision": "day"}
        assigned = {
            **first,
            "published_print": "2026-10",
            "date": "2026-10",
            "date_precision": "month",
        }
        self.assertEqual(first_publication(first)["first_date"], "2026-07-19")
        self.assertEqual(first_publication(assigned)["first_date"], "2026-07-19")

    def test_later_digital_edition_does_not_promote_old_paper(self):
        p = first_publication(
            {"published_online": "2026-08-12", "published_print": "1987-04", "date": "1987-04"}
        )
        self.assertEqual((p["first_lower"], p["first_upper"]), ("1987-04-01", "1987-04-30"))
        self.assertEqual(p["first_date"], "1987-04")

    def test_year_uncertainty_is_not_overridden_by_a_later_exact_date(self):
        p = first_publication(
            {"date": "2026", "date_precision": "year", "published_online": "2026-08-20"}
        )
        self.assertEqual((p["first_lower"], p["first_upper"]), ("2026-01-01", "2026-08-20"))
        self.assertEqual(p["first_precision"], "range")

    def test_provider_unverified_day_stays_a_year_interval(self):
        p = first_publication({"date": "2026-08-20", "date_precision": "provider_day_unverified"})
        self.assertEqual((p["first_lower"], p["first_upper"]), ("2026-01-01", "2026-12-31"))
        self.assertEqual(p["first_precision"], "provider_date_unverified")
        self.assertEqual(p["first_date"], "2026")

    def test_month_and_missing_dates(self):
        p = first_publication({"date": "2024-02"})
        self.assertEqual(p["first_upper"], "2024-02-29")
        self.assertEqual(first_publication({})["first_date"], None)


class JournalPaginationTests(unittest.TestCase):
    def setUp(self):
        self.journals = [
            dict(id="b", title="Beta"),
            dict(id="a", title="Alpha"),
            dict(id="c", title="Empty"),
        ]
        self.rows = [dict(id=f"{j}-{i}", journal_id=j) for i in range(23) for j in ["b", "a"]]

    def test_all_journals_counted_before_independent_pagination(self):
        first = journal_pages(self.rows, self.journals, "")
        next_page = journal_pages(self.rows, self.journals, '{"a":10}')
        self.assertEqual([g["journal"] for g in first], ["Alpha", "Beta"])
        self.assertEqual([g["total"] for g in first], [23, 23])
        self.assertEqual(
            [p["id"] for p in next_page[0]["items"]], [f"a-{i}" for i in range(10, 20)]
        )
        self.assertEqual(first[1], next_page[1])

    def test_empty_short_and_out_of_range_pages(self):
        self.assertEqual(journal_pages([], self.journals, ""), [])
        short = journal_pages(self.rows[:6], self.journals, '{"a":1000}')
        self.assertEqual((short[0]["offset"], len(short[0]["items"])), (0, 3))
        last = journal_pages(self.rows, self.journals, '{"a":999}')
        self.assertEqual((last[0]["offset"], len(last[0]["items"])), (20, 3))

    def test_malformed_offsets(self):
        for value in [
            "null",
            "[]",
            "1",
            "{",
            '{"a":-1}',
            '{"a":1.5}',
            '{"a":true}',
            '{"a":"10"}',
            '{"a":9007199254740992}',
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                journal_pages(self.rows, self.journals, value)
