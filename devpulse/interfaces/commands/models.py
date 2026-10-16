"""OS telemetry hardware profiler and Ollama model sizing rater."""

from pathlib import Path

from ...domain.hardware import FitTier, rate_models
from ...infrastructure.config import load_config
from ...infrastructure.hardware import fetch_models, probe_hardware
from ..output import emit


def handle(args, root: Path) -> int:
    profile = probe_hardware()

    # Determine base url if configured
    base_url = 'http://127.0.0.1:11434'
    try:
        config = load_config(root)
        for p in config.providers:
            if p.kind == 'ollama' and p.base_url:
                base_url = p.base_url
                break
    except Exception:
        pass

    if getattr(args, 'base_url', None):
        base_url = args.base_url

    models = fetch_models(base_url)
    ratings = rate_models(profile, models)

    if getattr(args, 'json', False):
        emit(
            {
                'hardware': {
                    'os': profile.os_name,
                    'ram_total_gb': round(profile.total_ram_gb, 2),
                    'ram_available_gb': round(profile.available_ram_gb, 2),
                    'gpu': profile.gpu_name,
                    'vram_gb': round(profile.vram_gb, 2),
                },
                'base_url': base_url,
                'ratings': [
                    {
                        'model': r.spec.name,
                        'params_b': r.spec.params_billion,
                        'tier': r.tier.value,
                        'memory_required_gb': r.memory_required_gb,
                        'predicted_tps': r.predicted_tps,
                        'coding_iq': r.spec.coding_iq,
                        'recommendation_score': r.recommendation_score,
                    }
                    for r in ratings
                ],
            },
            as_json=True,
        )
        return 0

    emit(f'DevPulse Hardware Profiler | OS: {profile.os_name} | GPU: {profile.gpu_name}')
    emit(
        f'RAM: {profile.total_ram_gb:.1f} GB Total ({profile.available_ram_gb:.1f} GB Avail) | VRAM: {profile.vram_gb:.1f} GB'
    )
    emit('-' * 78)
    emit(f'{"MODEL":<24} {"REQ MEM":<9} {"FIT TIER":<12} {"PRED TPS":<10} {"IQ":<5} {"SCORE":<6}')
    emit('-' * 78)

    tier_labels = {
        FitTier.FIT_VRAM: 'VRAM FIT',
        FitTier.FIT_RAM: 'RAM FIT',
        FitTier.OOM_DANGER: 'OOM DANGER',
    }

    for r in ratings:
        tier_str = tier_labels.get(r.tier, r.tier.value)
        emit(
            f'{r.spec.name:<24} {r.memory_required_gb:>6.1f} GB  {tier_str:<12} {r.predicted_tps:>6.1f} t/s  {r.spec.coding_iq:>3}   {r.recommendation_score:>5.1f}'
        )

    emit('-' * 78)
    vram_models = [r for r in ratings if r.tier == FitTier.FIT_VRAM]
    ram_models = [r for r in ratings if r.tier == FitTier.FIT_RAM]

    if vram_models:
        best_vram = vram_models[0].spec.name
        emit(f'Recommendation (Fastest, 100% GPU): devpulse init --model {best_vram}')
    elif ram_models:
        best_ram = ram_models[0].spec.name
        emit(f'Recommendation (Viable, CPU offload): devpulse init --model {best_ram}')
    else:
        emit(
            'Warning: No local model fits comfortably. Consider cloud BYOK or smaller quantized models.'
        )

    return 0
