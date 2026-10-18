# Live task evaluations

Run from the checkout with an installed local model:

```sh
python -m evaluations.runner --model phi3.5:3.8b --output .devpulse/evaluations/phi.json
python -m evaluations.runner --model gemma4:e4b --case run-tests --output .devpulse/evaluations/gemma-tests.json
```

Use `--config /path/to/.devpulse/config.json` instead of `--model` to evaluate a configured provider chain. This sends only disposable fixture code to those providers and may incur their normal API charges. Credential values are resolved by DevPulse; keep only environment variable names in configuration. `--timeout` bounds each task (default 600 seconds).

Each case gets a fresh temporary project and state database. The real CLI receives a natural-language task with edit/command permission. Independent checks outside the project validate resulting behavior, reject edits to acceptance tests and unrelated files, and require recorded successful test output when the task asks for tests. Review checks require the seeded SQL finding with a source location and unchanged source. Claims of completion alone cannot pass. The runner records failures, elapsed time, tool evidence, bounded traces, and relevant resulting code; it writes the report after each completed case.

The four starting cases cover a retry-bound bug, a feature spanning files, test execution without edits, and a read-only project audit. This small suite exposes harness failures; it does not establish a representative production success rate or parity with Codex. Repeat trials, expand tasks and languages, and compare agents on identical fixtures before making those claims. Hidden checks here are held out from the task prompt and fixture, not protected against an adversarial agent inspecting the host filesystem.
