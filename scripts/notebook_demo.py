"""Synthetic scripted handoff fixture. This is not an actual agent/client trial."""

import argparse
import json
import tempfile
from pathlib import Path

from cairn.records.models import canonical
from cairn.saving.models import (
    NoteChange,
    Observation,
    Relationship,
    Resource,
    SaveNote,
    SaveReading,
    SourceInput,
)
from cairn.saving.retrieval import get_note
from cairn.saving.service import save, source_record, undo
from cairn.saving.views import render
from cairn.saving.workspace import Book


def demonstrate(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cairn-notebook-demo-") as temporary:
        book = Book.init(Path(temporary) / "knowledge", synthetic=True)
        save(
            book,
            "research",
            SaveNote(
                operation_key="architecture",
                note=NoteChange(
                    id="concept_decoders",
                    kind="topic",
                    title="Autoregressive decoders",
                    markdown=(
                        "A decoder predicts the next token conditional on a"
                        " prefix. This synthetic notebook leaves training "
                        "evidence unresolved."
                    ),
                ),
            ),
        )
        source_a = SourceInput(
            identity="doi:10.9999/synthetic-a",
            title="Synthetic paper A: token recommendation",
            version="v1",
            text="This synthetic method represents an item as a sequence of tokens.",
            coverage="excerpt",
        )
        first = save(
            book,
            "research",
            SaveReading(
                operation_key="reading-a",
                client="scripted-claude-adapter",
                paper=source_a,
                note=NoteChange(
                    title=source_a.title,
                    markdown=(
                        "The paper fixture represents each candidate item "
                        "using tokens. We have read one supplied excerpt, "
                        "not inspected experiments."
                    ),
                    observations=[
                        Observation(
                            id="observation_prefix",
                            text=(
                                "I want to understand how errors in early tokens "
                                "affect later choices."
                            ),
                        )
                    ],
                    relationships=[
                        Relationship(
                            target="concept_recommendation",
                            kind="broader_topic",
                            explanation="Item token prediction is used to make a recommendation.",
                        )
                    ],
                ),
                topics=[
                    NoteChange(
                        id="concept_recommendation",
                        kind="topic",
                        title="Generative recommendation",
                        markdown=(
                            "# Intuition\nRecommend an item by generating its "
                            "identifier, one token at a time.\n\n## Open question"
                            "\nHow does the identifier representation affect "
                            "errors?"
                        ),
                        unresolved=["Compare a second architecture"],
                        enrichment="pending",
                    )
                ],
            ),
        )
        topic = get_note(book, "research", "concept_recommendation")
        source_b = SourceInput(
            identity="doi:10.9999/synthetic-b",
            title="Synthetic paper B: shared decoder",
            version="v1",
            text="This synthetic model uses a shared autoregressive decoder for item tokens.",
            coverage="excerpt",
        )
        source_b_id = source_record(source_b, "research")[0].id
        explanation = """# Intuition
A recommender can generate an item's identifier instead of assigning every item a score.
The identifier is a short sequence; each prediction narrows the possible continuations.

## Prerequisites
Understand conditional probability, item representations and autoregressive decoding.

## Mechanism and notation
For an identifier t₁…tₖ and user context u:

p(t₁…tₖ | u) = ∏ⱼ p(tⱼ | u, t₁…tⱼ₋₁).

This factorization describes the prediction task. It does not establish accuracy or efficiency.

## Comparison
Paper A's supplied excerpt describes item tokenization. Paper B's excerpt describes a shared
decoder. Their architectural connection is inferred from these fixture descriptions; no
benchmark result, architectural equivalence or causal advantage has been established.

## Worked example
An illustrative identifier [category, item] first chooses a category, then an item within it.
An incorrect first token may remove the intended item from later candidates.

## Limits and open questions
Both readings cover supplied excerpts only. Inspect the full methods and experiments before
claiming how training, retrieval constraints or errors behave in either paper.
"""
        second = save(
            book,
            "research",
            SaveReading(
                operation_key="reading-b",
                client="scripted-codex-adapter",
                paper=source_b,
                note=NoteChange(
                    title=source_b.title,
                    markdown=(
                        "The supplied fixture describes a shared "
                        "autoregressive decoder. Its training and empirical"
                        " behavior remain unknown."
                    ),
                    relationships=[
                        Relationship(
                            target="concept_recommendation",
                            kind="broader_topic",
                            explanation=(
                                "The decoder generates item identifiers for recommendation."
                            ),
                        ),
                        Relationship(
                            target="concept_decoders",
                            kind="uses",
                            explanation=(
                                "The fixture states that its prediction mechanism "
                                "is autoregressive."
                            ),
                        ),
                    ],
                ),
                topics=[
                    NoteChange(
                        id="concept_recommendation",
                        expected_revision=topic["revision"],
                        kind="topic",
                        title="Generative recommendation",
                        markdown=explanation,
                        relationships=[
                            Relationship(
                                target="concept_decoders",
                                kind="uses",
                                explanation=(
                                    "Generating an item identifier reuses the prefix-"
                                    "conditioned prediction mechanism."
                                ),
                            )
                        ],
                        citations=[
                            {"id": source_b_id, "locator": "line 1", "quote": source_b.text}
                        ],
                        resources=[
                            Resource(
                                key="flow",
                                kind="diagram",
                                title="A synthetic prediction path",
                                content=json.dumps(
                                    [
                                        "User context",
                                        "Decoder + prefix",
                                        "Next identifier token",
                                        "Candidate item",
                                    ]
                                ),
                                description=(
                                    "A conceptual flow for the fixture; not a verified "
                                    "implementation diagram."
                                ),
                            ),
                            Resource(
                                key="comparison",
                                kind="table",
                                title="What the excerpts support",
                                content=(
                                    "| Fixture | Supported description | Still unknown "
                                    "|\n|---|---|---|\n| A | Item tokens | Training and "
                                    "evidence |\n| B | Shared decoder | Training and "
                                    "evidence |"
                                ),
                                description=(
                                    "Claims are limited to the supplied synthetic excerpts."
                                ),
                            ),
                        ],
                        unresolved=["Read full methods and inspect evidence"],
                        enrichment="pending",
                    )
                ],
            ),
        )
        view = render(book, "research", "concept_recommendation")
        snapshot = render(book, "research", "concept_recommendation", snapshot=True)
        before = Path(snapshot["path"]).read_bytes()
        current = get_note(book, "research", "concept_recommendation")
        changed = save(
            book,
            "research",
            SaveNote(
                operation_key="refine",
                note=NoteChange(
                    id=current["id"],
                    expected_revision=current["revision"],
                    title=current["title"],
                    markdown=current["markdown"]
                    + (
                        "\nA useful next check is to trace one decoding "
                        "error through the candidate constraints.\n"
                    ),
                ),
            ),
        )
        unrelated = save(
            book,
            "research",
            SaveNote(
                operation_key="unrelated",
                note=NoteChange(
                    title="Independent research question",
                    kind="question",
                    markdown="Which evaluation isolates representation quality?",
                ),
            ),
        )
        undo(book, "research", changed["id"], "undo-refinement")
        assert get_note(book, "research", unrelated["notes"][0]["id"])
        assert Path(snapshot["path"]).read_bytes() == before
        current_view = render(book, "research", "concept_recommendation")
        (output / "notebook.html").write_bytes(Path(current_view["path"]).read_bytes())
        scenario = save(
            book,
            "finance",
            SaveNote(
                operation_key="scenario",
                note=NoteChange(
                    title="Illustrative compounding",
                    kind="topic",
                    markdown=(
                        "This deterministic teaching example uses annual "
                        "compounding and year-end contributions. It is not "
                        "a return forecast."
                    ),
                    resources=[
                        Resource(
                            key="growth",
                            kind="scenario",
                            title="Change the assumptions",
                            description=(
                                "Amounts are USD. Initial amount 100, contribution "
                                "10, annual rate 10%, two years."
                            ),
                            content=json.dumps(
                                {
                                    "initial": "100",
                                    "annual_contribution": "10",
                                    "annual_rate": "0.1",
                                    "years": 2,
                                    "unit": "USD",
                                }
                            ),
                        )
                    ],
                ),
            ),
        )
        scenario_view = render(book, "finance", scenario["notes"][0]["id"])
        (output / "scenario.html").write_bytes(Path(scenario_view["path"]).read_bytes())
        (output / "evidence.json").write_bytes(
            canonical(
                {
                    "fixture": "scripted adapters; no actual clients or model",
                    "reading_a": first["id"],
                    "reading_b": second["id"],
                    "view_refreshed": view["html_hash"] != current_view["html_hash"],
                    "snapshot_preserved": True,
                    "undo_preserved_unrelated": True,
                    "actual_claude_codex_trials": "unverified",
                    "finch_quill_semantic_trial": "unverified",
                }
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    demonstrate(parser.parse_args().output)
