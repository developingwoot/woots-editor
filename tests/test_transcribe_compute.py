import transcribe


def test_a_small_card_holds_whisper_in_8_bit_and_a_big_one_in_float16():
    assert transcribe.compute_type("cuda", 4.0) == "int8_float16"
    assert transcribe.compute_type("cuda", 8.0) == "float16" and transcribe.compute_type("cuda", 24.0) == "float16"
    assert transcribe.compute_type("cpu", 0) == "int8"
