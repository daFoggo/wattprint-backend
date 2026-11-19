from app.modules.copilot.services.voice import frames, pieces, spoken


def test_an_answer_is_written_as_it_is_read():
    text = (
        "**Tủ lạnh** tốn nhất [1]: 85,2 kWh, khoảng 1.248.000 đ (~1,2 triệu), lúc 21:30 và 06:00.\n"
        "- Giá 2.927đ/kWh, điều hòa 1.200W. Xem [hóa đơn](/dashboard/bill) ngày 19/11."
    )
    assert spoken(text, "vi") == (
        "Tủ lạnh tốn nhất: 85,2 ki lô oát giờ, khoảng 1248000 đồng (khoảng 1,2 triệu), "
        "lúc 21 giờ 30 và 6 giờ.\nGiá 2927 đồng mỗi ki lô oát giờ, điều hòa 1200 oát. "
        "Xem hóa đơn ngày 19/11."
    )
    assert spoken("Used 1,250.5 kWh, 1,250,000₫ at 8:30.", "en") == (
        "Used 1250.5 kilowatt hours, 1250000 dong at 8:30."
    )


def test_pieces_are_whole_sentences_the_first_one_short():
    text = "Một câu đầu khá dài để Wappi đọc ngay cho bạn. Hai.\nBa: x\nBốn. " + "Dài. " * 200
    out = pieces(text)
    assert out[0] == "Một câu đầu khá dài để Wappi đọc ngay cho bạn."
    assert out[1].startswith("Hai. Ba: x. Bốn.")  # a list line ends with a pause
    assert all(len(p) <= 300 for p in out[1:])
    assert sum(map(len, out)) <= 1500 + len(out)


def test_frames_drop_the_tags_that_would_cut_a_joined_stream():
    # ID3v2 tag of 5 bytes, a Xing frame (MPEG-2 Layer III, 128 kbps, 24 kHz: 384 bytes), audio.
    tag = b"ID3\x04\x00\x00\x00\x00\x00\x05" + b"x" * 5
    header = bytes([0xFF, 0xF3, 0xC4, 0xC4])
    xing = header + b"\x00" * 17 + b"Info" + b"\x00" * (384 - 25)
    audio = header + b"a" * 380
    assert frames(tag + xing + audio) == audio
    assert frames(audio) == audio
    assert frames(b"not mp3") == b"not mp3"
