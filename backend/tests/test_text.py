"""Text from outside, made storable."""

from frontdesk.domain.text import storable, storable_json


def test_what_postgres_cannot_store_is_removed() -> None:
    assert storable("Oi\x00, Ana!\x08") == "Oi, Ana!"


def test_line_breaks_tabs_accents_and_symbols_are_kept() -> None:
    kept = "Corte às 14h:\n\tR$ 45,00 😊 até 10\u202fminutos"

    assert storable(kept) == kept


def test_text_inside_a_document_is_cleaned_at_any_depth() -> None:
    raw = {"te\x00xt": ["a\x00b", {"body": "c\x00", "count": 1, "none": None, "ok": True}]}

    assert storable_json(raw) == {
        "text": ["ab", {"body": "c", "count": 1, "none": None, "ok": True}]
    }
