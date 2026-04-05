from ads_copilot.reporters.email import _markdown_to_html


def test_renders_h1_and_h2() -> None:
    html = _markdown_to_html("# Report\n## Spend")
    assert "<h1>Report</h1>" in html
    assert "<h2>Spend</h2>" in html


def test_renders_table() -> None:
    md = "| Platform | Cost |\n|---|---:|\n| google | 100 |"
    html = _markdown_to_html(md)
    assert "<table" in html
    assert "<td>google</td>" in html
    assert "<td>100</td>" in html
    assert "</table>" in html


def test_bold_rendered() -> None:
    html = _markdown_to_html("some **important** thing")
    assert "<strong>important</strong>" in html


def test_code_rendered() -> None:
    html = _markdown_to_html("use `foo` here")
    assert "<code>foo</code>" in html


def test_list_bullets() -> None:
    html = _markdown_to_html("- item one\n- item two")
    assert "• item one" in html
    assert "• item two" in html


def test_html_escaped() -> None:
    html = _markdown_to_html("<script>alert(1)</script>")
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
