import silence


def test_the_middle_of_a_long_silence_is_cut_and_a_short_one_stays():
    keep = [[0.0, 20.0]]
    got = silence.cut_silences(keep, [[5.0, 7.0], [10.0, 10.4]], 0.5, 0.15)
    assert got == [[0.0, 5.15], [6.85, 20.0]]                     # 0.3 s of the 2 s silence is left; the 0.4 s one is not touched


def test_a_silence_outside_the_kept_ranges_changes_nothing():
    assert silence.cut_silences([[0.0, 4.0]], [[6.0, 9.0]], 0.5, 0.15) == [[0.0, 4.0]]


def test_the_silence_at_the_start_of_a_range_is_trimmed():
    assert silence.cut_silences([[0.0, 10.0]], [[0.0, 2.0]], 0.5, 0.15) == [[1.85, 10.0]]


def test_more_of_a_silence_stays_after_the_speech_than_before_the_next_word():
    assert silence.cut_silences([[0.0, 20.0]], [[5.0, 7.0]], 0.5, 0.3, 0.1) == [[0.0, 5.3], [6.9, 20.0]]


def test_a_cut_never_lands_inside_a_word():
    words = [["me", 4.8, 5.6], ["so", 7.0, 7.2]]                    # the quiet end of "me" is called silence from 5.0, the next word starts at 7.0
    got = silence.cut_silences([[0.0, 20.0]], [[5.0, 7.2]], 0.5, 0.15, 0.1, words)
    assert got[0][1] >= 5.02 and got[1][0] <= 6.96                  # "me" keeps its likely length (0.12 s + 0.05 s a letter), the next word is not clipped
