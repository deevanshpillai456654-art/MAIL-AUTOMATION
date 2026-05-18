from html.parser import HTMLParser
from pathlib import Path


class SelectNameParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.label_depth = 0
        self.violations = []

    def handle_starttag(self, tag, attrs):
        attrs_map = dict(attrs)
        if tag == "label":
            self.label_depth += 1
        if tag == "select":
            has_name = any(
                attrs_map.get(attr)
                for attr in ("aria-label", "aria-labelledby", "title")
            )
            if not has_name and self.label_depth == 0:
                self.violations.append((self.getpos()[0], attrs_map.get("id") or attrs_map.get("name") or "<unknown>"))

    def handle_endtag(self, tag):
        if tag == "label" and self.label_depth:
            self.label_depth -= 1


def test_dashboard_selects_have_accessible_names():
    parser = SelectNameParser()
    parser.feed(Path("backend/dashboard/index.html").read_text("utf-8"))

    assert parser.violations == []
