"""OS telemetry hardware profiler and Ollama model sizing rater."""

import re
from pathlib import Path

from ...domain.hardware import FitTier, ModelSpec, rate_models
from ...infrastructure.config import load_config
from ...infrastructure.hardware import fetch_models, probe_hardware
from ...infrastructure.project import set_model
from ..output import emit


def _estimate_spec_from_name(name: str) -> ModelSpec:
    # Try parsing parameter size from name like "deepseek-coder:6.7b" or "qwen2.5:14b"
    match = re.search(r'([0-9.]+)\s*[bB]', name)
    params = float(match.group(1)) if match else 7.0
    base_iq = 68
    if 'coder' in name.lower():
        base_iq += 10
    if params >= 14:
        base_iq += 10
    elif params >= 7:
        base_iq += 5
    return ModelSpec(
        name=name,
        params_billion=params,
        quantization='Q4_K_M',
        coding_iq=min(95, base_iq),
    )


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

    query_model = getattr(args, 'model', None)
    should_select = getattr(args, 'select', False)

    all_models = fetch_models(base_url)

    # Filter or find target model if specified
    models = all_models
    if query_model:
        matched = [m for m in all_models if query_model.lower() in m.name.lower()]
        if matched:
            models = matched
        else:
            # Custom / unlisted model requested by name
            models = [_estimate_spec_from_name(query_model)]

    ratings = rate_models(profile, models)

    # Handle --select
    if should_select:
        target_name = query_model or (ratings[0].spec.name if ratings else 'qwen2.5-coder:7b')
        set_model(root, target_name, provider_kind='ollama', base_url=base_url)
        if getattr(args, 'json', False):
            emit(
                {
                    'status': 'success',
                    'action': 'model_selected',
                    'model': target_name,
                    'provider': 'ollama',
                },
                as_json=True,
            )
        else:
            emit(f"Active model set to '{target_name}' in .devpulse/config.json")
            emit('Ready to review! Run: devpulse review')
        return 0

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

    # Detailed single-model view
    if query_model and len(ratings) == 1:
        r = ratings[0]
        emit(f'MODEL INSPECTION: {r.spec.name}')
        emit(f'  Parameter Size:    {r.spec.params_billion}B ({r.spec.quantization})')
        emit(f'  Memory Footprint:  {r.memory_required_gb:.1f} GB (Weights + KV Cache)')
        emit(f'  Coding IQ Rating:  {r.spec.coding_iq}/100')
        emit(f'  Hardware Fit:      {r.tier.value}')
        emit(f'  Predicted Speed:   ~{r.predicted_tps:.1f} tokens/second')
        if r.tier == FitTier.FIT_VRAM:
            emit('  Offload Status:    100% GPU VRAM offload (Fastest, zero CPU overhead)')
        elif r.tier == FitTier.FIT_RAM:
            free_ram = max(0.0, profile.total_ram_gb - r.memory_required_gb)
            emit(
                f'  Offload Status:    System RAM / CPU offload ({free_ram:.1f} GB RAM left for OS)'
            )
        else:
            emit('  Offload Status:    DANGER: Exceeds safe host memory! High freeze / OOM risk.')
        emit('-' * 78)
        emit(f'To activate this model: devpulse models {r.spec.name} --select')
        return 0

    # Multi-model table view
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
        emit(f'Recommendation (Fastest, 100% GPU): devpulse models {best_vram} --select')
    elif ram_models:
        best_ram = ram_models[0].spec.name
        emit(f'Recommendation (Viable, CPU offload): devpulse models {best_ram} --select')
    else:
        emit('Warning: No local model fits comfortably. Consider cloud BYOK or smaller models.')

    return 0
