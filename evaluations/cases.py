"""Small held-out acceptance checks for real natural-language task execution."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskCase:
    id: str
    task: str
    files: dict[str, str]
    editable: tuple[str, ...] = ()
    verifier: str = ''
    required_tool: str = 'run_command'
    answer_patterns: tuple[str, ...] = ()


CASES = (
    TaskCase(
        'retry-bound',
        'Fix should_retry in retry.py so only zero-based attempts 0, 1 and 2 retry. '
        'Negative attempts must not retry. Preserve the public function and run the tests.',
        {
            'retry.py': 'def should_retry(attempts):\n    return attempts < 10\n',
            'test_retry.py': (
                'import unittest\nfrom retry import should_retry\n\n'
                'class RetryTests(unittest.TestCase):\n'
                '    def test_attempt_bound(self):\n'
                '        self.assertTrue(should_retry(2))\n'
                '        self.assertFalse(should_retry(3))\n'
                '        self.assertFalse(should_retry(-1))\n'
            ),
        },
        editable=('retry.py',),
        verifier=(
            'from retry import should_retry\n'
            'assert [bool(should_retry(n)) for n in range(-5, 20)] '
            '== [0 <= n < 3 for n in range(-5, 20)]\n'
        ),
    ),
    TaskCase(
        'cross-file-feature',
        'Make invoice(items) in invoice.py return USD followed by a space and the subtotal '
        'formatted with exactly two decimal places. Item values are integer cents. '
        'Keep using totals.subtotal, add reusable money.format_usd(cents), support zero '
        'and negative totals, and run the tests.',
        {
            'totals.py': 'def subtotal(items):\n    return sum(items)\n',
            'invoice.py': (
                'from totals import subtotal\n\ndef invoice(items):\n'
                '    return str(subtotal(items))\n'
            ),
            'test_invoice.py': (
                'import unittest\nfrom invoice import invoice\n\n'
                'class InvoiceTests(unittest.TestCase):\n'
                '    def test_formatted_total(self):\n'
                "        self.assertEqual(invoice([199, 1]), 'USD 2.00')\n"
            ),
        },
        editable=('invoice.py', 'money.py'),
        verifier=(
            'from invoice import invoice\nfrom money import format_usd\n'
            "assert invoice([199, 1]) == 'USD 2.00'\n"
            "assert invoice([]) == 'USD 0.00'\n"
            "assert invoice([-101, 1]) == 'USD -1.00'\n"
            "assert format_usd(12345) == 'USD 123.45'\n"
        ),
    ),
    TaskCase(
        'run-tests',
        'Check all tests pass and report the actual result. Do not edit any files.',
        {
            'arithmetic.py': 'def add(left, right):\n    return left + right\n',
            'test_math.py': (
                'import unittest\nfrom arithmetic import add\n\n'
                'class MathTests(unittest.TestCase):\n'
                '    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n'
            ),
        },
        verifier='from arithmetic import add\nassert add(2, 3) == 5\n',
    ),
    TaskCase(
        'project-review',
        'Review the entire repository for security issues. Do not edit files.',
        {
            'billing.py': (
                'def find_invoice(connection, user_input):\n'
                '    return connection.execute("SELECT * FROM invoices WHERE id = " + user_input)\n'
            ),
            'README.md': '# Billing\nThe caller supplies an untrusted invoice identifier.\n',
        },
        required_tool='review_project',
        answer_patterns=(r'billing\.py:\d+', r'SQL|injection|parameteriz'),
    ),
)
