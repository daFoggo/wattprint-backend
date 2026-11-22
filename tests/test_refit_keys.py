from scripts import refit


def test_keyed_home_has_its_own_meter_and_source():
    assert refit.meter(5) == "REFIT-H5"
    assert refit.source(5) == "refit/CLEAN_House5.csv"
    assert refit.meter(5, "5") == "REFIT-H5"
    assert refit.meter(5, "5-heat") == "REFIT-H5-heat"
    assert refit.source(5, "5-heat") == "refit/CLEAN_House5.csv#5-heat"
    assert refit.house_of("refit/CLEAN_House5.csv#5-heat") == 5
    assert refit.key_of("refit/CLEAN_House5.csv#5-heat") == "5-heat"
    assert refit.key_of("refit/CLEAN_House2.csv") == "2"
