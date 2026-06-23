from __future__ import annotations

import re

import arabic_reshaper
from bidi.algorithm import get_display


ARABIC_RE = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")


def terminal_text(value: object) -> str:
    text = str(value)
    if not ARABIC_RE.search(text):
        return text
    return get_display(arabic_reshaper.reshape(text))


def rtl_input_line(prompt: str, value: str) -> str:
    return f"{prompt}: {terminal_text(value)}"
