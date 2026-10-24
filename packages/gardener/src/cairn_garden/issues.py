"""A GitHub issue for each weekly review, so its proposals reach the owner (GitHub Actions).

Nothing else tells the owner that a weekly checklist is waiting: a report pushed by the
workflow and a successful scheduled run send no notification. `sync` opens one issue for the
latest weekly run that leaves proposals open, listing them as checkboxes, and closes the
issues of earlier runs. Ticking a box approves the item: every run first copies ticks from the
open issues into the weekly report, exactly as if the owner had ticked it there, and the weekly
review applies them. Unticking a box withdraws nothing; edit the report for that.

An issue item names its report line by a hash of the line's text, so an issue can only approve
a line the report already holds, never add one.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request

from . import engine as g
from . import reports

RUN = re.compile(r"<!-- cairn-garden-weekly: (\S+) (\S+) -->")
ITEM = re.compile(r"^\s*- \[([ xX])\] .*<!-- cairn-item: ([0-9a-f]{16}) -->\s*$")
BOX = re.compile(r"^\s*- \[[ xX-]\] ")
LIMIT = 60000  # GitHub refuses an issue body over 65,536 characters.


class GitHub:
    """The few REST calls the issue needs, with the workflow's token."""

    def __init__(self, repo=None, token=None, api=None):
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY")
        self.token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self.api = api or os.environ.get("GITHUB_API_URL", "https://api.github.com")
        if not self.repo or not self.token:
            raise RuntimeError("needs GITHUB_REPOSITORY and GITHUB_TOKEN")

    def call(self, method, path, body=None):
        request = urllib.request.Request(
            f"{self.api}/repos/{self.repo}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read() or "null")

    def open_issues(self):
        found, page = [], 1
        while True:
            batch = self.call("GET", f"/issues?state=open&per_page=100&page={page}")
            found += [i for i in batch if "pull_request" not in i]
            if len(batch) < 100:
                return found
            page += 1

    def create(self, title, body):
        return self.call("POST", "/issues", {"title": title, "body": body})

    def comment(self, number, body):
        self.call("POST", f"/issues/{number}/comments", {"body": body})

    def is_open(self, number):
        return self.call("GET", f"/issues/{number}")["state"] == "open"

    def close(self, number):
        self.call("PATCH", f"/issues/{number}", {"state": "closed", "state_reason": "completed"})


def key(line: str) -> str:
    """A report line's identity, the same whether it is open or marked superseded."""
    text = BOX.sub("", line, count=1)
    text = re.sub(r" _\(" + g.SUPERSEDED + r" [^)]*\)_", "", text)
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()[:16]


def run_id(body: str) -> str | None:
    markers = g.RUN_MARKER.findall(body)
    return markers[-1].removeprefix("<!-- gardener-run:").removesuffix(" -->") if markers else None


def run_lines(body: str, run: str) -> tuple[int, int]:
    """The line range of one run's section: after the previous run marker, up to its own."""
    lines = body.splitlines()
    ends = [i for i, line in enumerate(lines) if g.RUN_MARKER.search(line)]
    own = [i for i in ends if f"gardener-run:{run} " in lines[i]]
    if not own:
        return 0, 0
    return max((i + 1 for i in ends if i < own[0]), default=0), own[0] + 1


def latest(cfg):
    """The newest weekly report's id, its latest run, and that run's checklist section."""
    weekly = reports.reports(cfg, "weekly")
    if not weekly:
        return None, None, ""
    rid = max(weekly, key=lambda r: (weekly[r].meta.get("period", ""), r))
    return rid, run_id(weekly[rid].body), g.latest_run(weekly[rid].body)


def items(section: str) -> list[tuple[str | None, str]]:
    """The section's open proposals, each with the heading it sits under."""
    heading, found = None, []
    open_lines = dict(g.open_items(section))
    for number, line in enumerate(section.splitlines()):
        if line.startswith("## "):
            heading = line[3:].strip()
        elif number in open_lines:
            found.append((heading, line))
    return found


def web_links(cfg, rid: str, text: str, server: str, repo: str) -> str:
    """Relative note links resolve against the report file; on GitHub they need full URLs."""
    workspace = g.workspace(cfg).resolve()
    base = reports.path_of(cfg, rid).parent

    def absolute(match):
        target = match.group(2).strip("<>")
        if re.match(r"^[a-z][a-z0-9+.-]*:|^#", target):
            return match.group(0)
        path = (base / target.split("#")[0]).resolve()
        if not path.is_relative_to(workspace):
            return match.group(1)
        return f"[{match.group(1)}]({server}/{repo}/blob/HEAD/{path.relative_to(workspace).as_posix()})"

    return g.MD_LINK.sub(absolute, text)


def body(cfg, rid, run, proposals, server, repo) -> str:
    report = reports.path_of(cfg, rid).relative_to(g.workspace(cfg).resolve()).as_posix()
    count = len(proposals)
    lines = [
        f"The weekly garden review [{report}]({server}/{repo}/blob/HEAD/{report}) "
        f"has {count} proposal{'s' * (count != 1)} waiting for you.",
        "",
        "Tick an item to approve it. The next garden run copies your ticks into the report, and "
        "the weekly review applies them. Unticking here withdraws nothing; edit the report for "
        "that. This issue closes when the next weekly review replaces it.",
    ]
    section = False
    for shown, (heading, line) in enumerate(proposals):
        entry = web_links(cfg, rid, line.split("<!--")[0].rstrip(), server, repo)
        extra = [] if heading == section else ["", f"### {heading or 'Proposals'}"]
        extra.append(
            BOX.sub("- [ ] ", entry.lstrip(), count=1) + f" <!-- cairn-item: {key(line)} -->"
        )
        if sum(len(x) + 1 for x in lines + extra) > LIMIT:
            lines += ["", f"_{count - shown} more in the report._"]
            break
        lines += extra
        section = heading
    lines += ["", f"<!-- cairn-garden-weekly: {rid} {run} -->"]
    return "\n".join(lines) + "\n"


def approve(cfg, issue_body: str) -> list[str]:
    """Tick, in the issue's report, the open or superseded lines whose boxes are ticked."""
    marker = RUN.search(issue_body or "")
    if not marker:
        return []
    rid = marker.group(1)
    ticked = {
        m.group(2) for m in map(ITEM.match, issue_body.splitlines()) if m and m.group(1) != " "
    }
    note = reports.get(cfg, rid) if ticked else None
    if note is None:
        return []
    # Only the issue's own run: a rerun may restate an item word for word.
    first, last = run_lines(note.body, marker.group(2))
    lines, approved = note.body.splitlines(), []
    for number, line in enumerate(lines):
        if not first <= number < last:
            continue
        if re.match(r"^\s*- \[[ -]\] ", line) and key(line) in ticked:
            lines[number] = re.sub(r"\[[ -]\]", "[x]", line, count=1)
            approved.append(line.strip()[:120])
    if approved:
        tail = "\n" if note.body.endswith("\n") else ""
        reports.save(cfg, rid, "\n".join(lines) + tail, {}, revision=note.revision)
    return approved


def sync(cfg, github: GitHub, open_new: bool = True) -> dict:
    """Copy approvals from open review issues; then open the latest run's issue, closing older ones."""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    ours = [i for i in github.open_issues() if RUN.search(i.get("body") or "")]
    approved = {}
    for issue in ours:
        done = approve(cfg, issue["body"])
        if done:
            approved[issue["number"]] = done
    result = {"approved": approved, "opened": None, "closed": []}
    if not open_new:
        return result
    rid, run, section = latest(cfg)
    proposals = items(section)
    # GitHub lists a new issue only after a moment, so the state remembers the one opened.
    state = g.load_state(cfg)
    known = state.get("review_issue") or {}
    current = sorted(i["number"] for i in ours if RUN.search(i["body"]).groups() == (rid, run))
    if rid and (known.get("report"), known.get("run")) == (rid, run):
        result["opened"] = known["number"]
    elif current:
        result["opened"] = current[0]
    elif rid and run and proposals:
        period = reports.get(cfg, rid).meta.get("period", rid)
        count = len(proposals)
        title = f"Garden review {period}: {count} proposal{'s' * (count != 1)} to approve"
        created = github.create(title, body(cfg, rid, run, proposals, server, github.repo))
        result["opened"] = created["number"]
    if result["opened"] and known.get("number") != result["opened"]:
        state["review_issue"] = {"report": rid, "run": run, "number": result["opened"]}
        g.save_state(cfg, state)
    for issue in ours:
        if issue["number"] == result["opened"] or not github.is_open(issue["number"]):
            continue  # the listing can lag a close, too
        if issue["number"] in current:
            note = f"Duplicate of #{result['opened']}."
        elif result["opened"]:
            note = f"Replaced by #{result['opened']}."
        else:
            note = "No proposals are open."
        github.comment(issue["number"], note + " Approvals ticked here were copied to the report.")
        github.close(issue["number"])
        result["closed"].append(issue["number"])
    return result


def main(argv: list[str]) -> int:
    approvals_only = argv == ["--approvals-only"]
    if argv and not approvals_only:
        print("usage: cairn-garden ci issue [--approvals-only]")
        return 2
    try:
        result = sync(g.config(), GitHub(), open_new=not approvals_only)
    except Exception as error:
        g.out({"error": type(error).__name__, "message": str(error)})
        return 1
    g.out(result)
    return 0
