"""Training backend registry and provider catalog."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class TrainingBackendDefinition:
    """Describes a fine-tuning compute backend available to admins."""

    id: str
    name: str
    description: str
    status: str
    config_fields: tuple[str, ...] = ()
    supports_artifact_storage: bool = True

    def to_dict(self) -> dict:
        data = asdict(self)
        data["config_fields"] = list(self.config_fields)
        return data


_BACKENDS: dict[str, TrainingBackendDefinition] = {}


def register_training_backend(definition: TrainingBackendDefinition) -> None:
    backend_id = definition.id.strip().lower()
    if not backend_id:
        raise ValueError("Training backend id cannot be empty")
    if backend_id in _BACKENDS:
        raise ValueError(f"Training backend already registered: {backend_id!r}")
    if definition.status not in {"available", "configurable", "disabled"}:
        raise ValueError(f"Invalid training backend status: {definition.status!r}")
    _BACKENDS[backend_id] = definition


def list_training_backends() -> list[dict]:
    return [backend.to_dict() for backend in sorted(_BACKENDS.values(), key=lambda item: item.name)]


def get_training_backend(backend_id: str) -> TrainingBackendDefinition:
    normalized = backend_id.strip().lower()
    backend = _BACKENDS.get(normalized)
    if backend is None:
        raise ValueError(f"Unknown training backend: {backend_id!r}")
    return backend


def _register_builtin_backends() -> None:
    for definition in (
        TrainingBackendDefinition(
            id="local",
            name="Local GPU",
            description="Train on a local GPU worker when available.",
            status="available",
            config_fields=("device", "output_storage_uri"),
        ),
        TrainingBackendDefinition(
            id="custom",
            name="Custom Training Server",
            description="Submit jobs to an admin-managed HTTP or SSH training host.",
            status="configurable",
            config_fields=("endpoint_url", "auth_token", "ssh_host", "ssh_user", "ssh_key_ref", "output_storage_uri"),
        ),
        TrainingBackendDefinition(
            id="runpod",
            name="RunPod",
            description="Cloud GPU training through the RunPod API.",
            status="configurable",
            config_fields=("api_key", "gpu_type", "template_id", "network_volume_id", "output_storage_uri"),
        ),
        TrainingBackendDefinition(
            id="vast",
            name="Vast.ai",
            description="Marketplace GPU training through Vast.ai instances.",
            status="configurable",
            config_fields=("api_key", "offer_filters", "docker_image", "output_storage_uri"),
        ),
        TrainingBackendDefinition(
            id="lambda",
            name="Lambda Labs",
            description="Dedicated cloud GPU instances through Lambda Cloud.",
            status="configurable",
            config_fields=("api_key", "instance_type", "region", "ssh_key_ref", "output_storage_uri"),
        ),
        TrainingBackendDefinition(
            id="modal",
            name="Modal",
            description="Serverless GPU jobs through Modal.",
            status="configurable",
            config_fields=("token_id", "token_secret", "app_name", "gpu_type", "output_storage_uri"),
        ),
    ):
        register_training_backend(definition)


_register_builtin_backends()
