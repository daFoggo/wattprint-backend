from scripts.import_refit_weather import SITE, site_of


def test_a_home_without_a_site_uses_the_refit_site_on_utc():
    assert site_of({"house": 2}) == {**SITE, "timezone": "UTC"}


def test_a_home_with_a_site_gets_its_own_place_and_clock():
    home = {
        "house": 101,
        "site": {"latitude": 37.98, "longitude": 23.73, "timezone": "Europe/Athens"},
    }
    assert site_of(home) == {"latitude": 37.98, "longitude": 23.73, "timezone": "Europe/Athens"}
