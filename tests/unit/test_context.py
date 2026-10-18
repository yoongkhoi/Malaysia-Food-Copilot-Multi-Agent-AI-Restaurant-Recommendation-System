from food_copilot.agents.context import apply_history, web_query


def test_follow_up_keeps_the_previous_area_and_skips_shown_names():
    history = [
        {"role": "user", "content": "I want Korean BBQ around Old Klang Road."},
        {"role": "assistant", "content": "- Sae Ma Eul BBQ: price unknown\n- Oiso: price unknown"},
    ]
    text, skipped = apply_history("还有没有其他的推荐", history)
    assert "Old Klang Road" in text
    assert "korean" in text
    assert skipped == ["Sae Ma Eul BBQ", "Oiso"]


def test_a_new_area_is_not_overwritten():
    history = [{"role": "user", "content": "Korean BBQ around Old Klang Road"}]
    text, skipped = apply_history("Find a Japanese restaurant in Kuala Lumpur", history)
    assert text.startswith("Find a Japanese")
    assert skipped == []


def test_context_alone_keeps_korean_and_old_klang_road():
    text, skipped = apply_history(
        "还有没有其他的推荐",
        [],
        {"region": "old_klang_road", "cuisine": "korean", "shown_names": ["Sae Ma Eul BBQ"]},
    )
    assert "Old Klang Road" in text
    assert "korean" in text
    assert skipped == ["Sae Ma Eul BBQ"]


def test_japanese_follow_up_keeps_the_area_and_changes_cuisine():
    text, skipped = apply_history(
        "What about Japanese food?",
        [{"role": "user", "content": "I want Korean BBQ around Old Klang Road."}],
    )
    assert "Old Klang Road" in text
    assert "Japanese" in text
    assert "korean" not in text.lower()
    assert skipped == []


def test_kuala_lumpur_cafe_replaces_both_conditions():
    text, _skipped = apply_history(
        "Show me cafes in Kuala Lumpur instead.",
        [{"role": "user", "content": "I want Korean BBQ around Old Klang Road."}],
    )
    assert "Kuala Lumpur" in text
    assert "Old Klang Road" not in text
    parsed = __import__("food_copilot.retrieval.constraints", fromlist=["parse_constraints"]).parse_constraints(text)
    assert parsed.region == "kuala_lumpur"
    assert parsed.cuisine == "cafe"


def test_a_named_cuisine_drops_a_saved_brand():
    text, skipped = apply_history(
        "any recommendation for korean food?",
        [{"role": "user", "content": "how many kfc are there in old klang road"}],
        {"region": "old_klang_road", "name_contains": "kfc", "shown_names": ["KFC"]},
    )
    assert "Old Klang Road" in text
    assert "korean" in text.lower()
    assert "kfc" not in text.lower()
    assert skipped == []


def test_web_query_names_the_cuisine_and_road():
    assert web_query({"cuisine": "korean", "region": "old_klang_road"}) == "korean restaurant Old Klang Road Kuala Lumpur"
