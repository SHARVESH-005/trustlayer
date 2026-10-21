from trustlayer.badge import render


def test_badge_colours_follow_score():
    assert "#1a7f37" in render(98, "ok")
    assert "#bf8700" in render(70, "ok")
    assert "#cf222e" in render(40, "ok")
    assert "unknown" in render(None, "not monitored")


def test_badge_escapes_detail():
    assert "<script>" not in render(50, "<script>")
