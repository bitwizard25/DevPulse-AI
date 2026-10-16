"""Provider failover policy is independent of HTTP implementations."""

import json
import time

from ..domain.cancellation import NeverCancelled
from ..domain.errors import ProviderError, ReviewCancelled
from ..domain.models import ProviderConfig
from ..domain.privacy import Vault
from ..domain.review import validate_result
from .ports import CancellationToken, CircuitStore, Clock, ModelTransport


class Router:
    def __init__(
        self,
        transport: ModelTransport,
        circuits: CircuitStore | None = None,
        clock: Clock | None = None,
    ):
        self.transport = transport
        self._circuits: dict[str, tuple[int, float]] = {}
        self.circuits = circuits
        self.clock = clock

    def _now(self):
        return self.clock.now() if self.clock else time.time()

    def _read(self, key):
        return self.circuits.read(key) if self.circuits else self._circuits.get(key, (0, 0))

    def _write(self, key, failures, until):
        if self.circuits:
            self.circuits.write(key, failures, until)
        else:
            self._circuits[key] = (failures, until)

    def review(
        self,
        providers: list[ProviderConfig],
        prompt: str,
        vault: Vault,
        *,
        chaos: bool = False,
        cancellation: CancellationToken | None = None,
    ) -> dict:
        attempts = []
        cancellation = cancellation or NeverCancelled()
        retryable, retry_after = False, 0
        for index, provider in enumerate(providers):
            if cancellation.cancelled():
                raise ReviewCancelled()
            circuit_key = json.dumps(provider.__dict__, sort_keys=True)
            failures, until = self._read(circuit_key)
            if self._now() < until:
                attempts.append({'provider': provider.name, 'status': 'circuit-open'})
                retryable, retry_after = True, max(retry_after, until - self._now())
                continue
            try:
                if chaos and index == 0:
                    raise ProviderError('Simulated HTTP 503.', retryable=True)
                response = validate_result(self.transport(provider, prompt))
            except ProviderError as exc:
                if exc.retryable:
                    failures += 1
                    self._write(circuit_key, failures, self._now() + 30 if failures >= 3 else 0)
                    retryable = True
                    retry_after = max(retry_after, exc.retry_after)
                attempts.append(
                    {'provider': provider.name, 'status': 'failed', 'error': vault.scrub(str(exc))}
                )
                continue
            if cancellation.cancelled():
                raise ReviewCancelled()
            self._write(circuit_key, 0, 0)
            attempts.append({'provider': provider.name, 'status': 'completed'})
            return {
                'response': vault.scrub_value(response),
                'provider': provider.name,
                'model': provider.model,
                'attempts': attempts,
            }
        detail = '; '.join(
            f'{item["provider"]}: {item.get("error", item["status"])}' for item in attempts
        )
        raise ProviderError(
            'All configured providers failed. ' + detail + ' Use --offline for local checks.',
            retryable=retryable,
            retry_after=retry_after,
        )
