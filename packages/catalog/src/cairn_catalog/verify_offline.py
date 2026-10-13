#!/usr/bin/env python3
"""Compare the standalone HTML's network-free queries with SQLite."""

import json
import shutil
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path

from . import catalog_server, discovery, entities, insights, paths


def verify(root=None):
    root = Path(root or paths.data_dir())
    cases = []
    with closing(entities.connect(True, db=root / "catalog.sqlite")) as con:
        for start, end, offset in [
            ("2026-07-13", "2026-10-12", 0),
            ("2026-07-01", "2026-09-30", 30),
            ("2025-01-01", "2026-10-12", 0),
            ("2030-01-01", "2030-03-31", 0),
        ]:
            result = discovery.recent_query(con, start, end, offset=offset)
            cases.append(
                dict(
                    path="recent",
                    args=dict(start_date=start, end_date=end, offset=offset),
                    total=result["total"],
                    uncertain_count=result["uncertain_count"],
                    ids=[p["id"] for p in result["items"]],
                )
            )
        for start, end, offsets in [
            ("2026-07-13", "2026-10-12", {}),
            ("2026-07-13", "2026-10-12", {"mnsc": 10}),
            ("2026-07-13", "2026-10-12", {"mnsc": 20, "aer": 10}),
            ("2026-07-01", "2026-09-30", {"mnsc": 99999}),
            ("2025-01-01", "2026-10-12", {"aer": 10, "msom": 30}),
            ("2026-10-12", "2026-10-12", {}),
            ("2030-01-01", "2030-03-31", {}),
        ]:
            args = dict(
                start_date=start,
                end_date=end,
                group_by="journal",
                journal_offsets=json.dumps(offsets),
            )
            result = discovery.recent_query(con, **args)
            complete = discovery.recent_query(con, start, end, limit=100000)["items"]
            groups = result["groups"]
            assert sum(g["total"] for g in groups) == len(complete) == result["total"]
            assert [g["journal"] for g in groups] == sorted(g["journal"] for g in groups)
            for g in groups:
                matching = [p for p in complete if p["journal_id"] == g["journal_id"]]
                assert len(matching) == g["total"]
                assert g["items"] == matching[g["offset"] : g["offset"] + 10]
            cases.append(
                dict(
                    path="recent",
                    args=args,
                    total=result["total"],
                    uncertain_count=result["uncertain_count"],
                    groups=[
                        {
                            **{k: v for k, v in g.items() if k != "items"},
                            "ids": [p["id"] for p in g["items"]],
                            "author_ids": [
                                [a["author_id"] for a in p["author_entities"]] for p in g["items"]
                            ],
                        }
                        for g in groups
                    ],
                )
            )
        # Field overview and field-filtered journal pages, with and without unread state.
        seen = json.dumps(
            {"business": "2026-10-10", "economics": "2026-10-11", "physics": "2026-10-12"}
        )
        for args in [
            dict(start_date="2026-07-13", end_date="2026-10-12", group_by="field"),
            dict(start_date="2025-10-13", end_date="2026-10-12", group_by="field", seen=seen),
            dict(
                start_date="2025-10-13",
                end_date="2026-10-12",
                group_by="field",
                seen=seen,
                new_only="1",
            ),
            dict(
                start_date="2026-07-13",
                end_date="2026-10-12",
                group_by="journal",
                field="economics",
                journal_offsets=json.dumps({"aer": 10}),
                seen=seen,
            ),
            dict(
                start_date="2026-07-13",
                end_date="2026-10-12",
                group_by="journal",
                field="business",
                seen=seen,
                new_only="1",
            ),
            dict(start_date="2026-07-13", end_date="2026-10-12", field="stats-ml", limit=30),
        ]:
            result = discovery.recent_query(con, **args)
            case = dict(
                path="recent",
                args=args,
                total=result["total"],
                uncertain_count=result["uncertain_count"],
            )
            if "fields" in result:
                assert sum(f["total"] for f in result["fields"]) == result["total"]
                case["fields"] = [
                    {
                        **{k: v for k, v in f.items() if k != "items"},
                        "ids": [p["id"] for p in f["items"]],
                    }
                    for f in result["fields"]
                ]
            elif "groups" in result:
                case["groups"] = [
                    {
                        **{k: v for k, v in g.items() if k != "items"},
                        "ids": [p["id"] for p in g["items"]],
                        "author_ids": [
                            [a["author_id"] for a in p["author_entities"]] for p in g["items"]
                        ],
                    }
                    for g in result["groups"]
                ]
            else:
                case["ids"] = [p["id"] for p in result["items"]]
            cases.append(case)
        cases.append(
            dict(
                path="insights",
                args={},
                insights=insights.build(
                    con, json.loads((root / "coverage.json").read_text())["as_of"]
                ),
            )
        )
        for extra in [
            dict(
                basis="first",
                start_date="2026-07-13",
                end_date="2026-10-12",
                include_uncertain=True,
            ),
            dict(
                basis="first",
                start_date="2026-07-13",
                end_date="2026-10-12",
                entry_type="correction_or_retraction",
            ),
            dict(query="https://doi.org/10.1257/aer.20191569"),
        ]:
            result = catalog_server.papers_query(con, **extra)
            args = {**extra}
            if "include_uncertain" in args:
                args["include_uncertain"] = "1" if args["include_uncertain"] else "0"
            cases.append(
                dict(
                    path="papers",
                    args=args,
                    total=result["total"],
                    ids=[p["id"] for p in result["items"]],
                )
            )
        for query, offset in [("", 0), ("", 20), ("John", 0), ("García", 0)]:
            result = entities.entity_search("author", query, limit=20, offset=offset, con=con)
            cases.append(
                dict(
                    path="entities",
                    args=dict(kind="author", query=query, limit=20, offset=offset),
                    total=result["total"],
                    ids=[e["id"] for e in result["items"]],
                )
            )
        for start, end, basis, uncertain in [
            ("2026-07-01", "2026-09-30", "issue", False),
            ("2026-01-01", "2026-12-31", "issue", False),
            ("2021-10-12", "2026-10-11", "online", True),
            ("2016-10-12", "2026-10-11", "print", False),
            ("2024-03-17", "2026-09-07", "issue", True),
        ]:
            args = dict(
                kind="institution",
                entity="ror:024mw5h28",
                period="range",
                start_date=start,
                end_date=end,
                basis=basis,
                include_uncertain="1" if uncertain else "0",
                limit=30,
            )
            result = entities.publication_query(
                "institution",
                args["entity"],
                period="all",
                start_date=start,
                end_date=end,
                basis=basis,
                include_uncertain=uncertain,
                con=con,
                limit=30,
            )
            cases.append(
                dict(
                    path="publications",
                    args=args,
                    total=result["total"],
                    certain_count=result["certain_count"],
                    uncertain_count=result["uncertain_count"],
                    ids=[p["id"] for p in result["items"]],
                )
            )
        for query, journal, start, end, basis, uncertain in [
            ("causal inference", "mnsc", "", "", "issue", False),
            ("", "aer", "2026-07-01", "2026-09-30", "issue", False),
            ("", "msom", "2021-10-12", "2026-10-11", "online", True),
            ("", "jpe", "2016-10-12", "2026-10-11", "print", False),
            ("", "", "2024-03-17", "2026-09-07", "issue", True),
        ]:
            result = catalog_server.papers_query(
                con,
                query=query,
                journal=journal,
                start_date=start,
                end_date=end,
                basis=basis,
                include_uncertain=uncertain,
            )
            cases.append(
                dict(
                    path="papers",
                    args=dict(
                        query=query,
                        journal=journal,
                        period="all" if not start else "range",
                        start_date=start,
                        end_date=end,
                        basis=basis,
                        include_uncertain="1" if uncertain else "0",
                        limit=30,
                    ),
                    total=result["total"],
                    ids=[p["id"] for p in result["items"]],
                )
            )
        for stage in ["issue_assigned", "online_first", "pending", "unassigned"]:
            result = catalog_server.papers_query(con, journal="mnsc", stage=stage)
            cases.append(
                dict(
                    path="papers",
                    args=dict(journal="mnsc", period="all", stage=stage, limit=30),
                    total=result["total"],
                    ids=[p["id"] for p in result["items"]],
                )
            )
            result = entities.publication_query(
                "institution", "ror:024mw5h28", period="all", stage=stage, con=con, limit=30
            )
            cases.append(
                dict(
                    path="publications",
                    args=dict(
                        kind="institution",
                        entity="ror:024mw5h28",
                        period="all",
                        stage=stage,
                        limit=30,
                    ),
                    total=result["total"],
                    certain_count=result["certain_count"],
                    uncertain_count=result["uncertain_count"],
                    ids=[p["id"] for p in result["items"]],
                )
            )
        # Verify byline identities in the shared result page, not just the detail dialog.
        result = catalog_server.papers_query(con, query="Collective Activism", limit=30)
        cases.append(
            dict(
                path="papers",
                args=dict(query="Collective Activism", period="all", limit=30),
                total=result["total"],
                ids=[p["id"] for p in result["items"]],
                author_ids=[
                    [a["author_id"] for a in p["author_entities"]] for p in result["items"]
                ],
            )
        )
    node = shutil.which("node")
    if not node:
        raise RuntimeError(
            "Node.js is needed only for offline verification, not for opening the catalog"
        )
    # Retain the independent SQLite reference for diagnosing loader failures
    # without repeating the expensive full-scope database queries.
    (root / "offline-query-cases.json").write_text(json.dumps(cases), encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="cairn-offline-test-") as temp:
        reference = Path(temp) / "expected.json"
        reference.write_text(json.dumps(cases))
        subprocess.run(
            [
                node,
                str(Path(__file__).with_name("verify") / "offline.js"),
                str(reference),
                str(root),
            ],
            check=True,
        )
    return len(cases)
