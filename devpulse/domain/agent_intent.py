"""Small deterministic routes for high-confidence task modes."""

import re

_PROJECT_REVIEW = re.compile(
    r'\b(?:review|audit|scan|check)\s+'
    r'(?:(?:the|this|our|my|your|current|entire|whole|full|all)\s+)*'
    r'(?:project|repo(?:sitory)?|code\s*base)(?:\s+(?:code|files|source))?'
    r'(?=$|[?.!,;]|\s+(?:for|and|without|but|to|please)\b)',
    re.IGNORECASE,
)
_EXPLANATION = re.compile(
    r'^\s*(?:please\s+)?(?:(?:can|could|would|will)\s+you\s+)?'
    r'(?:explain|describe|how|what|why|(?:tell|show)\s+me\s+how)\b',
    re.IGNORECASE,
)
_NEGATED_REVIEW = re.compile(r"\b(?:do\s+not|don't|dont|never|avoid)\s*$", re.IGNORECASE)
_MUTATION = re.compile(
    r'\b(fix|change|edit|implement|modify|update|rewrite|refactor|repair|apply|write)\w*\b',
    re.IGNORECASE,
)
_NEGATED_MUTATION = re.compile(
    r"\b(?:do\s+not|don't|dont|without|avoid|never|no)\s+(?:\w+\s+){0,2}"
    r'(?:fix|change|edit|implement|modify|update|rewrite|refactor|repair|apply|write)\w*\b',
    re.IGNORECASE,
)
_TEST_EXECUTION = re.compile(
    r'\b(?:run|rerun|execute)\s+(?:(?:the|all|our|existing|unit|integration|automated|project)\s+)*'
    r'(?:tests?|test\s+suite|pytest|unittest)\b'
    r'|\b(?:check|verify|ensure|confirm|make\s+sure)\b[^.!?\n]{0,60}\btests?\b'
    r'[^.!?\n]{0,30}\b(?:pass|passes|passing)\b',
    re.IGNORECASE,
)


def requests_test_execution(task: str) -> bool:
    """Recognize explicit test execution requests, without treating explanations as actions."""
    if _EXPLANATION.search(task):
        return False
    return any(
        not _NEGATED_REVIEW.search(task[: match.start()])
        for match in _TEST_EXECUTION.finditer(task)
    )


def requests_project_review(task: str) -> bool:
    """Recognize explicit project audits; leave ambiguous requests to the task model."""
    if _EXPLANATION.search(task):
        return False
    return any(
        not _NEGATED_REVIEW.search(task[: match.start()])
        for match in _PROJECT_REVIEW.finditer(task)
    )


def is_read_only_project_review(task: str) -> bool:
    """Recognize explicit project-wide review requests without claiming edit intent."""
    mutation_intent = _NEGATED_MUTATION.sub('', task)
    return (
        requests_project_review(task)
        and not _MUTATION.search(mutation_intent)
        and not requests_test_execution(task)
    )
