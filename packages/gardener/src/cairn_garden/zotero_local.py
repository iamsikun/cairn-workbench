"""Authenticated, loopback-only access to the narrow Zotero 9 write extension."""

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

BRIDGE = Path(__file__).resolve().parent / "bridge"


def bridge_hash():
    digest = hashlib.sha256()
    for path in sorted(BRIDGE.glob("*")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def package(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(BRIDGE.glob("*")):
            data = source.read_bytes().replace(b"__BRIDGE_BUILD__", bridge_hash().encode())
            archive.writestr(source.name, data)
    return str(path)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError("Local Zotero redirects are forbidden")


class LocalWriter:
    def __init__(self, cfg, config_dir, local_api):
        parsed = urllib.parse.urlsplit(local_api)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Local Zotero must use a loopback HTTP address")
        if parsed.path.rstrip("/") not in (
            "/api/users/0",
            "/api/users/" + str(cfg.get("zotero_user_id")),
        ):
            raise ValueError("Local Zotero must target the configured personal library")
        path = Path(config_dir) / "zotero-local.json"
        if path.stat().st_mode & 0o077:
            raise ValueError("Local Zotero credential file must have mode 600")
        self.credentials = json.loads(path.read_text())
        if self.credentials.get("user_id") != cfg.get("zotero_user_id") or not re.fullmatch(
            "[a-f0-9]{64}", self.credentials.get("token", "")
        ):
            raise ValueError("Local Zotero credential account mismatch or invalid token")
        self.url = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, "/kb-gardener/v1", "", "")
        )
        self.status = self.request("status")
        if (
            self.status.get("protocol") != 1
            or self.status.get("build") != bridge_hash()
            or self.status.get("user_id") != cfg.get("zotero_user_id")
            or not {"create", "add"} <= set(self.status.get("capabilities", []))
        ):
            raise ValueError(
                "Local Zotero bridge is outdated or incompatible; install the matching extension"
            )

    def request(self, operation, **payload):
        data = json.dumps(
            {**payload, "op": operation, "user_id": self.credentials["user_id"]}
        ).encode()
        request = urllib.request.Request(
            self.url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "cairn-kb-gardener",
                "Authorization": "Bearer " + self.credentials["token"],
            },
            method="POST",
        )
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(
                request, timeout=90
            ) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:600]
            raise RuntimeError(f"Local Zotero HTTP {error.code}: {detail}") from None
        if not isinstance(result, dict) or result.get("error"):
            raise RuntimeError("Local Zotero returned an invalid result")
        return result

    def verify(self, result, targets, get, identity=None, ids=None):
        key = result.get("key")
        if not isinstance(key, str) or not re.fullmatch(
            "[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}", key
        ):
            raise RuntimeError("Local Zotero response has no valid item key")
        live = get("items/" + key)["data"]
        required = set(targets) | set(result.get("before_collections", []))
        if live.get("deleted") or not required <= set(live.get("collections", [])):
            raise RuntimeError("Local Zotero collection read-back failed")
        if identity and identity not in ids(live):
            raise RuntimeError("Local Zotero identity read-back failed")
        for field in ("itemType", "title", "DOI", "url", "creators"):
            if live.get(field) != result.get("data", {}).get(field):
                raise RuntimeError("Local Zotero metadata read-back failed: " + field)
        return {**result, "verified": True, "collections": live.get("collections", [])}


def prepare(output, credentials=False):
    """Build the reviewed local extension and provision its private local credential file."""
    import os
    import secrets

    from . import engine as g

    cfg = g.config()
    result = {"package": package(output), "build": bridge_hash(), "installed": False}
    if credentials:
        if not isinstance(cfg.get("zotero_user_id"), int):
            raise ValueError(
                "Set zotero_user_id to the intended personal library account before provisioning"
            )
        path = g.BRIDGE_CREDENTIALS
        if path.exists():
            existing = json.loads(path.read_text())
            if existing.get("user_id") != cfg["zotero_user_id"]:
                raise ValueError("Existing bridge credentials belong to another account")
            path.chmod(0o600)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump(
                    {"user_id": cfg["zotero_user_id"], "token": secrets.token_hex(32)}, handle
                )
                handle.flush()
                os.fsync(handle.fileno())
        result["credentials_ready"] = True
    return result
