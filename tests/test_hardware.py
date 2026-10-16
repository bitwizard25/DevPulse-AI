import unittest

from devpulse.domain.hardware import (
    FitTier,
    HardwareProfile,
    ModelCatalog,
    ModelSpec,
    rate_models,
)


class HardwareDomainTests(unittest.TestCase):
    def test_fit_tier_and_memory_estimation(self):
        # 8 GB RAM, 4 GB VRAM (like an RTX 2050 laptop)
        profile = HardwareProfile(
            total_ram_bytes=8 * 1024**3,
            available_ram_bytes=4 * 1024**3,
            vram_bytes=4 * 1024**3,
            gpu_name="NVIDIA GeForce RTX 2050",
            os_name="Windows",
        )

        models = [
            ModelSpec("qwen2.5-coder:1.5b", 1.5, "Q4_K_M", coding_iq=68),
            ModelSpec("qwen2.5-coder:7b", 7.0, "Q4_K_M", coding_iq=84),
            ModelSpec("qwen2.5-coder:14b", 14.0, "Q4_K_M", coding_iq=89),
            ModelSpec("qwen2.5-coder:32b", 32.0, "Q4_K_M", coding_iq=92),
        ]

        ratings = rate_models(profile, models)
        rating_map = {r.spec.name: r for r in ratings}

        # 1.5b (~1.2 GB) fits comfortably in 4GB VRAM
        self.assertEqual(rating_map["qwen2.5-coder:1.5b"].tier, FitTier.FIT_VRAM)
        self.assertTrue(rating_map["qwen2.5-coder:1.5b"].predicted_tps > 30)

        # 7b (~5.0 GB) does not fit in 4GB VRAM, but fits in 8GB RAM
        self.assertEqual(rating_map["qwen2.5-coder:7b"].tier, FitTier.FIT_RAM)

        # 14b (~9.5 GB) and 32b (~20 GB) exceed 8GB RAM -> OOM
        self.assertEqual(rating_map["qwen2.5-coder:14b"].tier, FitTier.OOM_DANGER)
        self.assertEqual(rating_map["qwen2.5-coder:32b"].tier, FitTier.OOM_DANGER)

    def test_default_catalog_contains_popular_coding_models(self):
        catalog = ModelCatalog.default_models()
        names = [m.name for m in catalog]
        self.assertIn("qwen2.5-coder:7b", names)
        self.assertIn("deepseek-coder:6.7b", names)
        self.assertTrue(all(m.coding_iq > 0 for m in catalog))

    def test_rating_sorting_prioritizes_best_viable_iq(self):
        profile = HardwareProfile(
            total_ram_bytes=32 * 1024**3,
            available_ram_bytes=24 * 1024**3,
            vram_bytes=16 * 1024**3,
            gpu_name="NVIDIA RTX 4080",
            os_name="Linux",
        )
        models = [
            ModelSpec("small:1b", 1.0, "Q4_K_M", coding_iq=55),
            ModelSpec("best:14b", 14.0, "Q4_K_M", coding_iq=90),
            ModelSpec("mid:7b", 7.0, "Q4_K_M", coding_iq=82),
        ]
        ratings = rate_models(profile, models)
        # In a 16GB VRAM card, 14B fits in VRAM and has highest IQ, so it should rank top
        self.assertEqual(ratings[0].spec.name, "best:14b")


if __name__ == "__main__":
    unittest.main()
