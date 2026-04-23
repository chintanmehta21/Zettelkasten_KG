from pathlib import Path

from ops.scripts.lib.links_parser import parse_links_file


def test_parse_section_headered(tmp_path: Path):
    links = tmp_path / "links.txt"
    links.write_text(
        "# YouTube\nhttps://youtube.com/a\nhttps://youtube.com/b\n\n"
        "# Reddit\nhttps://reddit.com/r/x/comments/1\n",
        encoding="utf-8",
    )

    result = parse_links_file(links)

    assert result["youtube"] == ["https://youtube.com/a", "https://youtube.com/b"]
    assert result["reddit"] == ["https://reddit.com/r/x/comments/1"]


def test_parse_ignores_comments_and_blanks(tmp_path: Path):
    links = tmp_path / "links.txt"
    links.write_text("# YouTube\n# a comment\nhttps://yt.com/a\n\n", encoding="utf-8")

    assert parse_links_file(links)["youtube"] == ["https://yt.com/a"]
