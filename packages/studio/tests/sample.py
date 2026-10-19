"""A small synthetic knowledge base, written through the core as an agent would."""

from __future__ import annotations

from pathlib import Path

from cairn.store import KB, init

TOPICS = [
    ("Recommendation systems", "Predicting what a user wants next.", []),
    (
        "Generative recommendation",
        "Recommenders that generate item identifiers.",
        ["Recommendation systems"],
    ),
    ("Large recommendation models", "Scaling laws for recommenders.", ["Recommendation systems"]),
    ("Causal inference", "Effects of interventions from data.", []),
    (
        "Uplift modeling",
        "Who responds to a treatment.",
        ["Causal inference", "Recommendation systems"],
    ),
]
PAPERS = [
    (
        "TIGER: Recommender Systems with Generative Retrieval",
        "arxiv:2305.05065",
        ["Generative recommendation"],
        "## Main idea\n\nItems get **semantic IDs**; a seq2seq model generates them.\n\n"
        "**User:** the cold-start result is the interesting part.",
    ),
    (
        "Actions Speak Louder than Words: HSTU",
        "arxiv:2402.17152",
        ["Large recommendation models", "Generative recommendation"],
        "## Main idea\n\nA sequential transducer that scales like a language model. "
        "Compare [[tiger-recommender-systems-with-generative-retrieval]].",
    ),
    (
        "Meta-learners for heterogeneous treatment effects",
        "doi:10.1073/pnas.1804597116",
        ["Uplift modeling"],
        "## Main idea\n\nT-, S- and X-learners; the X-learner helps with unbalanced groups.",
    ),
]


def build(root: Path) -> KB:
    kb = KB(init(root))
    for title, body, broader in TOPICS:
        kb.save(kind="topic", title=title, body=body, topics=broader)
    for title, source, topics, body in PAPERS:
        kb.save(
            kind="paper",
            title=title,
            body=body,
            topics=topics,
            fields={"source": source, "year": 2023},
        )
    first = kb.save(
        kind="idea",
        title="Semantic IDs for cold-start ads",
        body="**Question:** do semantic IDs help cold-start ads? "
        "Builds on [[tiger-recommender-systems-with-generative-retrieval]].",
        topics=["Generative recommendation"],
        fields={"next_action": "Find an ads dataset with cold-start items"},
        minute="**User:** cold-start ads might benefit most.\n"
        "**Agent (suggestion):** start with a public dataset.",
    )
    kb.save(
        kind="idea",
        title="Semantic IDs for cold-start ads",
        slug=first["slug"],
        revision=kb.get(first["slug"])["revision"],
        body="**Question:** do semantic IDs help cold-start ads?",
        fields={"status": "exploring"},
        minute="**User:** worth a pilot.\n\n**Source:** [[actions-speak-louder-than-words-hstu]] "
        "scales well.",
    )
    kb.save(
        kind="idea",
        title="Uplift-aware ranking",
        body="Rank by predicted uplift instead of click probability.",
        topics=["Uplift modeling"],
    )
    kb.save(kind="note", title="Reading list", body="Next: [[uplift-modeling]].")
    return kb
