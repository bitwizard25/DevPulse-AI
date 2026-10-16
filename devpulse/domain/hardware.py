"""Domain entities and rating algorithms for hardware capabilities and LLM sizing."""

from dataclasses import dataclass
from enum import Enum


class FitTier(str, Enum):
    FIT_VRAM = "FIT_VRAM"  # 100% GPU offload, fast inference
    FIT_RAM = "FIT_RAM"  # System RAM offload, viable CPU/hybrid inference
    OOM_DANGER = "OOM_DANGER"  # Exceeds safe memory threshold; system freeze risk


@dataclass(frozen=True)
class HardwareProfile:
    total_ram_bytes: int
    available_ram_bytes: int
    vram_bytes: int
    gpu_name: str
    os_name: str

    @property
    def total_ram_gb(self) -> float:
        return self.total_ram_bytes / (1024**3)

    @property
    def available_ram_gb(self) -> float:
        return self.available_ram_bytes / (1024**3)

    @property
    def vram_gb(self) -> float:
        return self.vram_bytes / (1024**3)


@dataclass(frozen=True)
class ModelSpec:
    name: str
    params_billion: float
    quantization: str = "Q4_K_M"
    coding_iq: int = 70  # 0-100 benchmark-derived score

    @property
    def required_memory_gb(self) -> float:
        # Weights size estimate: 4-bit quant is ~0.55-0.65 GB per billion params
        # Plus ~0.8 - 1.2 GB KV cache overhead for standard context window (4k-8k)
        quant_mult = 0.65 if "4" in self.quantization else 1.2
        return (self.params_billion * quant_mult) + 0.8


@dataclass(frozen=True)
class ModelRating:
    spec: ModelSpec
    tier: FitTier
    predicted_tps: float
    recommendation_score: float  # 0-100 composite score
    memory_required_gb: float
    vram_percent: float
    ram_percent: float


class ModelCatalog:
    @staticmethod
    def default_models() -> list[ModelSpec]:
        return [
            ModelSpec("qwen2.5-coder:1.5b", 1.5, "Q4_K_M", coding_iq=68),
            ModelSpec("starcoder2:3b", 3.0, "Q4_K_M", coding_iq=65),
            ModelSpec("llama3.2:3b", 3.2, "Q4_K_M", coding_iq=67),
            ModelSpec("phi3.5:3.8b", 3.8, "Q4_K_M", coding_iq=72),
            ModelSpec("deepseek-coder:6.7b", 6.7, "Q4_K_M", coding_iq=82),
            ModelSpec("qwen2.5-coder:7b", 7.0, "Q4_K_M", coding_iq=85),
            ModelSpec("codellama:7b", 7.0, "Q4_K_M", coding_iq=76),
            ModelSpec("mistral:7b", 7.0, "Q4_K_M", coding_iq=74),
            ModelSpec("qwen2.5-coder:14b", 14.0, "Q4_K_M", coding_iq=90),
            ModelSpec("deepseek-coder-v2:16b", 16.0, "Q4_K_M", coding_iq=88),
            ModelSpec("qwen2.5-coder:32b", 32.0, "Q4_K_M", coding_iq=93),
        ]


def rate_models(profile: HardwareProfile, models: list[ModelSpec]) -> list[ModelRating]:
    ratings: list[ModelRating] = []

    # Safe headroom: OS needs ~1.5 GB RAM minimum
    usable_ram_gb = max(0.5, profile.total_ram_gb - 1.5)
    usable_vram_gb = max(0.0, profile.vram_gb - 0.5)

    for m in models:
        req_gb = m.required_memory_gb
        vram_pct = (req_gb / profile.vram_gb * 100) if profile.vram_gb > 0 else 0.0
        ram_pct = (req_gb / profile.total_ram_gb * 100) if profile.total_ram_gb > 0 else 100.0

        if profile.vram_gb > 0 and req_gb <= usable_vram_gb:
            tier = FitTier.FIT_VRAM
            # High speed GPU offload: ~30-65 TPS depending on size
            tps = max(15.0, 60.0 - (m.params_billion * 2.2))
            score = (m.coding_iq * 0.7) + 30.0  # Bonus for VRAM fit
        elif req_gb <= usable_ram_gb:
            tier = FitTier.FIT_RAM
            # CPU/hybrid offload: ~5-15 TPS
            tps = max(3.0, 15.0 - (m.params_billion * 0.7))
            score = (m.coding_iq * 0.7) + 10.0  # Smaller bonus
        else:
            tier = FitTier.OOM_DANGER
            tps = 0.5
            score = max(0.0, (m.coding_iq * 0.3) - 20.0)

        ratings.append(
            ModelRating(
                spec=m,
                tier=tier,
                predicted_tps=round(tps, 1),
                recommendation_score=round(score, 1),
                memory_required_gb=round(req_gb, 2),
                vram_percent=round(vram_pct, 1),
                ram_percent=round(ram_pct, 1),
            )
        )

    # Sort: VRAM fits first, then RAM fits, then OOM; within each tier, highest recommendation_score
    tier_order = {FitTier.FIT_VRAM: 0, FitTier.FIT_RAM: 1, FitTier.OOM_DANGER: 2}
    ratings.sort(key=lambda r: (tier_order[r.tier], -r.recommendation_score))
    return ratings
