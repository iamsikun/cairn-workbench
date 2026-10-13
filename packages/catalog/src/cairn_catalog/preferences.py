"""Edit the catalog preferences from the catalog pages (through `cairn-catalog serve`).

Changes arrive as small actions, are applied to the file as it is on disk, and the file is
rewritten with its explanatory comments. Unknown top-level keys are kept.
"""

import re
import shutil

import yaml

from . import discovery

TIERS = ("core", "skim", "mute")
KINDS = {"author": "people", "institution": "institutions"}
ID = re.compile(r"^[a-z][a-z-]*:[A-Za-z0-9._/:-]{1,200}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,120}$")


def dump(value):
    """One YAML value on one line (lists and maps in flow style)."""
    return (
        yaml.safe_dump(value, default_flow_style=True, allow_unicode=True, width=10_000)
        .strip()
        .removesuffix("\n...")
        .removesuffix("...")
        .strip()
    )


def block(entries):
    if not entries:
        return " []\n"
    lines = [""]
    for entry in entries:
        entry = {"name": entry} if isinstance(entry, str) else entry
        keys = [k for k in ["name", "label", "ids", "id"] if k in entry] + [
            k for k in entry if k not in ("name", "label", "ids", "id")
        ]
        for i, key in enumerate(keys):
            lines.append(("- " if i == 0 else "  ") + f"{key}: {dump(entry[key])}")
    return "\n".join(lines) + "\n"


def render(prefs):
    fields = prefs.get("fields") or {}
    journals = prefs.get("journals") or {}
    for_you = prefs.get("for_you") or {}
    keywords = for_you.get("keywords") or []
    out = [
        """# Personal settings for the saved journal catalog (catalog.html, authors.html, institutions.html).
# Edit them on the pages when the catalog is opened through the catalog app (cairn-catalog serve --open),
# or edit this file and run:  cairn-catalog personalize
# then reload the page. No catalog rebuild is needed. The weekly updater reruns it automatically.

# How much room each field gets on the front page.
#   core: full tile with headlines, counts toward "For you" at full weight
#   skim: compact tile; "For you" matches count half
#   mute: hidden from the front page and "For you" (still searchable)
fields:"""
        + ("\n" + "\n".join(f"  {k}: {dump(v)}" for k, v in fields.items()) if fields else " {}"),
        """
# Optional per-journal overrides, using journal ids from journals.json, e.g.
#   prl: mute
journals:"""
        + (
            "\n" + "\n".join(f"  {k}: {dump(v)}" for k, v in journals.items())
            if journals
            else " {}"
        ),
        """
for_you:
  # Phrases matched against titles and abstracts of the past 12 months.
  # Plain text is matched as a phrase, and a trailing plural is tolerated
  # ("large language model" also matches "models").
  # SQLite FTS5 syntax is passed through when you use quotes, *, AND, OR, NOT or NEAR.
  keywords:"""
        + ("\n" + "\n".join(f"  - {dump(str(k))}" for k in keywords) if keywords else " []")
        + f"""

  # Also use the titles and aliases of your Cairn topics (research/topics/*.md).
  cairn_topics: {dump(bool(for_you.get("cairn_topics", True)))}
  # Topic slugs to ignore.
  exclude_topics: {dump(list(for_you.get("exclude_topics") or []))}
  # Topics that have narrower topics under them (e.g. "Mathematics") are skipped unless listed here
  # or include_broad_topics is true.
  include_topics: {dump(list(for_you.get("include_topics") or []))}
  include_broad_topics: {dump(bool(for_you.get("include_broad_topics")))}""",
        """
# People to follow. Use a name, or an explicit id when a name matches several identities
# (the Authors page lists the candidates). Several ids can be listed for one person.
#   - name: Daron Acemoglu
#   - name: Ryan Kellogg
#     ids: [openalex:A5089706396]
people:"""
        + block(prefs.get("people") or []).rstrip("\n"),
        """
# Institutions to follow, by name or id (ror:… / openalex:…).
#   - name: Washington University in St. Louis
institutions:"""
        + block(prefs.get("institutions") or []).rstrip("\n"),
    ]
    known = {"fields", "journals", "for_you", "people", "institutions"}
    extra = {k: v for k, v in prefs.items() if k not in known}
    extra_for_you = {
        k: v
        for k, v in for_you.items()
        if k
        not in {
            "keywords",
            "cairn_topics",
            "exclude_topics",
            "include_topics",
            "include_broad_topics",
        }
    }
    if extra_for_you:
        out[2] += "\n" + "\n".join(f"  {k}: {dump(v)}" for k, v in extra_for_you.items())
    if extra:
        out.append(
            "\n# Other settings\n"
            + yaml.safe_dump(extra, allow_unicode=True, sort_keys=False).rstrip("\n")
        )
    return "\n".join(out) + "\n"


def text(value, name, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\n" in value:
        raise ValueError(f"Invalid {name}")
    return value.strip()


def entry_ids(entry):
    if isinstance(entry, str):
        return []
    return list(entry.get("ids") or ([entry["id"]] if entry.get("id") else []))


def entry_label(entry):
    if isinstance(entry, str):
        return entry
    return entry.get("label") or entry.get("name") or ", ".join(entry_ids(entry))


def apply(prefs, change, topics=None):
    """Apply one change from the page; returns the updated preferences. topics: slug -> {broader: [...]}."""
    topics = topics or {}
    if not isinstance(change, dict):
        raise ValueError("Invalid change")
    action = change.get("action")
    for_you = None
    if action in ("keyword_add", "keyword_remove", "topic", "cairn_topics"):
        for_you = prefs["for_you"] = prefs.get("for_you") or {}
    if action in ("follow", "unfollow", "choose"):
        if change.get("kind") not in KINDS:
            raise ValueError("Invalid kind")
        key = KINDS[change["kind"]]
        follows = prefs.get(key) or []
        prefs[key] = follows
        identity = change.get("id")
        if identity is not None and not (isinstance(identity, str) and ID.match(identity)):
            raise ValueError("Invalid identity id")
        if action == "follow":
            name = text(change.get("name"), "name")
            if identity and any(identity in entry_ids(e) for e in follows):
                return prefs
            if not identity and any(entry_label(e).casefold() == name.casefold() for e in follows):
                return prefs
            follows.append({"name": name, "ids": [identity]} if identity else {"name": name})
        elif action == "choose":
            label, identity = (
                text(change.get("label"), "label"),
                identity or text(None, "identity id"),
            )
            for i, entry in enumerate(follows):
                if entry_label(entry) == label:
                    entry = {"name": entry} if isinstance(entry, str) else entry
                    ids = entry_ids(entry)
                    entry.pop("id", None)
                    entry["ids"] = ids + [identity] if identity not in ids else ids
                    follows[i] = entry
                    break
            else:
                raise LookupError(f'"{label}" is not in the follow list')
        else:
            label = change.get("label")
            # A profile sends its catalog id and the follow's label; the file may list another id form (ORCID, ROR).
            if identity and any(identity in entry_ids(e) for e in follows):
                kept = []
                for entry in follows:
                    ids = entry_ids(entry)
                    if identity in ids:
                        if len(ids) == 1:
                            continue
                        entry = {k: v for k, v in entry.items() if k != "id"}
                        entry["ids"] = [i for i in ids if i != identity]
                    kept.append(entry)
                prefs[key] = kept
            else:
                label = text(label, "label")
                prefs[key] = [e for e in follows if entry_label(e) != label]
    elif action == "keyword_add":
        keyword = text(change.get("text"), "keyword")
        keywords = [str(k) for k in for_you.get("keywords") or []]
        if keyword.casefold() not in {k.casefold() for k in keywords}:
            keywords.append(keyword)
        for_you["keywords"] = keywords
    elif action == "keyword_remove":
        keyword = text(change.get("text"), "keyword")
        for_you["keywords"] = [k for k in for_you.get("keywords") or [] if str(k) != keyword]
    elif action == "topic":
        slug = change.get("slug")
        if not (isinstance(slug, str) and SLUG.match(slug) and slug in topics):
            raise ValueError("Unknown topic")
        exclude = [t for t in for_you.get("exclude_topics") or [] if t != slug]
        include = [t for t in for_you.get("include_topics") or [] if t != slug]
        if change.get("include") is True:
            # Only broad topics (those with narrower topics) need listing to be used.
            if any(slug in (t.get("broader") or []) for t in topics.values()):
                include.append(slug)
        elif change.get("include") is False:
            exclude.append(slug)
        else:
            raise ValueError("Invalid topic choice")
        for_you["exclude_topics"], for_you["include_topics"] = exclude, include
    elif action == "cairn_topics":
        if not isinstance(change.get("value"), bool):
            raise ValueError("Invalid choice")
        for_you["cairn_topics"] = change["value"]
    elif action == "tier":
        field, tier = change.get("field"), change.get("tier")
        if field not in {f["id"] for f in discovery.fields()} or tier not in TIERS:
            raise ValueError("Invalid field or tier")
        fields = prefs.get("fields") or {}
        fields[field] = tier
        prefs["fields"] = fields
    else:
        raise ValueError("Unknown change")
    return prefs


def save(path, prefs):
    """Write atomically; the previous version is kept beside it with a .bak suffix."""
    content = render(prefs)
    if yaml.safe_load(content) is None:
        raise ValueError("Could not write preferences")
    if path.exists():
        shutil.copyfile(path, path.with_name(path.name + ".bak"))
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)
