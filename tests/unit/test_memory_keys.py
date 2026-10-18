from food_copilot.memory.store import session_key


def test_session_key_is_scoped():
    assert session_key("abc") == "session:abc:messages"
    assert "user" not in session_key("abc")
