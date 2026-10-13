"""Derived surname index for author browsing; citation author order is unchanged."""

import json
import re
import unicodedata
from collections import Counter, defaultdict

from . import paths

ROOT = paths.data_dir()
PARTICLES = {
    "da",
    "de",
    "del",
    "della",
    "den",
    "der",
    "di",
    "dos",
    "du",
    "la",
    "le",
    "ten",
    "ter",
    "van",
    "von",
    "zu",
    "zur",
}
SUFFIX = re.compile(r"(?:\s+|,\s*)(?:jr\.?|sr\.?|ii|iii|iv|v|vi)$", re.I)


def alphabetic(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", value))


def name_parts(display_name):
    name = SUFFIX.sub("", str(display_name or "").strip())
    if "," in name:
        family, given = name.split(",", 1)
        return family.strip(), given.strip()
    words = name.split()
    if not words:
        return "", ""
    start = len(words) - 1
    while start > 1 and alphabetic(words[start - 1]) in PARTICLES:
        start -= 1
    return " ".join(words[start:]), " ".join(words[:start])


def sort_key(family, given):
    key = alphabetic(family)
    return (key if any(c.isalpha() for c in key) else "\uffff") + "\x1f" + alphabetic(given)


def inferred_sort_key(display_name):
    return sort_key(*name_parts(display_name))


def exists(con):
    return (
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='author_directory'"
        ).fetchone()
        is not None
    )


def build(con):
    votes = defaultdict(Counter)
    for row in con.execute(
        "SELECT s.author_id,a.details_json FROM authorships s JOIN authors a ON a.paper_id=s.paper_id AND a.position=s.position"
    ):
        details = json.loads(row[1] or "{}")
        family = SUFFIX.sub("", str(details.get("family") or "").strip())
        if family:
            votes[row[0]][(family, str(details.get("given") or "").strip())] += 1
    rows = []
    for identity, name in con.execute("SELECT id,display_name FROM author_entities"):
        family, given = name_parts(name)
        source = "display_name_inference"
        if votes[identity]:
            family, given = min(
                votes[identity],
                key=lambda pair: (
                    -votes[identity][pair],
                    not alphabetic(name).endswith(alphabetic(pair[0])),
                    alphabetic(pair[0]),
                    alphabetic(pair[1]),
                ),
            )
            source = "recorded_family_name"
        rows.append((identity, family, given, sort_key(family, given), source))
    con.execute(
        "CREATE TABLE IF NOT EXISTS author_directory(author_id TEXT PRIMARY KEY REFERENCES author_entities(id),family_name TEXT NOT NULL,given_names TEXT NOT NULL,sort_key TEXT NOT NULL,surname_source TEXT NOT NULL)"
    )
    con.execute("DELETE FROM author_directory")
    con.executemany("INSERT INTO author_directory VALUES(?,?,?,?,?)", rows)
    con.execute(
        "CREATE INDEX IF NOT EXISTS author_directory_sort ON author_directory(sort_key,author_id)"
    )
    return {
        "authors": len(rows),
        "recorded_family_names": sum(r[4] == "recorded_family_name" for r in rows),
    }
