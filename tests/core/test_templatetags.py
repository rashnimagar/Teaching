from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory

from apps.core.templatetags.core_tags import initial_grapheme

User = get_user_model()


class TestInitialGrapheme:
    def test_nepali_names_and_conjuncts(self):
        # Whole syllables and conjuncts must not be split
        assert initial_grapheme("राम") == "रा"
        assert initial_grapheme("क्षत्रिय") == "क्ष"
        assert initial_grapheme("ज्ञान") == "ज्ञा"
        assert initial_grapheme("प्रदीप") == "प्र"
        assert initial_grapheme("अधिकारी") == "अ"
        assert initial_grapheme("नेपाली") == "ने"
        assert initial_grapheme("ऋषि") == "ऋ"

    def test_latin_names_and_titles(self):
        assert initial_grapheme("Python") == "P"
        assert initial_grapheme("django") == "D"
        assert initial_grapheme("alexander") == "A"
        assert initial_grapheme("100 Days of Code") == "1"

    def test_whitespace_and_empty_inputs(self):
        assert initial_grapheme("") == ""
        assert initial_grapheme("   ") == ""
        assert initial_grapheme(None) == ""
        assert initial_grapheme("  राम  ") == "रा"
        assert initial_grapheme("  django  ") == "D"

    def test_symbols_and_emoji_fallback_to_empty(self):
        # Non-alphanumeric symbols return empty string to trigger icon fallback
        assert initial_grapheme("---") == ""
        assert initial_grapheme("!Important") == ""
        assert initial_grapheme("🎓 Masterclass") == ""

    def test_user_object_with_name_or_email(self):
        u1 = User(first_name="रोशन", last_name="श्रेष्ठ", email="roshan@example.com")
        assert initial_grapheme(u1) == "रो"

        u2 = User(first_name="", last_name="", email="student@example.com")
        assert initial_grapheme(u2) == "S"

        u3 = User(first_name="Bikash", last_name="Thapa", email="b@example.com")
        assert initial_grapheme(u3) == "B"


class TestUrlReplaceTag:
    def test_url_replace_preserves_and_updates_query_params(self, rf: RequestFactory):
        request = rf.get("/courses/?q=python&filter=free&page=1")
        template = Template("{% load core_tags %}?{% url_replace page=2 %}")
        rendered = template.render(Context({"request": request}))
        assert "page=2" in rendered
        assert "q=python" in rendered
        assert "filter=free" in rendered

    def test_url_replace_removes_param_when_none(self, rf: RequestFactory):
        request = rf.get("/courses/?q=python&page=2")
        template = Template("{% load core_tags %}?{% url_replace page=None filter='all' %}")
        rendered = template.render(Context({"request": request}))
        assert "page=" not in rendered
        assert "filter=all" in rendered
        assert "q=python" in rendered
