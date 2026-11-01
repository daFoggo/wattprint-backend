import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = json.loads((ROOT / "app" / "seed" / "refit_metadata.json").read_text(encoding="utf-8"))
HOUSES = [*range(1, 14), *range(15, 22)]


def test_twenty_houses_without_house_14():
    assert sorted(int(h) for h in META) == HOUSES


def test_keys_match_csv_file_names():
    csv_dir = ROOT / "dataset" / "CLEAN_REFIT_081116"
    if csv_dir.is_dir():
        names = {p.name for p in csv_dir.glob("CLEAN_House*.csv")}
    else:  # the dataset is not in git; fall back to the documented file naming
        names = {f"CLEAN_House{h}.csv" for h in HOUSES}
    assert {f"CLEAN_House{h}.csv" for h in META} == names


def test_each_house_has_aggregate_and_nine_appliances():
    for h, info in META.items():
        assert list(info["channels"]) == ["Aggregate", *[f"Appliance{k}" for k in range(1, 10)]], h
        assert info["channels"]["Aggregate"] == {"name": "Aggregate"}
        for k in range(1, 10):
            assert set(info["channels"][f"Appliance{k}"]) == {"name", "brand", "model", "note"}


def test_unknown_names_mapped():
    assert META["12"]["channels"]["Appliance2"]["name"] == "unknown"
    assert META["13"]["channels"]["Appliance5"]["name"] == "unknown"
    assert not any("?" in c["name"] for i in META.values() for c in i["channels"].values())


def test_unknown_brand_and_model_are_null():
    c = META["5"]["channels"]["Appliance2"]
    assert (c["brand"], c["model"]) == (None, None)
    assert META["5"]["channels"]["Appliance1"]["brand"] == "Fisher & Paykel"


def test_note_extracted_and_model_joined():
    c5 = META["5"]["channels"]["Appliance5"]
    assert c5["name"] == "Desktop Computer" and c5["note"] == "change 17 Mar 2015"
    c18 = META["18"]["channels"]["Appliance1"]
    assert (c18["name"], c18["brand"], c18["model"], c18["note"]) == (
        "Fridge", "LEC", "R 403W", "garage",
    )


def test_household_information_parsed():
    h16 = META["16"]
    assert h16["occupancy"] == 6
    assert (h16["type"], h16["size"]) == ("Detached", "5 bed")
    assert META["1"]["construction"] == "1975-1980" and META["1"]["appliances_owned"] == 35


def test_no_stray_whitespace():
    for info in META.values():
        for c in info["channels"].values():
            for v in c.values():
                assert v is None or (v == v.strip() and "\t" not in v and "  " not in v)
