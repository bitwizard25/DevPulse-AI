"""OS-native hardware telemetry and Ollama model catalog adapter."""

import ctypes
import platform
import re
import subprocess
from urllib.request import Request, urlopen

from ..domain.hardware import HardwareProfile, ModelCatalog, ModelSpec


def _probe_ram_windows() -> tuple[int, int]:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ('dwLength', ctypes.c_ulong),
            ('dwMemoryLoad', ctypes.c_ulong),
            ('ullTotalPhys', ctypes.c_ulonglong),
            ('ullAvailPhys', ctypes.c_ulonglong),
            ('ullTotalPageFile', ctypes.c_ulonglong),
            ('ullAvailPageFile', ctypes.c_ulonglong),
            ('ullTotalVirtual', ctypes.c_ulonglong),
            ('ullAvailVirtual', ctypes.c_ulonglong),
            ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        return int(stat.ullTotalPhys), int(stat.ullAvailPhys)
    return 8 * 1024**3, 4 * 1024**3


def _probe_ram_linux() -> tuple[int, int]:
    total, avail = 8 * 1024**3, 4 * 1024**3
    try:
        with open('/proc/meminfo', 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    total = int(line.split()[1]) * 1024
                elif line.startswith('MemAvailable:'):
                    avail = int(line.split()[1]) * 1024
    except Exception:
        pass
    return total, avail


def _probe_ram_darwin() -> tuple[int, int]:
    try:
        out = subprocess.check_output(['sysctl', '-n', 'hw.memsize'], timeout=2).strip()
        total = int(out)
        return total, int(total * 0.6)
    except Exception:
        return 8 * 1024**3, 4 * 1024**3


def _probe_gpu() -> tuple[str, int]:
    # 1. Try nvidia-smi across Windows and Linux
    try:
        proc = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            first_line = proc.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in first_line.split(',')]
            name = parts[0]
            vram_mb = float(parts[1]) if len(parts) > 1 else 0.0
            return name, int(vram_mb * 1024 * 1024)
    except Exception:
        pass

    # 2. Apple Silicon unified memory
    if platform.system() == 'Darwin' and platform.machine() == 'arm64':
        total_ram, _ = _probe_ram_darwin()
        return 'Apple Silicon (Unified Memory)', total_ram

    return 'Integrated / CPU Fallback', 0


def probe_hardware() -> HardwareProfile:
    os_sys = platform.system()
    if os_sys == 'Windows':
        total_ram, avail_ram = _probe_ram_windows()
    elif os_sys == 'Linux':
        total_ram, avail_ram = _probe_ram_linux()
    elif os_sys == 'Darwin':
        total_ram, avail_ram = _probe_ram_darwin()
    else:
        total_ram, avail_ram = 8 * 1024**3, 4 * 1024**3

    gpu_name, vram_bytes = _probe_gpu()
    return HardwareProfile(
        total_ram_bytes=total_ram,
        available_ram_bytes=avail_ram,
        vram_bytes=vram_bytes,
        gpu_name=gpu_name,
        os_name=os_sys,
    )


def http_json(url: str, timeout: float = 2.0) -> dict:
    import json

    req = Request(url, headers={'User-Agent': 'devpulse/hardware-profiler'})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _parse_param_size(val: str) -> float:
    match = re.search(r'([0-9.]+)\s*[bB]', val)
    return float(match.group(1)) if match else 7.0


def fetch_models(base_url: str = 'http://127.0.0.1:11434') -> list[ModelSpec]:
    clean_url = base_url.rstrip('/')
    try:
        data = http_json(f'{clean_url}/api/tags', timeout=2.0)
        items = data.get('models', [])
        if not items:
            return ModelCatalog.default_models()
        specs: list[ModelSpec] = []
        for item in items:
            name = item.get('name', 'unknown')
            details = item.get('details', {})
            param_str = details.get('parameter_size', '7B')
            quant = details.get('quantization_level', 'Q4_K_M')
            params = _parse_param_size(param_str)
            # Estimate coding IQ based on params & name
            base_iq = 65
            if 'coder' in name.lower():
                base_iq += 12
            if params >= 14:
                base_iq += 10
            elif params >= 7:
                base_iq += 6
            specs.append(
                ModelSpec(
                    name=name,
                    params_billion=params,
                    quantization=quant,
                    coding_iq=min(95, base_iq),
                )
            )
        return specs
    except Exception:
        return ModelCatalog.default_models()
