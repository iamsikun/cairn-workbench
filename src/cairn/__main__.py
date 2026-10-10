from cairn.updater.launch import prelaunch

prelaunch()

from cairn.cli import app  # noqa: E402 - a bound runtime may re-execute first

app()
