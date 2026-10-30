import sections


def test_a_cutaway_runs_on_over_the_jump_cut_inside_a_beat():
    keep = [[0.0, 6.0], [10.0, 20.0]]                         # two pieces: 6 s and 10 s
    got = sections._broll_pieces("B05", keep, 4.0, 6.0, 100.0)
    assert got == [("B05", 4.0, 2.0, 100.0), ("B05.2", 0.0, 4.0, 102.0)]       # the picture goes on from where it was


def test_a_cutaway_inside_one_piece_is_left_alone():
    assert sections._broll_pieces("B01", [[0.0, 20.0]], 3.0, 5.0, 10.0) == [("B01", 3.0, 5.0, 10.0)]
