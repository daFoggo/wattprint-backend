import json
import random
import unittest
from pathlib import Path

import numpy as np
import torch

from training.model.TwoStageNILMFormer.GRUDetector import GRUConfig
from training.model.TwoStageNILMFormer.NILMFormerRegressor import NILMFormerConfig
from training.seeds import BASE_SEED, generate_model_seeds, make_data_generator, seed_everything
from training.train_twostage_nilmformer import initialize_twostage_nilmformer


class SeedTests(unittest.TestCase):
    def test_saved_seeds_are_unique_reproducible_and_do_not_change_global_rng(self):
        config = json.loads((Path(__file__).parents[1] / "configs/seeds.json").read_text(encoding="utf-8"))
        random.seed(99)
        state = random.getstate()
        seeds = generate_model_seeds()
        self.assertEqual(random.getstate(), state)
        self.assertEqual(seeds, config["model_seeds"])
        self.assertEqual(len(set(seeds)), 5)
        self.assertTrue(all(0 <= seed <= 2**31 - 1 for seed in seeds))

    def test_python_numpy_and_torch_repeat(self):
        seed_everything()
        first = (random.random(), np.random.rand(), torch.rand(4))
        seed_everything()
        second = (random.random(), np.random.rand(), torch.rand(4))
        self.assertEqual(first[:2], second[:2])
        torch.testing.assert_close(first[2], second[2], rtol=0, atol=0)
        self.assertTrue(torch.are_deterministic_algorithms_enabled())

    def test_model_seed_controls_both_stages(self):
        detector = GRUConfig(c_out=2, conv_channels=4, hidden=4)
        regressor = NILMFormerConfig(c_out=2, d_model=16, n_head=4, n_encoder_layers=1)
        seeds = generate_model_seeds()
        first = initialize_twostage_nilmformer(detector, regressor, seeds[0])
        same = initialize_twostage_nilmformer(detector, regressor, seeds[0])
        other = initialize_twostage_nilmformer(detector, regressor, seeds[1])
        for key, value in first.state_dict().items():
            torch.testing.assert_close(value, same.state_dict()[key], rtol=0, atol=0)
        for key in ("Detector.EmbedBlock.0.weight", "Regressor.TokenStats.weight"):
            self.assertFalse(torch.equal(first.state_dict()[key], other.state_dict()[key]))

    def test_data_generator_is_independent_of_model_seed(self):
        generator = make_data_generator()
        expected = torch.randperm(20, generator=generator)
        seed_everything(generate_model_seeds()[1])
        actual = torch.randperm(20, generator=make_data_generator(BASE_SEED))
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)
        with self.assertRaisesRegex(AssertionError, "Số seed"):
            generate_model_seeds(count=10, lower=0, upper=5)


if __name__ == "__main__":
    unittest.main()
