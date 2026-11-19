from app.modules.copilot.services.privacy import redact


def test_personal_data_is_replaced_before_anyone_reads_it():
    text, found = redact(
        "Gọi mình 0912 345 678 hoặc +84 28 3822 1234, mail an.nguyen@gmail.com. CCCD 001203004567,"
        " CMND: 123456789, STK 0011 0045 6789 tại VCB, thẻ 4111 1111 1111 1111.",
        "vi",
    )
    assert text == (
        "Gọi mình [số điện thoại] hoặc [số điện thoại], mail [email]. CCCD [số giấy tờ],"
        " CMND: [số giấy tờ], STK [số tài khoản] tại VCB, thẻ [số thẻ]."
    )
    assert found == ["account", "card", "email", "id", "phone"]


def test_energy_numbers_are_left_alone():
    for question in [
        "Tháng này dùng 1.250.000 đ, 212,5 kWh, bậc 4 từ 201 đến 300 số.",
        "Hóa đơn 1234567890123 có đúng không?",  # 13 digits failing Luhn: a bill code, not a card
        "So sánh 19/11/2026 với 0 giờ hôm qua, công tơ 123456789.",
    ]:
        assert redact(question, "vi") == (question, [])


def test_labels_follow_the_language():
    assert redact("call 0987654321", "en") == ("call [phone number]", ["phone"])
