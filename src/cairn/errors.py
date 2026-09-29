"""Stable, content-free error categories for CLI and adapters."""


class CairnError(Exception):
    code = "invalid"
    exit_status = 2


class Denied(CairnError):
    code = "denied"
    exit_status = 3


class Conflict(CairnError):
    code = "conflict"
    exit_status = 4


class Blocked(CairnError):
    code = "blocked"
    exit_status = 5


class RecoveryRequired(CairnError):
    code = "recovery_required"
    exit_status = 6
