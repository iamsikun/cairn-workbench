"""Require independent journal identity evidence before admitting indexed records.

An OpenAlex source bucket is a discovery mechanism, not journal membership proof.
Publisher/archival deposits and publisher-supplied indexes provide identity evidence;
an individually checked publisher TOC is recorded separately, never inferred.
"""

import json
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from urllib.parse import urlparse

PUBLISHERS = {
    "aer": {"American Economic Association"},
    "qje": {"Oxford University Press (OUP)", "JSTOR", "MIT Press"},
    "ecta": {"The Econometric Society", "JSTOR", "Wiley", "Wiley-Blackwell"},
    "jpe": {"University of Chicago Press"},
    "restud": {"Oxford University Press (OUP)", "JSTOR", "Wiley", "Wiley-Blackwell"},
    "jmr": {"SAGE Publications", "JSTOR", "American Marketing Association"},
    **{
        j: {"Institute for Operations Research and the Management Sciences (INFORMS)"}
        for j in ["mnsc", "mksc", "opre", "msom"]
    },
}


def identifier(value):
    return (
        re.sub(r"^https?://(?:dx\.)?doi\.org/", "", str(value or "").lower()).removeprefix("doi:")
        or None
    )


def crossref_evidence(raw, journal):
    actual = {s.upper() for s in raw.get("ISSN", [])}
    expected = {s.upper() for s in journal["issns"]}
    if not actual & expected:
        return None, "The source record does not contain a target journal ISSN."
    publisher = raw.get("publisher")
    if publisher not in journal.get("publishers", PUBLISHERS.get(journal["id"], set())):
        return (
            None,
            "The source publisher does not match the target journal or its archival registrar.",
        )
    doi = identifier(raw.get("DOI"))
    resource = ((raw.get("resource") or {}).get("primary") or {}).get("URL")
    return {
        "status": "publisher_deposit_confirmed",
        "provider": "crossref",
        "doi": doi,
        "issns": sorted(actual & expected),
        "publisher": publisher,
        "record_url": "https://api.crossref.org/works/" + doi if doi else None,
        "publisher_record_url": resource,
        "explanation": "Journal ISSN and publisher checked against the actual deposited record; not inferred from a search bucket.",
    }, None


class Gate:
    def __init__(self, root, same_paper, titlekey):
        self.root, self.same_paper, self.titlekey = root, same_paper, titlekey
        self.by_doi, self.by_title = {}, defaultdict(list)
        path = root / "raw/membership/archive-evidence.json"
        self.reviews = (
            json.loads(path.read_text()) if path.exists() else {"confirmed": [], "excluded": []}
        )
        self.confirmed = {
            (r["journal_id"], identifier(r["doi"])): r for r in self.reviews["confirmed"]
        }
        self.excluded = {r["source_id"]: r for r in self.reviews["excluded"]}
        self.quarantine, self.counts = [], Counter()

    def check(self, raw, provider, journal, record, provenance):
        source_id = provenance["id"]
        review = self.excluded.get(source_id)
        evidence, reason = None, None
        if review:
            reason = review["reason"]
        elif provider == "crossref":
            evidence, reason = crossref_evidence(raw, journal)
        elif provider == "repec":
            # This exact series is supplied by the AEA, not an unrestricted name search.
            url = urlparse(raw.get("url") or "")
            if (
                journal["id"] == "aer"
                and url.hostname == "ideas.repec.org"
                and url.path.startswith("/a/aea/aecrev/")
            ):
                evidence = {
                    "status": "publisher_supplied_index_confirmed",
                    "provider": "repec",
                    "publisher": "American Economic Association",
                    "record_url": raw["url"],
                    "explanation": "Record from the AEA-supplied American Economic Review series in RePEc.",
                }
            else:
                reason = "No recognized publisher-supplied journal series."
        elif provider == "journal_archive":
            prefixes = journal.get("archive_prefixes", [])
            article_url = raw.get("url") or ""
            archive_url = provenance.get("archive_url") or ""
            if (
                prefixes
                and raw.get("title")
                and any(article_url.startswith(prefix) for prefix in prefixes)
                and any(archive_url.startswith(prefix) for prefix in prefixes)
            ):
                evidence = {
                    "status": "publisher_archive_confirmed",
                    "provider": provider,
                    "record_url": article_url,
                    "archive_status": "confirmed",
                    "archive_url": archive_url,
                    "archive_checked_at": provenance["retrieved_at"],
                    "archive_match": "publisher_article_record",
                    "explanation": "Article metadata parsed from the configured public publisher archive; original source response retained.",
                }
            else:
                reason = "The article and retained archive response are not from the configured publisher archive."
        else:
            doi = identifier(raw.get("doi"))
            known = self.by_doi.get(doi) if doi else None
            if known and known["journal_id"] != journal["id"]:
                reason = "DOI belongs to a different verified catalog journal."
            elif known:
                left, right = self.titlekey(known)[1], self.titlekey(record)[1]
                if left and right and SequenceMatcher(None, left, right).ratio() < 0.8:
                    reason = "The indexed title conflicts with the publisher record for this DOI."
                else:
                    evidence = {**known["journal_membership"], "matched_by": "same_doi"}
            else:
                # A duplicate may have a JSTOR registration or no DOI. Require exact
                # title AND volume/issue/start page, not a name or a vague similarity.
                citation_fields = (
                    ["volume"]
                    if record.get("publication_unit") == "volume"
                    else ["volume", "issue"]
                )
                candidates = [
                    r
                    for r in self.by_title[self.titlekey(record)]
                    if all(record.get(f) and r.get(f) == record[f] for f in citation_fields)
                    and record.get("pages")
                    and r.get("pages")
                    and self.same_paper(r, record)
                ]
                if doi and not doi.startswith("10.2307/"):
                    candidates = []  # Working-paper / book / repository DOIs are not journal registrations.
                if len(candidates) == 1:
                    evidence = {
                        **candidates[0]["journal_membership"],
                        "matched_by": "exact_title_and_issue_citation",
                    }
                else:
                    reason = "OpenAlex journal assignment has no independent publisher/registry or exact verified issue-citation match."
            archive = self.confirmed.get((journal["id"], doi))
            if not evidence and archive:
                evidence = {
                    "status": "publisher_archive_confirmed",
                    "provider": "publisher",
                    "record_url": archive["url"],
                    "explanation": "Exact DOI appears in a checked publisher archive record.",
                }
        if not evidence:
            self.counts[provider + ":" + journal["id"] + ":quarantined"] += 1
            self.quarantine.append(
                {
                    "source_id": source_id,
                    "provider": provider,
                    "requested_journal_id": journal["id"],
                    "status": "confirmed_other_journal"
                    if review
                    else "unverified_journal_membership",
                    "reason": reason,
                    "review": review,
                    "record": record,
                }
            )
            return False
        evidence = dict(evidence)
        archive = self.confirmed.get((journal["id"], record.get("doi")))
        evidence["archive_status"] = (
            "confirmed" if archive or provider == "journal_archive" else "not_individually_checked"
        )
        if archive:
            evidence["archive_url"] = archive["url"]
            evidence["archive_checked_at"] = archive["checked_at"]
            evidence["archive_match"] = archive.get("archive_match", "exact_doi_in_publisher_toc")
        record["journal_membership"] = evidence
        self.counts[provider + ":" + journal["id"] + ":admitted"] += 1
        if provider in ["crossref", "repec", "journal_archive"]:
            self.by_title[self.titlekey(record)].append(record)
            if record.get("doi"):
                self.by_doi[record["doi"]] = record
        return True

    def report(self, records):
        quarantined = {q["source_id"] for q in self.quarantine}
        admitted_ids = {s["id"] for r in records for s in r["sources"]}
        return {
            "policy_version": "1.0",
            "journal_identity_required": True,
            "language_is_not_a_membership_test": True,
            "counts_by_source": dict(self.counts),
            "quarantined_source_records": len(self.quarantine),
            "quarantined_source_identities": len(quarantined),
            "identities_absent_from_main_catalog": len(quarantined - admitted_ids),
            "main_catalog_membership": dict(
                Counter(r["journal_membership"]["status"] for r in records)
            ),
            "publisher_archive_checked_papers": sum(
                r["journal_membership"]["archive_status"] == "confirmed" for r in records
            ),
            "publisher_archive_direct_records": sum(
                r["journal_membership"].get("archive_match") == "publisher_article_record"
                for r in records
            ),
            "publisher_archive_completeness_verified": False,
            "note": "Publisher/archival ISSN deposits and AEA-supplied index records establish journal identity. Individual publisher TOC checking is separate and incomplete. A blocked or absent page is not proof of a different journal. Unsupported discoveries are preserved in quarantine and excluded from paper, issue, author and institution indexes.",
        }


def display_date(value, precision):
    if not value:
        return "Unavailable"
    if precision in ["provider_day_unverified", "provider_date_unverified"]:
        return value[:4] + " (day and month unverified)"
    return value
