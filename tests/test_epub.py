import zipfile

from story.epub_reader import read_epub, split_scenes


def make_epub(path):
    body = lambda title, n: f"<html><body><h1>{title}</h1>" + "".join(f"<p>Paragraph {i} " + "word " * 40 + "</p>" for i in range(n)) + "</body></html>"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
                   '<item id="cover" href="cover.xhtml"/><item id="a" href="ch%201.xhtml"/><item id="b" href="ch2.xhtml"/></manifest>'
                   '<spine><itemref idref="cover"/><itemref idref="b"/><itemref idref="a"/></spine></package>')
        z.writestr("OEBPS/cover.xhtml", "<html><body><p>Cover</p></body></html>")
        z.writestr("OEBPS/ch 1.xhtml", body("First", 10))
        z.writestr("OEBPS/ch2.xhtml", body("Second", 10))


def test_spine_order_and_front_matter_skipped(tmp_path):
    p = tmp_path / "t.epub"
    make_epub(p)
    ch = read_epub(str(p))
    assert [c.title for c in ch] == ["Second", "First"]   # spine order, cover dropped, %20 href resolved
    assert "Paragraph 3" in ch[0].text and "<p>" not in ch[0].text


def test_split_scenes_respects_limit():
    text = "\n\n".join("x" * 1000 for _ in range(10))
    scenes = split_scenes(text, max_chars=2500)
    assert len(scenes) > 1 and all(len(s) <= 3100 for s in scenes)


def test_matter_filter_and_epigraph():
    from story.clean import matter_reason, split_epigraph
    assert matter_reason("ABOUT THE AUTHOR", "x")
    assert matter_reason("Section 3", "CONTENTS\n\nBook I")
    assert matter_reason("Section 9", "It was a relief globe.") is None
    epi, body = split_epigraph("Empires do not suffer.\n\n—WORDS OF X\n\nBY PRINCESS Y\n\nAlia peered down.")
    assert epi.endswith("BY PRINCESS Y") and body == "Alia peered down."
    assert split_epigraph("No quote here.\n\nMore.") == ("", "No quote here.\n\nMore.")


def test_verse_epigraph_and_publisher_page():
    from story.clean import matter_reason, split_epigraph
    verse = "\n\n".join(["Short line"] * 7) + "\n\n—FROM “SONGS”\n\nBY THE PRINCESS\n\nLeto stood."
    epi, body = split_epigraph(verse)
    assert epi.endswith("BY THE PRINCESS") and body == "Leto stood."
    assert matter_reason("Section 3", "ACE\n\nPublished by Berkley")


def make_structured_epub(path):
    words = "word " * 80
    page = lambda body: f"<html><body>{body}</body></html>"
    files = {
        "praise.xhtml": page(f"<p>Praise {words}</p>"),
        "part1.xhtml": page("<h1>Book One</h1>"),
        "ch1.xhtml": page('<div class="block"><p class="nonindent">A beginning is delicate.</p>'
                          '<p class="center01">—FROM “MANUAL”<br/>BY THE PRINCESS</p></div>'
                          f'<p class="indent">Scene one {words}</p><p class="x04-Space-Break"></p>'
                          f'<p class="indent">Scene two {words}</p>'),
        "ch1b.xhtml": page(f'<p class="indent">Continued {words}</p>'),
        "excerpt.xhtml": page(f'<p class="x05-Head-A">The following is from a journal.</p><p>Journal {words}</p>'),
        "ch2.xhtml": page('<p class="x03-Chapter-Epigraph">Quote two.</p>'
                          '<p class="x03-Chapter-Epigraph-Source">—SAYINGS</p>'
                          '<p class="x03-Chapter-Epigraph-Source-2L">BY SOMEONE</p>'
                          f'<p class="x03-CO-Body-Text">Body two {words}</p>'),
        "about.xhtml": page(f"<p>About the author {words}</p>"),
    }
    order = list(files)
    nav = ('<html xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol>'
           '<li><a href="praise.xhtml">Praise</a></li><li><a href="part1.xhtml">Book One: Start</a></li>'
           '<li><a href="ch1.xhtml">Chapter 01</a></li><li><a href="ch2.xhtml">Chapter 02</a></li>'
           '<li><a href="about.xhtml">About the Author</a></li></ol></nav>'
           '<nav epub:type="page-list"><ol><li><a href="ch1.xhtml#p1">1</a></li></ol></nav></body></html>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        items = "".join(f'<item id="i{i}" href="{n}"/>' for i, n in enumerate(order))
        spine = "".join(f'<itemref idref="i{i}"/>' for i in range(len(order)))
        z.writestr("OEBPS/content.opf", '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
                   f'<item id="nav" href="nav.xhtml" properties="nav"/>{items}</manifest><spine>{spine}</spine></package>')
        z.writestr("OEBPS/nav.xhtml", nav)
        for n, body in files.items():
            z.writestr(f"OEBPS/{n}", body)


def test_read_book_uses_toc_and_epigraph_classes(tmp_path):
    from story.epub_reader import read_book
    p = tmp_path / "s.epub"
    make_structured_epub(p)
    ch = read_book(str(p))
    assert [c.title for c in ch] == ["Chapter 01", "Interlude", "Chapter 02"]   # praise/about dropped
    c1, inter, c2 = ch
    assert c1.part == "Book One: Start"
    assert c1.epigraph.startswith("A beginning") and c1.source == "FROM “MANUAL” BY THE PRINCESS"
    assert len(c1.scenes) == 2 and "Continued" in c1.scenes[1]          # scene break + continuation file merged
    assert inter.text.startswith("The following is from a journal.") and not inter.epigraph
    assert c2.epigraph == "Quote two.\n\n—SAYINGS\n\nBY SOMEONE" and c2.source == "SAYINGS BY SOMEONE"
    assert c2.text.startswith("Body two")
