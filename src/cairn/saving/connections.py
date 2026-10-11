"""Owner-invoked client registration. Tests pass synthetic homes explicitly."""

import fcntl
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any, Literal

from cairn.errors import Conflict, Denied, RecoveryRequired
from cairn.records.models import Domain, canonical, digest
from cairn.saving.workspace import Book
from cairn.storage.files import RootFS

Client = Literal["claude", "codex"]


def connection(
    home: Path,
    client: Client,
    book: Book,
    collection: Domain,
    action: Literal["connect", "check", "repair", "disconnect"] = "connect",
) -> dict[str, Any]:
    book.collection(collection)
    fs = RootFS(home)
    token = digest(canonical([str(book.root), collection]))[:16]
    name = "cairn_" + token
    config = ".claude.json" if client == "claude" else ".codex/config.toml"
    receipt_path = f".cairn/connections/{client}_{token}.json"
    journal = ".cairn/connections/pending.json"
    desired = {
        "command": sys.executable,
        "args": ["-m", "cairn", "mcp", "--workspace", str(book.root), "--collection", collection],
    }
    if client == "claude":
        desired["type"] = "stdio"
    with fs.parent(".cairn/connect.lock", create=True) as (parent, leaf):
        fd = os.open(leaf, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    try:
        fs._regular(os.fstat(fd))
        fcntl.flock(fd, fcntl.LOCK_EX)
        if fs.exists(journal):
            if action != "repair":
                raise RecoveryRequired("connection interrupted; run connect --repair")
            pending = json.loads(fs.read(journal))
            if pending["client"] != client or pending["token"] != token:
                raise RecoveryRequired("repair the pending connection first")
            for entry in pending["entries"]:
                current = fs.read(entry["path"]).decode() if fs.exists(entry["path"]) else None
                if current not in (entry["before"], entry["after"]):
                    raise Conflict("client settings changed during interrupted registration")
            for entry in pending["entries"]:
                fs.write(entry["path"], entry["after"].encode())
            fs.remove(journal)
        before = fs.read(config).decode() if fs.exists(config) else None
        raw = before or ("{}\n" if client == "claude" else "")
        settings = json.loads(raw) if client == "claude" else tomllib.loads(raw)
        server_key = "mcpServers" if client == "claude" else "mcp_servers"
        servers = settings.get(server_key, {})
        if not isinstance(servers, dict):
            raise Denied("invalid client MCP settings")
        prior = json.loads(fs.read(receipt_path)) if fs.exists(receipt_path) else None
        active = prior is not None and prior["active"]
        existing = servers.get(name)
        healthy = bool(active and existing == desired)
        if action == "check":
            return {
                "name": name,
                "configured": healthy,
                "client_trial": "unverified",
                "workspace": str(book.root),
                "collection": collection,
            }
        if existing is not None and not active:
            raise Conflict("matching client entry is not owned by Cairn")
        if (
            prior is not None
            and active
            and existing not in (None, prior["entry"])
            and action != "repair"
        ):
            raise Conflict("Cairn entry was manually changed; use --repair explicitly")
        removing = action == "disconnect"
        if removing and not active:
            return {"name": name, "status": "disconnected", "client_trial": "unverified"}
        if healthy and not removing:
            return {"name": name, "status": "connected", "client_trial": "unverified"}
        if client == "claude":
            updated = dict(servers)
            if removing:
                updated.pop(name, None)
            else:
                updated[name] = desired
            settings[server_key] = updated
            after = json.dumps(settings, ensure_ascii=False, indent=2) + "\n"
        else:
            begin, end = f"# BEGIN Cairn {name}\n", f"# END Cairn {name}\n"
            if begin in raw or end in raw:
                if raw.count(begin) != 1 or raw.count(end) != 1:
                    raise Conflict("ambiguous Cairn settings markers")
                first, tail = raw.split(begin, 1)
                _, last = tail.split(end, 1)
                raw = first + last
            elif existing is not None:
                raise Conflict("owned TOML entry lost its markers; preserve and repair manually")
            after = raw
            if not removing:
                after += ("\n" if raw and not raw.endswith("\n") else "") + begin
                after += f"[mcp_servers.{name}]\ncommand = {json.dumps(desired['command'])}\n"
                after += "args = " + json.dumps(desired["args"], ensure_ascii=False) + "\n" + end
            tomllib.loads(after)
        receipt = canonical(
            {
                "active": not removing,
                "entry": desired,
                "config": config,
                "workspace": str(book.root),
                "collection": collection,
            }
        ).decode()
        old_receipt = fs.read(receipt_path).decode() if fs.exists(receipt_path) else None
        entries = [
            {"path": config, "before": before, "after": after},
            {"path": receipt_path, "before": old_receipt, "after": receipt},
        ]
        fs.write(
            journal,
            canonical({"client": client, "token": token, "entries": entries}),
            exclusive=True,
        )
        for entry in entries:
            assert entry["path"] is not None and entry["after"] is not None
            fs.write(entry["path"], entry["after"].encode())
        fs.remove(journal)
        return {
            "name": name,
            "status": "disconnected" if removing else "connected",
            "client_trial": "unverified",
        }
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
