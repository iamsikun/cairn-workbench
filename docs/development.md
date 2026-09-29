# Synthetic development

Build the development image using `docker build --target development -t cairn-dev:local .`.
The build context is allowlisted in `.dockerignore`; dependency acquisition occurs before
any data processing. The base and Python dependencies are pinned by digest and `uv.lock`.

Run tests with the processing profile:

```sh
docker run --rm --pull=never --network=none --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges --pids-limit=64 --memory=512m --cpus=1 \
  --log-driver=none --no-healthcheck --restart=no \
  --user=65532:65532 --tmpfs=/tmp:rw,noexec,nosuid,size=128m,mode=1777 \
  cairn-dev:local
```

Use the same profile for `ruff check src tests scripts` and `mypy`. Development containers
contain only public files and create synthetic workspaces in container-local temporary
storage. Never mount a host home, private workspace, credentials, or the Docker socket.
For editing/formatting, an explicit mount of only the public checkout is acceptable.

`scripts/export_schemas.py` generates schemas from the typed models. The schema parity
test detects drift. Run it with only the public checkout writable.

Run `scripts/isolation_probe.py` inside this profile with the absolute path of a synthetic
host canary that is deliberately not mounted. It attempts canonical/policy/approval
writes, network and DNS access, and launches a hostile subprocess. A skipped or failed
probe is a failed isolation gate. Delete the synthetic canary using ordinary owner
maintenance when no longer needed; never use real private data as a canary.

The host Docker launcher is trusted. A client that can control that launcher or the Docker
daemon is outside the worker boundary. The application never mounts its daemon socket
inside a worker. This boundary does not defend against a compromised host/engine.
