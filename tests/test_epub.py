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
