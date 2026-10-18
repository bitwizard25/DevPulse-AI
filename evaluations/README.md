# Live task evaluations

Run from the checkout with an installed local model:

```sh
python -m evaluations.runner --model phi3.5:3.8b --output .devpulse/evaluations/phi.json
python -m evaluations.runner --model gemma4:e4b --case run-tests --output .devpulse/evaluations/gemma-tests.json
```

Use `--config /path/to/.devpulse/config.json` instead of `--model` to evaluate a configured provider chain. This sends only disposable fixture code to those providers and may incur their normal API charges. Credential values are resolved by DevPulse; keep only environment variable names in configuration. `--timeout` bounds each task (default 600 seconds).

Each case gets a fresh temporary project and state database. The real CLI receives a natural-language task with edit/command permission. Independent checks outside the project validate resulting behavior, reject edits to acceptance tests and unrelated files, and require recorded successful test output when the task asks for tests. Review checks require the seeded SQL finding with a source location and unchanged source. Claims of completion alone cannot pass. The runner records failures, elapsed time, tool evidence, bounded traces, and relevant resulting code; it writes the report after each completed case.

The four starting cases cover a retry-bound bug, a feature spanning files, test execution without edits, and a read-only project audit. This small suite exposes harness failures; it does not establish a representative production success rate or parity with Codex. Repeat trials, expand tasks and languages, and compare agents on identical fixtures before making those claims. Hidden checks here are held out from the task prompt and fixture, not protected against an adversarial agent inspecting the host filesystem.

`--model` uses the same hardware-constrained context/output budget as interactive local setup. Reports include that configuration; compare timings only when budgets and fixtures match.

On 2026-10-18, the Phi3.5 run-tests trial at a 4096-token context and 512-token output budget failed independent grading after 80.41 seconds: it ran a Python file that only defined tests, produced no test output, and claimed success. Version 0.3.6 adds a regression-tested completion check that rejects empty or zero-test summaries. That final change has not yet been rerun against the live model. Automated harness tests and installed-package smoke checks do not establish live task success.
