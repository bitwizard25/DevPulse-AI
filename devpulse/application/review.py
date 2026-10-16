"""Prepare immutable redacted inputs, then execute them through injected adapters."""

import copy
import json
import re
import threading
import time
from pathlib import Path

from ..domain.cancellation import NeverCancelled
from ..domain.checks import check_python, finding
from ..domain.errors import ReviewCancelled
from ..domain.jobs import ReviewSnapshot
from ..domain.models import Config
from ..domain.privacy import Vault
from ..domain.review import bound_result
from .context import ContextPlanner
from .ports import CancellationToken, ContextReader, CredentialReader, SourceReader, StateStore
from .router import Router

PROMPT_VERSION = 'review-v3'


class Engine:
    def __init__(
        self,
        state: StateStore,
        source_reader: SourceReader,
        context_reader: ContextReader,
        router: Router,
        credentials: CredentialReader,
        planner: ContextPlanner,
    ):
        self.state = state
        self.source_reader = source_reader
        self.context_reader = context_reader
        self.router = router
        self.credentials = credentials
        self.planner = planner
        self._queue = threading.Lock()

    def prepare(
        self,
        root: Path,
        config: Config,
        *,
        mode: str = 'ai',
        file: str | None = None,
        worktree: bool = False,
        no_cache: bool = False,
        chaos: bool = False,
    ) -> ReviewSnapshot:
        if mode not in ('ai', 'offline'):
            raise ValueError('Review mode must be ai or offline.')
        source = self.source_reader(root, file=file, worktree=worktree)
        vault = Vault()
        credentials = self.credentials(config)
        for value in credentials:
            vault.protect(value)
        redacted_source = vault.scrub(source['text'])
        context = self.context_reader(
            root, vault, budget=config.context_bytes, query=redacted_source
        )
        # Indexing can discover values also repeated in source without a credential label.
        redacted_source = vault.scrub(redacted_source)
        context = vault.scrub_value(context)
        identity = {
            'schema': PROMPT_VERSION,
            'project': str(root),
            'source': source,
            'context': context,
            'config': config.as_dict(),
            'mode': mode,
            'chaos': chaos,
            'credentials': [self.state.identity(value) for value in credentials],
        }
        digest = self.state.identity(json.dumps(identity, sort_keys=True))
        planned = self.planner.plan(
            context,
            redacted_source,
            source['kind'],
            config.providers,
            byte_budget=config.context_bytes,
            enforce=mode == 'ai',
        )
        redacted_count = max(
            vault.count, len(set(re.findall(r'__SECRET_(?:INDEX_)?\d+__', planned['prompt'])))
        )
        findings = check_python(source['files'])
        if redacted_count:
            findings.append(
                finding(
                    'secret-detected',
                    'warning',
                    '',
                    1,
                    f'{redacted_count} potential secret value(s) redacted from source/context before inference.',
                )
            )
        changed = sum(
            line.startswith(('+', '-')) and not line.startswith(('+++', '---'))
            for line in source['text'].splitlines()
        )
        if changed > 500 and source['kind'] not in ('file', 'project'):
            findings.append(
                finding(
                    'large-change',
                    'info',
                    '',
                    1,
                    'More than 500 changed lines; split this change into focused reviews.',
                )
            )
        # No raw code, project absolute path or vault mapping crosses this boundary.
        return ReviewSnapshot(
            project=self.state.identity(str(root)),
            digest=digest,
            config=copy.deepcopy(config),
            prompt=planned['prompt'],
            findings=vault.scrub_value(findings),
            context=vault.scrub_value(planned['context']),
            source=vault.scrub_value(
                {'kind': source['kind'], 'python_files_checked': len(source['files'])}
            ),
            redacted_values=redacted_count,
            mode=mode,
            has_source=bool(source['text'].strip()),
            no_cache=no_cache,
            chaos=chaos,
        )

    def review(self, root: Path, config: Config, **options) -> dict:
        return self.execute(self.prepare(root, config, **options))

    def execute(
        self, snapshot: ReviewSnapshot, cancellation: CancellationToken | None = None
    ) -> dict:
        cancellation = cancellation or NeverCancelled()
        started = time.monotonic()
        with self._queue:
            if cancellation.cancelled():
                raise ReviewCancelled()
            session = self.state.start(snapshot.project, snapshot.digest)
            try:
                cached = (
                    None
                    if snapshot.no_cache or snapshot.chaos
                    else self.state.cache_get(snapshot.digest)
                )
                result = copy.deepcopy(cached) if cached else self._evaluate(snapshot, cancellation)
                if cancellation.cancelled():
                    raise ReviewCancelled()
                result.update(
                    session=session,
                    cache='L1' if cached else 'MISS',
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                )
                result = bound_result(result)
                if not cached and not snapshot.no_cache and not snapshot.chaos:
                    self.state.cache_put(snapshot.digest, result, snapshot.config.cache_ttl)
                self.state.finish(session, result)
                return result
            except Exception:
                self.state.finish(
                    session,
                    error='Review attempt failed or was cancelled; raw inputs were not retained.',
                )
                raise

    def _evaluate(self, snapshot: ReviewSnapshot, cancellation: CancellationToken) -> dict:
        findings = copy.deepcopy(snapshot.findings)
        summary = 'Offline deterministic checks completed; no AI review was performed.'
        provider, model, attempts = 'deterministic', None, []
        vault = Vault()
        for value in self.credentials(snapshot.config):
            vault.protect(value)
        if not snapshot.has_source:
            summary = 'No changes to review.'
        elif snapshot.mode == 'ai':
            if not snapshot.config.providers:
                raise ValueError(
                    'No provider configured. Run devpulse init or use review --offline.'
                )
            routed = self.router.review(
                snapshot.config.providers,
                snapshot.prompt,
                vault,
                chaos=snapshot.chaos,
                cancellation=cancellation,
            )
            summary = routed['response']['summary']
            findings.extend(routed['response']['findings'])
            provider, model, attempts = routed['provider'], routed['model'], routed['attempts']
        return vault.scrub_value(
            {
                'summary': summary,
                'findings': findings,
                'provider': provider,
                'model': model,
                'mode': snapshot.mode,
                'context': snapshot.context,
                'redacted_values': snapshot.redacted_values + vault.count,
                'attempts': attempts,
                'source': snapshot.source,
            }
        )
