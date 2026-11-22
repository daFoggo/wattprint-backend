import pytest

torch = pytest.importorskip("torch")

from app.ml.nilm.DilatedResidualBlock import DilatedResidualBlock  # noqa: E402


def test_the_four_trained_dilations_build():
    block = DilatedResidualBlock(c_in=1, c_out=8, kernel_size=3, dilated_list=[1, 2, 4, 8])
    assert block(torch.zeros(1, 1, 16)).shape == (1, 8, 16)


def test_other_dilations_are_refused_not_ignored():
    with pytest.raises(ValueError):
        DilatedResidualBlock(c_in=1, c_out=8, kernel_size=3, dilated_list=[1, 2])
