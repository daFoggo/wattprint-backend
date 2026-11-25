from app.modules.nilm.services.devices import DEVICE_TYPES


def test_the_new_homes_labels_map_to_catalog_types():
    assert DEVICE_TYPES["AC"] == "ac"
    assert DEVICE_TYPES["Boiler"] == "water_heater"
    assert DEVICE_TYPES["Kimchi"] == "fridge"
    assert DEVICE_TYPES["RiceCooker"] == "rice_cooker"
