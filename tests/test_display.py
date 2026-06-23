from derja_scraper.display import rtl_input_line, terminal_text


def test_terminal_text_shapes_arabic_for_ltr_terminal_display():
    raw = "\u0628\u0631\u0634\u0627"

    assert terminal_text(raw) == "\ufe8e\ufeb7\ufeae\ufe91"


def test_terminal_text_leaves_latin_text_unchanged():
    assert terminal_text("hello") == "hello"


def test_rtl_input_line_renders_current_buffer_for_terminal_echo():
    assert rtl_input_line("Word or sentence", "\u0633\u0644\u0627\u0645") == (
        "Word or sentence: \ufee1\ufefc\ufeb3"
    )
