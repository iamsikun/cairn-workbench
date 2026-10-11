from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from cairn.records.models import Digest, Model
from cairn.storage.files import components


class WheelArtifact(Model):
    name: Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
    version: Annotated[str, Field(pattern=r"^[0-9][a-zA-Z0-9.+_-]*$")]
    filename: str
    sha256: Digest
    installed_files: dict[str, Digest] = Field(min_length=1)

    @field_validator("filename")
    @classmethod
    def wheel_basename(cls, value: str) -> str:
        if len(components(value)) != 1 or not value.endswith(".whl"):
            raise ValueError("wheel requires a basename")
        return value

    @field_validator("installed_files")
    @classmethod
    def safe_paths(cls, value: dict[str, str]) -> dict[str, str]:
        for path in value:
            components(path)
            if ".data" in path.split("/")[0] or path.endswith("/RECORD"):
                raise ValueError("unsupported relocated or generated wheel file")
        return value


class _ReleaseFields(Model):
    product: Literal["cairn-workbench"] = "cairn-workbench"
    code_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    source_hash: Digest
    lock_hash: Digest
    python_version: str
    python_implementation: str
    python_executable_hash: Digest
    platform: str
    artifacts: list[WheelArtifact] = Field(min_length=1)
    bootstrap_files: dict[str, Digest]
    adapters: dict[str, str]

    @model_validator(mode="after")
    def unique_artifacts(self) -> Self:
        if len({a.name for a in self.artifacts}) != len(self.artifacts):
            raise ValueError("duplicate release package")
        if len({a.filename for a in self.artifacts}) != len(self.artifacts):
            raise ValueError("duplicate wheel filename")
        if sum(a.name == self.product for a in self.artifacts) != 1:
            raise ValueError("release omits Cairn wheel")
        names = set(self.bootstrap_files)
        for path in names:
            components(path)
            if len(components(path)) != 1:
                raise ValueError("bootstrap files must be at site-packages root")
        for artifact in self.artifacts:
            if names.intersection(artifact.installed_files):
                raise ValueError("release files overlap")
            names.update(artifact.installed_files)
        return self


class ReleaseManifest(_ReleaseFields):
    """Version 1 remains strict for historical runtime approvals."""

    schema_version: Literal[1] = 1
    worker_image: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class NativeReleaseManifest(_ReleaseFields):
    """Native package inventory; never grants legacy runtime authorization."""

    schema_version: Literal[2] = 2


type PackageManifest = ReleaseManifest | NativeReleaseManifest
