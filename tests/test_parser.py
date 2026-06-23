from pathlib import Path

from derja_scraper.parser import parse_search_results


FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_arabic_search_result_with_audio_regions():
    records = parse_search_results(
        read_fixture("search_results_arabic.html"),
        query="برشا",
        script="arabic",
    )

    assert len(records) == 1
    record = records[0]
    assert record["query"] == "برشا"
    assert record["script"] == "arabic"
    assert record["rank"] == 1
    assert record["entry_id"] == "619bce92-f587-4fbe-816b-25943d024d4c"
    assert record["entry_url"] == "https://derja.ninja/e/619bce92-f587-4fbe-816b-25943d024d4c"
    assert record["term_arabic"] == "حلم برشا"
    assert record["term_transliteration"] == "7lim barcha"
    assert record["definition_english"] == "he dreamt alot"
    assert record["example_sentence_english"] == "When he was little he dreamt a lot."
    assert record["example_sentence_arabic"] == "كيف كان صغير كان يحلم برشا"
    assert record["example_sentence_transliteration"] == "kyf kn sghyr kn y7lm brch"
    assert record["audio"]["source_url"] == "https://static.derjaninja.com/recordings/2121.mp3"
    assert record["audio"]["regions"]["term"] == {
        "start": 3.88577010291296,
        "end": 4.88577010291296,
    }
    assert record["audio"]["regions"]["sentence"] == {
        "start": 10.002604379747236,
        "end": 15.42754832469118,
    }
    assert record["audio"]["clips"] == {}


def test_parse_no_results_page_returns_empty_list():
    records = parse_search_results(
        read_fixture("no_results.html"),
        query="أنا نحبك",
        script="arabic",
    )

    assert records == []


def test_parse_result_without_audio_keeps_text_fields_and_empty_audio():
    records = parse_search_results(
        read_fixture("missing_audio.html"),
        query="كلمة",
        script="arabic",
    )

    assert len(records) == 1
    assert records[0]["term_arabic"] == "كلمة"
    assert records[0]["audio"] == {
        "source_url": None,
        "regions": {},
        "clips": {},
    }
