import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from training.data import REFITCSVDataset


class CSVDataTests(unittest.TestCase):
    def test_csv_roundtrip_normalization_and_missing_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {
                "config": {"storage_format": "csv", "window_size": 2, "power_scale_w": 10000},
                "target_channels": ["Kettle", "Microwave"],
                "shards": [{"split": "train", "house": 1, "windows": 2, "file": "train_house_01.csv"}],
            }
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            frame = pd.DataFrame(
                {
                    "house_id": [1] * 4,
                    "window_id": [0, 0, 1, 1],
                    "step": [0, 1, 0, 1],
                    "timestamp": pd.date_range("2023-01-01", periods=4, freq="1min"),
                    "aggregate_w": [1000.0] * 4,
                    "Kettle_w": [2000.0, 0.0, 0.0, 1000.0],
                    "Kettle_on": [1, 0, 0, 1],
                    "Kettle_valid": [1] * 4,
                    "Microwave_w": [np.nan] * 4,
                    "Microwave_on": [np.nan] * 4,
                    "Microwave_valid": [0] * 4,
                }
            )
            path = root / "train_house_01.csv"
            frame.to_csv(path, index=False)
            dataset = REFITCSVDataset(root, "train", house_id=1)
            sample = dataset[0]
            self.assertEqual(len(dataset), 2)
            self.assertEqual(sample["x"].shape, (9, 2))
            torch.testing.assert_close(sample["x"][0], torch.tensor([0.1, 0.1]))
            torch.testing.assert_close(sample["power"][0], torch.tensor([0.2, 0.0]))
            self.assertFalse(sample["valid"][1].any())
            self.assertTrue((sample["power"][1] == 0).all())
            raw = REFITCSVDataset(root, "train", normalize=False)[0]
            torch.testing.assert_close(raw["power"][0], torch.tensor([2000.0, 0.0]))
            self.assertEqual(dataset[1]["start_time_ns"], pd.Timestamp("2023-01-01 00:02").value)
            # Không cho ghép sai cửa sổ chỉ vì số dòng vẫn chia hết cho L.
            frame.loc[1, "step"] = 0
            frame.to_csv(path, index=False)
            with self.assertRaisesRegex(AssertionError, "không đúng thứ tự"):
                REFITCSVDataset(root, "train")[0]


if __name__ == "__main__":
    unittest.main()
