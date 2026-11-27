import unittest

import torch

from training.model.NILMFormer.NILMFormer import NILMFormer, NILMFormerConfig


class NILMFormerTests(unittest.TestCase):
    def test_custom_dilations_and_config(self):
        config = NILMFormerConfig(dilations=[1, 3, 3], d_model=16, n_head=4, n_encoder_layers=1, dp_rate=0, norm_eps=1e-3)
        model = NILMFormer(config).eval()
        self.assertIs(model.config, config)
        self.assertEqual(model.EncoderBlock[-1].eps, 1e-5)
        self.assertEqual(model.EncoderBlock[0].norm1.eps, 1e-3)
        self.assertEqual(model.EmbedBlock.block_names, ["dilated_1", "dilated_3", "dilated_3_2"])
        with torch.no_grad():
            prediction = model(torch.randn(2, 9, 17))
        self.assertEqual(prediction.shape, (2, 1, 17))
        self.assertTrue(torch.isfinite(prediction).all())

    def test_shapes_and_gradients(self):
        for channels in (1, 9):
            with self.subTest(channels=channels):
                model = NILMFormer(
                    NILMFormerConfig(
                        c_out=channels,
                        d_model=16,
                        n_head=4,
                        n_encoder_layers=1,
                        dp_rate=0,
                    )
                )
                x = torch.randn(2, 9, 17)
                prediction = model(x)
                self.assertEqual(prediction.shape, (2, channels, 17))
                loss = (prediction - torch.randn_like(prediction)).square().mean()
                loss.backward()
                for name, parameter in model.named_parameters():
                    self.assertIsNotNone(parameter.grad, name)
                    self.assertTrue(torch.isfinite(parameter.grad).all(), name)

    def test_constant_aggregate_is_finite(self):
        model = NILMFormer(NILMFormerConfig()).eval()
        with torch.no_grad():
            for length in (1, 32):
                prediction = model(torch.zeros(2, 9, length))
                self.assertEqual(prediction.shape, (2, 1, length))
                self.assertTrue(torch.isfinite(prediction).all())

    def test_output_has_no_on_off_gate(self):
        model = NILMFormer(NILMFormerConfig()).eval()
        with torch.no_grad():
            model.DownstreamTaskHead.weight.zero_()
            model.DownstreamTaskHead.bias.zero_()
            model.ProjStats2.weight.zero_()
            model.ProjStats2.bias.copy_(torch.tensor([2.0, 1.0]))
            prediction = model(torch.zeros(2, 9, 16))
        torch.testing.assert_close(prediction, torch.full_like(prediction, 2.0))


if __name__ == "__main__":
    unittest.main()
