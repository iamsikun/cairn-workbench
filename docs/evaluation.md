# Synthetic baseline evaluation

The retained [gold-set report](evidence/goldset.json) executes the public
[corpus](../examples/goldset/corpus.json) through Cairn's actual capture, extraction,
proposal, approval, apply, query, receipt, adoption, and context APIs. It uses temporary
synthetic workspaces in the network-disabled development container. It does not access a
private workspace or run a real model or second agent.

The first measured baseline passes **129/129 mechanical checks**. The eight query cases
all satisfy their exact-source rubric. All **36 checked citation occurrences** match
source hashes, extraction artifacts, locators, and any quoted text. These occurrences
include duplicate references in a record and its assertions; they are not 36 independent
claims or an entailment score.

| Case | Required observation | Observed result |
| --- | --- | --- |
| Exact source | Orchid latency is quoted as 42 milliseconds with its date and locator | Passed |
| Multiple sources | Both Orchid latency and throughput sources are returned | Passed retrieval; model synthesis not performed |
| Contradiction | Cedar's 8 and 13 percent estimates both remain visible with a dispute flag | Passed; dispute explicitly annotated in the fixture |
| Outdated rule | Fictional Maple 2024/2025 terms retain both dates, values, and revision lineage | Passed; no automatic applicability decision |
| Absent evidence | An unmatched question returns insufficient evidence | Passed |
| Two-character Chinese | `检索` finds Chinese text and the curated English alias | Passed |
| English/Chinese alias | `retrieval` also finds the Chinese source | Passed; no general translation claim |
| Source injection | Juniper's purported instructions remain quoted data and cannot change policy or adopt a decision | Passed in the defined fixture |
| Conversation roles | User and assistant roles remain ordered; receipt approval does not adopt the suggestion | Passed |
| Project continuity | An explicit adoption and failed approach are present with citations in a bounded pack | Passed mechanics; actual second-session usefulness pending |

The defined disclosure checks observed **zero violations**: adding a denied record did
not change authorized rankings/counts; denied titles, backlinks, query text, and context
were withheld. Write checks observed **zero violations**: each apply changed exactly the
approved canonical pages and preserved source/human bytes; query left durable files
unchanged. This corpus does not prove universal security. The separate installed-worker
and isolation trials exercise process/network boundaries and hostile subprocesses.

The workload produced **12 reviewed fixture proposals and 13 page changes**, with required
review flags and diff-line counts retained per proposal. Human edits and review duration
are `null`, because no human review study ran. Synthetic acknowledgements are not evidence
of actual owner acceptance. The report records three latency samples and a median for
each query, plus context and end-to-end time; these are observations on one reference
container, not performance guarantees. Model calls/tokens were zero and model cost was
**USD 0.00**; host computation cost is not included.

This establishes a reproducible usefulness baseline for preserving and finding specified
evidence. Future changes should retain all expected sources, dates, conflicts, and quote
locators, with zero observed disclosure/write violations in this corpus. Do not optimize
latency by weakening those checks. Semantic answer quality, generalization, real-client
cost, human review burden, and usefulness in a later agent session remain unmeasured.
The [manual continuity procedure](research-continuity.md#manual-separate-session-acceptance)
remains the owner-selected M2 semantic gate. The owner's real evaluation set stays private.

Run `python scripts/evaluate_goldset.py --output /tmp/goldset.json` inside the documented
development container. `scripts/check.sh` runs it against the installed development image
as part of acceptance. To retain a public report, use a container mounting only this
public checkout and select `docs/evidence/goldset.json` as output. The report binds the
corpus, evaluator, and source tree by SHA256 and records Python, SQLite, and platform.
Random durable IDs and timestamps are normalized to fixture aliases in the result; timing
samples naturally vary. Any failed mechanical check returns a nonzero exit status.
