"""Conservative deterministic Python checks; these never execute target code."""

import ast


def finding(rule: str, severity: str, path: str, line: int, message: str) -> dict:
    return {'rule': rule, 'severity': severity, 'path': path, 'line': line, 'message': message}


def check_python(files: list[dict]) -> list[dict]:
    findings = []
    for file in files:
        if not file['path'].endswith('.py'):
            continue
        try:
            tree = ast.parse(file['content'], filename=file['path'])
        except (SyntaxError, ValueError, RecursionError) as exc:
            findings.append(
                finding(
                    'python-syntax',
                    'error',
                    file['path'],
                    getattr(exc, 'lineno', 1) or 1,
                    'Python could not parse this file. Check the syntax locally.',
                )
            )
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id in ('eval', 'exec'):
                findings.append(
                    finding(
                        'dynamic-execution',
                        'warning',
                        file['path'],
                        node.lineno,
                        'Dynamic code execution: ensure the input is trusted.',
                    )
                )
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == 'subprocess'
            ):
                if any(
                    k.arg == 'shell' and isinstance(k.value, ast.Constant) and k.value.value is True
                    for k in node.keywords
                ):
                    findings.append(
                        finding(
                            'shell-execution',
                            'warning',
                            file['path'],
                            node.lineno,
                            'shell=True can allow command injection with untrusted input.',
                        )
                    )
    return findings
