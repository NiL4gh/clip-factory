import os
import pytest
from PIL import Image, ImageDraw
from shorts_generator import overlays

FONT = os.path.join(os.path.dirname(__file__), "..", "shorts_generator", "assets", "BebasNeue-Regular.ttf")

def test_fit_lines_short_text_one_line():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    lines, font = overlays.fit_lines(draw, "RCMP CALL", FONT, max_w=960, max_h=240)
    assert lines == ["RCMP CALL"]
    assert font.size <= overlays.MAX_FONT

def test_fit_lines_long_text_wraps_to_two_and_fits():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    text = "YOUR FRIEND'S FIRE IS OUT OF CONTROL"
    lines, font = overlays.fit_lines(draw, text, FONT, max_w=960, max_h=240)
    assert 1 <= len(lines) <= 2
    for ln in lines:
        w = draw.textbbox((0, 0), ln, font=font, stroke_width=12)[2]
        assert w <= 960            # never overflows the safe width
    assert font.size >= overlays.MIN_FONT

def test_fit_lines_respects_min_font_floor():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    # Very long header — would normally shrink small; floor at 52.
    text = "THE ONE MONEY RULE NOBODY EVER TELLS YOU ABOUT"
    lines, font = overlays.fit_lines(draw, text, FONT, max_w=960, max_h=240,
                                     min_font_size=52)
    assert font.size >= 52

# ── preset registry + keyword picker ──────────────────────────────────────────

def test_presets_exist():
    assert set(overlays.HEADER_PRESETS) == {"card", "stroke"}
    for p in overlays.HEADER_PRESETS.values():
        assert {"container", "text", "keyword"} <= set(p)

def test_pick_keyword_prefers_trigger_word():
    # "SECRET" is a trigger word -> it should be the accent index
    words = ["DAD'S", "FIRECRACKER", "SECRET"]
    assert overlays.pick_keyword(words) == 2

def test_pick_keyword_falls_back_to_last_word():
    words = ["PARENTS", "ARE", "CRAZY"]
    assert overlays.pick_keyword(words) == 2

# ── render PNG per preset ─────────────────────────────────────────────────────

@pytest.mark.parametrize("preset", ["card", "stroke"])
def test_render_overlay_png(tmp_path, preset):
    out = str(tmp_path / f"{preset}.png")
    p = overlays.render_overlay_png("PARENTS ARE CRAZY", preset, FONT, out_path=out)
    assert p == out
    im = Image.open(out)
    assert im.mode == "RGBA"
    assert im.size == (overlays.ZONE_W, overlays.ZONE_H)
    # something was actually drawn (alpha not fully zero)
    assert im.getextrema()[3][1] > 0

def test_render_overlay_long_text_does_not_raise(tmp_path):
    out = str(tmp_path / "long.png")
    overlays.render_overlay_png("YOUR FRIEND'S FIRE IS OUT OF CONTROL", "card", FONT, out_path=out)
    assert Image.open(out).size == (overlays.ZONE_W, overlays.ZONE_H)

def test_card_text_stays_opaque_when_background_is_transparent(tmp_path):
    # With opacity=0.5 the card box should be semi-transparent, but the
    # text must still reach full alpha (255). Before the fix the whole
    # layer was multiplied, so max alpha capped near 127.
    out = str(tmp_path / "hook.png")
    overlays.render_overlay_png("PARENTS ARE CRAZY", "card", FONT,
                                out_path=out, opacity=0.5)
    im = Image.open(out)
    max_alpha = im.getextrema()[3][1]
    assert max_alpha == 255


# ── casing option ─────────────────────────────────────────────────────────────

def test_fit_lines_defaults_to_upper():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    lines, _font = overlays.fit_lines(draw, "stay hungry", FONT)
    assert " ".join(lines) == "STAY HUNGRY"


def test_fit_lines_title_case():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    lines, _font = overlays.fit_lines(draw, "when you surprise your girlfriend",
                                      FONT, casing="title")
    assert " ".join(lines) == "When You Surprise Your Girlfriend"


def test_fit_lines_title_case_keeps_apostrophes():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    lines, _font = overlays.fit_lines(draw, "don't quit your job", FONT,
                                      casing="title")
    assert " ".join(lines) == "Don't Quit Your Job"
