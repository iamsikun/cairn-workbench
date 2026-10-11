"""Public direct-save schema registry, shared by export and parity checks."""

from cairn.saving.models import (
    Capture,
    KnowledgeRecord,
    SaveNote,
    SaveReading,
    SaveReceipt,
    SaveTransaction,
    WorkspaceConfigV4,
)

SCHEMAS = {
    "workspaceconfig-v4": WorkspaceConfigV4,
    "knowledgerecord-v2": KnowledgeRecord,
    "savenote-v1": SaveNote,
    "savereading-v1": SaveReading,
    "capture-v1": Capture,
    "savereceipt-v1": SaveReceipt,
    "savetransaction-v1": SaveTransaction,
}
