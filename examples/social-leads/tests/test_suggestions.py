"""The project follows Karni's patterns: `karni check` has no suggestion for it."""


def test_karni_has_no_suggestion_for_this_project():
    from karni import suggestions

    assert [item.as_dict() for item in suggestions.detect()] == []
