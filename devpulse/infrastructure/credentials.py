"""Resolve provider keys from process or Windows user environment, never project files."""

import os
import re

IS_WINDOWS = os.name == 'nt'


def read_api_key(name: str) -> str:
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        return ''
    if name in os.environ:
        return os.environ[name]
    if not IS_WINDOWS:
        return ''
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
            value, kind = winreg.QueryValueEx(key, name)
            return value if kind == winreg.REG_SZ and isinstance(value, str) else ''
    except OSError:
        return ''


def save_api_key(name: str, value: str) -> bool:
    """Activate immediately; persist in HKCU on Windows. Return whether it was saved."""
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ValueError('Invalid API key environment variable name.')
    if not value or len(value) > 4096 or any(not 33 <= ord(char) <= 126 for char in value):
        raise ValueError('API key must be nonempty text without spaces or control characters.')
    os.environ[name] = value
    if not IS_WINDOWS:
        return False
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, 'Environment', 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    return True
