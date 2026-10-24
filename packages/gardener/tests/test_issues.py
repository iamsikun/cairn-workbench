"""The weekly review's GitHub issue: opened per run, ticks copied back as approvals."""

from pathlib import Path

import yaml
from cairn_garden import ci, issues, reports
from cairn_garden import workflow as w
from test_regressions import g

ROOT = Path(__file__).resolve().parents[3]


def proposals(cfg, mode, folder, facts, model=None):
    return {
        "body": "## Connections\n"
        '- [ ] **C1** Link [[research-catalogs]] to B. <!-- action: {"op":"manual","description":"Link it"} -->\n'
        "\n## Topic organization\n"
        '- [ ] **T1** Split the topic. <!-- action: {"op":"manual","description":"Split it"} -->\n'
        "- **Manual:** not a checkbox.",
        "selected": [],
    }, {"agent": "claude", "model": "fixture"}


class FakeGitHub:
    repo = "owner/kb"

    def __init__(self):
        self.issues, self.comments = {}, []

    def open_issues(self):
        return [i for i in self.issues.values() if i["state"] == "open"]

    def create(self, title, body):
        number = len(self.issues) + 1
        self.issues[number] = {"number": number, "title": title, "body": body, "state": "open"}
        return self.issues[number]

    def comment(self, number, body):
        self.comments.append((number, body))

    def is_open(self, number):
        return self.issues[number]["state"] == "open"

    def close(self, number):
        self.issues[number]["state"] = "closed"


def tick(issue, text):
    lines = issue["body"].splitlines()
    index = next(i for i, line in enumerate(lines) if text in line)
    lines[index] = lines[index].replace("- [ ]", "- [x]", 1)
    issue["body"] = "\n".join(lines)


def weekly_report(cfg):
    weekly = reports.reports(cfg, "weekly")
    return weekly[max(weekly)].body


def test_weekly_run_opens_one_issue_listing_its_proposals(setup):
    w.run(setup, "weekly", renderer=proposals)
    github = FakeGitHub()
    result = issues.sync(setup, github)
    issue = github.issues[result["opened"]]
    assert issue["title"].endswith(": 2 proposals to approve")
    assert "### Connections" in issue["body"] and "### Topic organization" in issue["body"]
    assert (
        "https://github.com/owner/kb/blob/HEAD/research/topics/research-catalogs.md"
        in issue["body"]
    )
    assert "action:" not in issue["body"] and "Manual:" not in issue["body"]
    # Rerunning the step for the same run opens nothing new.
    assert issues.sync(setup, github)["opened"] == result["opened"]
    assert len(github.issues) == 1


def test_an_issue_github_does_not_list_yet_is_not_opened_twice(setup):
    w.run(setup, "weekly", renderer=proposals)
    github = FakeGitHub()
    first = issues.sync(setup, github)["opened"]
    listed = github.open_issues
    github.open_issues = lambda: []  # just created: the listing lags behind
    assert issues.sync(setup, github)["opened"] == first
    assert len(github.issues) == 1
    # A duplicate opened before this fix is closed in favour of the remembered issue.
    github.open_issues = listed
    duplicate = github.create("dup", github.issues[first]["body"])["number"]
    assert issues.sync(setup, github)["closed"] == [duplicate]
    github.open_issues = lambda: [dict(i, state="open") for i in github.issues.values()]
    assert issues.sync(setup, github)["closed"] == []  # a lagging listing: no second comment
    assert github.comments[-1] == (
        duplicate,
        f"Duplicate of #{first}. Approvals ticked here were copied to the report.",
    )


def test_a_ticked_box_approves_the_report_line_and_the_review_applies_it(setup):
    w.run(setup, "weekly", renderer=proposals)
    github = FakeGitHub()
    number = issues.sync(setup, github)["opened"]
    tick(github.issues[number], "**C1**")
    result = issues.sync(setup, github, open_new=False)
    assert len(result["approved"][number]) == 1
    body = weekly_report(setup)
    assert "- [x] **C1**" in body and "- [ ] **T1**" in body
    assert [line for line in g.approved_lines(body)] == [
        line for line in body.splitlines() if "**C1**" in line
    ]
    # Copying again changes nothing.
    assert issues.sync(setup, github, open_new=False)["approved"] == {}


def test_next_review_closes_the_old_issue_and_keeps_late_ticks(setup, monkeypatch):
    w.run(setup, "weekly", renderer=proposals)
    github = FakeGitHub()
    first = issues.sync(setup, github)["opened"]
    w.run(setup, "weekly", renderer=proposals)  # a rerun supersedes the open items
    tick(github.issues[first], "**T1**")  # ticked after the review began
    result = issues.sync(setup, github)
    assert result["opened"] != first and result["closed"] == [first]
    assert github.issues[first]["state"] == "closed"
    assert "Replaced by" in github.comments[0][1]
    # The superseded line is approved, as ticking it in the report would.
    approved = [line for line in g.approved_lines(weekly_report(setup)) if "**T1**" in line]
    assert len(approved) == 1 and issues.g.SUPERSEDED in approved[0]


def test_an_issue_cannot_add_a_proposal(setup):
    w.run(setup, "weekly", renderer=proposals)
    github = FakeGitHub()
    number = issues.sync(setup, github)["opened"]
    before = weekly_report(setup)
    issue = github.issues[number]
    issue["body"] += "\n- [x] **X9** Delete everything. <!-- cairn-item: 0123456789abcdef -->"
    assert issues.sync(setup, github, open_new=False)["approved"] == {}
    assert weekly_report(setup) == before


def test_no_issue_without_open_proposals(setup):
    w.run(setup, "daily", renderer=proposals)
    assert issues.sync(setup, FakeGitHub())["opened"] is None


def test_ci_issue_needs_a_repository_and_token(setup, monkeypatch):
    for name in ("GITHUB_REPOSITORY", "GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert ci.main(["issue", "--approvals-only"]) == 1
    assert ci.main(["issue", "--bogus"]) == 2


def test_workflow_and_template_grant_issue_access():
    spec = yaml.safe_load((ROOT / ".github/workflows/garden.yml").read_text())
    job = spec["jobs"]["garden"]
    assert job["permissions"] == {"contents": "write", "issues": "write"}
    steps = [s.get("name") for s in job["steps"]]
    assert (
        steps.index("Restore garden state")
        < steps.index("Copy approvals from the review issue")
        < steps.index("Daily digest")
    )
    assert steps.index("Publish reports and state") < steps.index("Open the review issue")
    assert yaml.safe_load(ci.template("v9.9.9"))["permissions"] == {
        "contents": "write",
        "issues": "write",
    }
