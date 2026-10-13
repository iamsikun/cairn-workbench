"""Publication stage inferred conservatively from recorded bibliography and dates."""

LABELS = {
    "issue_assigned": "Assigned to a volume or issue",
    "online_first": "Online first · awaiting issue assignment",
    "unassigned": "Issue details unavailable",
}


def classify(record):
    if record.get("publication_unit") == "volume" and record.get("volume"):
        return (
            "issue_assigned",
            "The journal publishes by volume; a volume is recorded and no issue number is required.",
        )
    if record.get("volume") and record.get("issue"):
        return "issue_assigned", "Volume and issue are recorded in the source metadata."
    if record.get("published_online") and not record.get("published_print"):
        return (
            "online_first",
            "Inferred from a recorded online publication date with no print date and no complete volume/issue assignment. The publisher may have newer issue metadata.",
        )
    return (
        "unassigned",
        "Volume or issue metadata are incomplete; forthcoming status is not established.",
    )


def annotate(record):
    state, evidence = classify(record)
    record.update(publication_status=state, publication_status_evidence=evidence)
    return record


def where(stage="", alias="p"):
    # Only fixed, validated literals enter SQL; caller owns the table alias.
    if stage in ["", "all"]:
        return ""
    if stage == "pending":
        return f"{alias}.publication_status!='issue_assigned'"
    if stage not in LABELS:
        raise ValueError("Invalid publication stage")
    return f"{alias}.publication_status='{stage}'"
