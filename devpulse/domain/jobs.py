"""Serializable job values; snapshots contain redacted data only."""

from dataclasses import asdict, dataclass, field

from .models import Config, ProviderConfig

TERMINAL_STATES = frozenset({'succeeded', 'failed', 'cancelled', 'expired'})


@dataclass(frozen=True)
class ReviewSnapshot:
    project: str
    digest: str
    config: Config
    prompt: str
    findings: list[dict]
    context: dict
    source: dict
    redacted_values: int
    mode: str
    has_source: bool
    no_cache: bool = False
    chaos: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict):
        value = dict(value)
        config = dict(value['config'])
        config['providers'] = [ProviderConfig(**item).validate() for item in config['providers']]
        value['config'] = Config(**config)
        return cls(**value)


@dataclass(frozen=True)
class Job:
    id: str
    project: str
    status: str
    attempts: int
    created: float
    updated: float
    expires: float
    available: float
    owner: str | None
    heartbeat: float | None
    cancel_requested: bool
    result: dict | None = None
    error: str | None = None
    snapshot: ReviewSnapshot | None = field(default=None, repr=False)

    def public(self, *, include_result=True) -> dict:
        fields = {key: value for key, value in asdict(self).items() if key != 'snapshot'}
        if not include_result:
            fields.pop('result', None)
        return fields
