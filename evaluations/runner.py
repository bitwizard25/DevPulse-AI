"""Run the real CLI in disposable fixtures and grade observable outcomes."""

import argparse
import json
import os
import platform
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from devpulse.domain.hardware import initial_token_budget
from devpulse.domain.models import Config, ProviderConfig
from devpulse.infrastructure.agent_commands import stop_command
from devpulse.infrastructure.hardware import probe_hardware

from .cases import CASES

REPO = Path(__file__).resolve().parents[1]


def local_config(model):
    budget = initial_token_budget(probe_hardware(), local=True)
    return Config(providers=[ProviderConfig(model=model, **asdict(budget))]).as_dict()


def prepare_case(case, root):
    root.mkdir(parents=True, exist_ok=True)
    for name, content in case.files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode('utf-8'))


def grade_case(case, root, answer, actions):
    failures = []
    changed = {
        path.relative_to(root).as_posix()
        for path in root.rglob('*')
        if path.is_file()
        and not any(part in ('.devpulse', '__pycache__', '.git') for part in path.parts)
        and (
            path.relative_to(root).as_posix() not in case.files
            or path.read_bytes() != case.files[path.relative_to(root).as_posix()].encode('utf-8')
        )
    }
    changed.update(name for name in case.files if not (root / name).is_file())
    if changed - set(case.editable):
        failures.append('unexpected_changes')
    if not any(
        item['name'] == case.required_tool
        and item['status'] == 'completed'
        and not item['result'].get('timed_out')
        and (
            case.required_tool != 'run_command'
            or (
                item['result'].get('exit_code') == 0
                and re.search(
                    r'Ran [1-9]\d* tests?\b.*\bOK\b|\b[1-9]\d* passed\b',
                    item['result'].get('output', ''),
                    re.DOTALL,
                )
            )
        )
        for item in actions
    ):
        failures.append('required_tool')
    if any(not re.search(pattern, answer, re.IGNORECASE) for pattern in case.answer_patterns):
        failures.append('answer_evidence')
    verifier_output = ''
    if case.verifier:
        # The independent checker stays outside the agent's project and transcript.
        code = 'import sys\nsys.path.insert(0, sys.argv[1])\n' + case.verifier
        try:
            result = subprocess.run(
                [sys.executable, '-I', '-c', code, str(root)],
                cwd=root,
                capture_output=True,
                timeout=10,
            )
            if result.returncode:
                failures.append('behavior')
                verifier_output = result.stderr.decode('utf-8', errors='replace')[-4000:]
        except subprocess.TimeoutExpired:
            failures.append('verifier_timeout')
    return {
        'passed': not failures,
        'failures': failures,
        'changed_files': sorted(changed),
        'verifier_output': verifier_output,
    }


def read_actions(home):
    path = home / 'state.db'
    if not path.is_file():
        return []
    with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as db:
        messages = [
            row[0]
            for row in db.execute(
                "SELECT content FROM agent_messages WHERE role='tool' ORDER BY id"
            )
        ]
        actions = []
        for call_id, name, status, result in db.execute(
            'SELECT call_id,name,status,result FROM agent_actions ORDER BY rowid'
        ):
            evidence = json.loads(result or '{}')
            prefix = f'Tool result {call_id}: '
            for message in messages:
                if message.startswith(prefix):
                    evidence.update(json.loads(message[len(prefix) :]))
            actions.append({'name': name, 'status': status, 'result': evidence})
        return actions


def run_case(case, config, timeout):
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='devpulse-eval-') as directory:
        base = Path(directory).resolve()
        root, home = base / 'project', base / 'state'
        prepare_case(case, root)
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        (root / '.devpulse').mkdir()
        (root / '.devpulse/config.json').write_text(json.dumps(config), encoding='utf-8')
        env = dict(os.environ, DEVPULSE_HOME=str(home), PYTHONUTF8='1')
        env['PYTHONPATH'] = str(REPO)
        argv = [
            sys.executable,
            '-m',
            'devpulse',
            '--project',
            str(root),
            'run',
            case.task,
            '--new',
            '--allow-edits',
            '--allow-commands',
            '--json',
        ]
        options = (
            {'creationflags': subprocess.CREATE_NO_WINDOW}
            if os.name == 'nt'
            else {'start_new_session': True}
        )
        timed_out = False
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(
                argv,
                cwd=root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                **options,
            )
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                stop_command(process)
            except BaseException:
                stop_command(process)
                raise
            stdout.seek(0)
            stderr.seek(0)
            output = stdout.read(65536).decode('utf-8', errors='replace')
            trace = stderr.read(65536).decode('utf-8', errors='replace')
        try:
            answer = json.loads(output)['message']
        except (ValueError, KeyError, TypeError):
            answer = ''
        actions = read_actions(home)
        grade = grade_case(case, root, answer, actions)
        if process.returncode or timed_out:
            grade['failures'].append('timeout' if timed_out else 'cli_error')
            grade['passed'] = False
        return {
            'case': case.id,
            'task': case.task,
            **grade,
            'elapsed_seconds': round(time.monotonic() - started, 2),
            'exit_code': process.returncode,
            'answer': answer,
            'actions': actions,
            'trace': trace,
            'files_after': {
                name: (root / name).read_text('utf-8', errors='replace')[:12000]
                for name in case.editable
                if (root / name).is_file()
            },
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    provider = parser.add_mutually_exclusive_group(required=True)
    provider.add_argument('--model', help='Installed Ollama model to evaluate.')
    provider.add_argument('--config', type=Path, help='Existing DevPulse config JSON to copy.')
    parser.add_argument('--case', action='append', choices=[case.id for case in CASES])
    parser.add_argument('--timeout', type=int, default=600, help='Per-task deadline in seconds.')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error('--timeout must be positive')
    config = json.loads(args.config.read_text('utf-8')) if args.config else local_config(args.model)
    for item in config.get('providers', []):
        ProviderConfig(**item).validate()
    if not config.get('providers'):
        parser.error('Evaluation requires at least one configured provider.')
    report = {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(),
        'platform': platform.platform(),
        'config': config,
        'cases': [],
        'scope': 'Small local task suite; not a Codex parity or production success-rate measurement.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        if args.case and case.id not in args.case:
            continue
        print(f'Running {case.id}...', flush=True)
        result = run_case(case, config, args.timeout)
        report['cases'].append(result)
        report['passed'] = sum(item['passed'] for item in report['cases'])
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(
            f'{case.id}: {"PASS" if result["passed"] else "FAIL"} '
            f'({result["elapsed_seconds"]}s) {result["failures"]}',
            flush=True,
        )
    return 0 if all(item['passed'] for item in report['cases']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
