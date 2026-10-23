"""Executable claims for the book renderer; fixtures never leave .temp/."""
import copy
import hashlib
import importlib.machinery
import importlib.util
import inspect
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("book", str(ROOT / "scripts/platform_book.py"))
spec = importlib.util.spec_from_loader(loader.name, loader)
book = importlib.util.module_from_spec(spec)
loader.exec_module(book)


class BookTests(unittest.TestCase):
    def setUp(self):
        (ROOT / ".temp").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / ".temp", prefix="book-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.book = self.root / "book"
        book.scaffold(self.book, "en")
        self.chapter = self.book / "en/00-introduction.md"

    def manifest(self):
        return json.loads((self.book / "src/figures.json").read_text())

    def write_manifest(self, manifest):
        (self.book / "src/figures.json").write_text(json.dumps(manifest))

    def reject(self, message):
        with self.assertRaisesRegex(book.Refusal, message):
            book.check_figures(self.book)

    # Claim: both language scaffolds are complete; an existing destination and
    # its bytes survive a refused second scaffold.
    def test_scaffold_languages_and_no_overwrite(self):
        book.check_figures(self.book)
        original = self.chapter.read_bytes()
        with self.assertRaisesRegex(book.Refusal, "destination already exists"):
            book.scaffold(self.book, "ru")
        self.assertEqual(self.chapter.read_bytes(), original)
        russian = self.root / "russian"
        book.scaffold(russian, "ru")
        config, _ = book.check_figures(russian)
        self.assertEqual(config["language"], "ru")
        self.assertFalse((russian / "en").exists())

    # Claim: readiness accepts the pinned local environment and detects absent
    # tools, tool/parser version drift and a modified font before rendering.
    def test_readiness_gates(self):
        book.readiness()
        with patch.object(book.sys, "prefix", "/invented/other-python"):
            with self.assertRaisesRegex(book.Refusal, "outside the activated VIRTUAL_ENV"):
                book.readiness()
        with patch.object(book.sys, "version", "0.0.0"):
            with self.assertRaisesRegex(book.Refusal, "Python version differs"):
                book.readiness()
        with patch.object(book.shutil, "which", return_value=None):
            with self.assertRaisesRegex(book.Refusal, "missing tool: pandoc"):
                book.readiness()
        with patch.object(book, "run", return_value=("pandoc 0.0\n", "")):
            with self.assertRaisesRegex(book.Refusal, "pandoc version differs"):
                book.readiness()
        with patch.object(book.importlib.metadata, "version", return_value="0.0"):
            with self.assertRaisesRegex(book.Refusal, "pypdf version differs"):
                book.readiness()
        with patch.object(book.importlib.metadata, "version", side_effect=book.importlib.metadata.PackageNotFoundError):
            with self.assertRaisesRegex(book.Refusal, "missing pinned Python dependency"):
                book.readiness()
        real_version = book.importlib.metadata.version
        with patch.object(book.importlib.metadata, "version",
                          side_effect=lambda name: "0.0" if name == "weasyprint" else real_version(name)):
            with self.assertRaisesRegex(book.Refusal, "weasyprint version differs"):
                book.readiness()
        assets = self.root / "assets"
        shutil.copytree(book.ASSETS, assets)
        (assets / "fonts/PTM55FT.ttf").write_bytes(b"changed")
        with patch.object(book, "ASSETS", assets):
            with self.assertRaisesRegex(book.Refusal, "modified bundled font"):
                book.readiness()

    # Claim: settings accept a real chapter list and boolean contents switch,
    # and reject unsupported languages, nonboolean switches and absent chapters.
    def test_settings_gates(self):
        config = self.book / "book.json"
        config.write_text(json.dumps({"language": "en", "toc": True}))
        self.assertTrue(book.settings(self.book)[0]["toc"])
        for value, message in [({"language": "fr", "toc": True}, "language must be en or ru"),
                               ({"language": "en", "toc": "yes"}, "toc must be boolean")]:
            config.write_text(json.dumps(value))
            with self.assertRaisesRegex(book.Refusal, message):
                book.settings(self.book)
        config.write_text(json.dumps({"language": "en", "toc": False}))
        self.chapter.unlink()
        with self.assertRaisesRegex(book.Refusal, "no numbered chapters"):
            book.settings(self.book)

    # Claim: Pandoc AST validation covers reference-style images and attributes,
    # and refuses missing, undeclared, escaped and remote image targets.
    def test_image_syntax_and_targets(self):
        text = self.chapter.read_text()
        self.chapter.write_text(text.replace("![From a note to an explanation](../diagrams/reading-flow.svg)",
                                             "![A caption][flow]{.tall}\n\n[flow]: ../diagrams/reading-flow.svg"))
        book.check_figures(self.book)
        for target, message in [("../diagrams/missing.svg", "absent from figure manifest"),
                                ("https://example.org/image.svg", "local ../diagrams/"),
                                ("../../outside.svg", "local ../diagrams/")]:
            with self.subTest(target=target):
                self.chapter.write_text(text.replace("../diagrams/reading-flow.svg", target))
                self.reject(message)
        self.chapter.write_text(text)
        (self.book / "diagrams/reading-flow.svg").unlink()
        self.reject("missing figure file")

    # Claim: source and render drift, undeclared files, unsafe manifest paths,
    # extra record fields and symlinked inputs fail with specific verdicts.
    def test_provenance_and_path_gates(self):
        original = self.manifest()
        for kind in ("source", "render"):
            manifest = copy.deepcopy(original)
            manifest["reading-flow"][kind + "_sha256"] = "0" * 64
            self.write_manifest(manifest)
            self.reject(f"figure {kind} hash mismatch")
        manifest = copy.deepcopy(original)
        manifest["reading-flow"]["source"] = "../outside.svg"
        self.write_manifest(manifest); self.reject("figure path escapes")
        manifest = copy.deepcopy(original)
        manifest["reading-flow"]["extra"] = True
        self.write_manifest(manifest); self.reject("invalid figure record")
        self.write_manifest(original)
        orphan = self.book / "src/orphan.svg"
        orphan.write_text("<svg/>")
        self.reject("orphan figure"); orphan.unlink()
        render = self.book / "diagrams/reading-flow.svg"
        render.unlink(); render.symlink_to(self.book / "src/reading-flow.svg")
        self.reject("figure symlink forbidden"); render.unlink()
        shutil.copy2(self.book / "src/reading-flow.svg", render)
        self.chapter.rename(self.root / "chapter.md")
        self.chapter.symlink_to(self.root / "chapter.md")
        self.reject("chapter symlink forbidden")

    # Claim: a self-contained SVG with local paint servers passes; external
    # SVG resources, executable elements and raw HTML cannot bypass the AST.
    def test_svg_and_raw_resource_gates(self):
        svg = self.root / "control.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><defs id="p"/><path fill="url(\'#p\')"/></svg>')
        book.check_svg(svg)
        for source, message in [
            ('<svg><image href="https://example.org/a.png"/></svg>', "external resource"),
            ('<svg><style>@import "remote.css";</style></svg>', "external resource"),
            ('<svg><path fill="url(file:///missing)"/></svg>', "external resource"),
            ('<svg><script/></svg>', "executable content"),
            ('<!DOCTYPE svg><svg/>', "external declaration")]:
            with self.subTest(source=source):
                svg.write_text(source)
                with self.assertRaisesRegex(book.Refusal, message):
                    book.check_svg(svg)
        self.chapter.write_text(self.chapter.read_text() + '\n<img src="https://example.org/a.png">\n')
        self.reject("raw HTML forbidden")

    def filtered(self, text):
        return subprocess.run(["pandoc", "--from=markdown", "--to=html5",
                               "--lua-filter", str(book.ASSETS / "filters/book.lua")],
                              input=text, text=True, capture_output=True)

    # Claim: English/Russian multiword badges and explicit landscape classes
    # render, while an adjacent unknown complete marker fails; code is literal.
    def test_lua_status_and_figure_controls(self):
        result = self.filtered("⟦working today⟧⟦решено⟧; `⟦literal⟧`\n\n![Figure](flow.svg){.landscape}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('class="status now"', result.stdout)
        self.assertIn('class="status dec"', result.stdout)
        self.assertIn("<code>⟦literal⟧</code>", result.stdout)
        self.assertIn('<figure class="landscape">', result.stdout)
        for text in ("⟦decided⟧⟦unknown⟧", "⟦решено⟧⟦unknown status⟧"):
            result = self.filtered(text)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown status marker:", result.stderr)

    # Claim: the original sample is two pages with all three embedded families;
    # wrong page/family expectations and an unembedded base font are rejected.
    def test_build_and_pdf_negatives(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject
        output = self.root / "sample.pdf"
        self.assertEqual(book.build(self.book, output, 2)["pages"], 2)
        book.check_pdf(output, 2, ("PT Serif", "PT Sans", "PT Mono"))
        with self.assertRaisesRegex(book.Refusal, "page count mismatch"):
            book.check_pdf(output, 3)
        with self.assertRaisesRegex(book.Refusal, "font family missing"):
            book.check_pdf(output, 2, ("Missing Family",))
        writer = PdfWriter(); page = writer.add_blank_page(100, 100)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        bad = self.root / "unembedded.pdf"
        writer.write(bad)
        with self.assertRaisesRegex(book.Refusal, "font descriptor missing"):
            book.check_pdf(bad)
        font[NameObject("/FontDescriptor")] = DictionaryObject()
        writer.write(bad)
        with self.assertRaisesRegex(book.Refusal, "font is not embedded"):
            book.check_pdf(bad)

    # Claim: failed validation or rendering preserves the prior output bytes and
    # leaves no temporary partial PDF; a subsequent valid build replaces it.
    def test_atomic_publication(self):
        output = self.root / "published.pdf"; output.write_bytes(b"previous output")
        def failed_renderer(book_dir, language, html, pdf):
            pdf.write_bytes(b"partial")
            raise book.Refusal("renderer failed control")
        with patch.object(book, "render_pdf", side_effect=failed_renderer):
            with self.assertRaisesRegex(book.Refusal, "renderer failed control"):
                book.build(self.book, output, 2)
        self.assertEqual(output.read_bytes(), b"previous output")
        self.assertFalse(list(self.root.glob(".platform-book-*")))
        (self.book / "diagrams/reading-flow.svg").unlink()
        with self.assertRaisesRegex(book.Refusal, "missing figure file"):
            book.build(self.book, output, 2)
        self.assertEqual(output.read_bytes(), b"previous output")
        shutil.copy2(self.book / "src/reading-flow.svg", self.book / "diagrams/reading-flow.svg")
        book.build(self.book, output, 2)
        self.assertTrue(output.read_bytes().startswith(b"%PDF"))

    # Claim: the negative instrument actually detects known weakened gates.
    # Each bounded mutant narrows just one requirement; the corresponding
    # witness must fail its assertion rather than fail during fixture setup.
    def test_narrowing_mutants(self):
        cases = [
            ("language", "language must be en or ru", "test_settings_gates"),
            ("contents", "toc must be boolean", "test_settings_gates"),
            ("chapters", "no numbered chapters", "test_settings_gates"),
            ("python", "Python version differs", "test_readiness_gates"),
            ("venv-prefix", "Python is outside the activated VIRTUAL_ENV", "test_readiness_gates"),
            ("tool-presence", "missing tool: pandoc", "test_readiness_gates"),
            ("version", "pandoc version differs", "test_readiness_gates"),
            ("parser-version", "pypdf version differs", "test_readiness_gates"),
            ("renderer-version", "weasyprint version differs", "test_readiness_gates"),
            ("font", "modified bundled font", "test_readiness_gates"),
            ("hash", "figure source hash mismatch", "test_provenance_and_path_gates"),
            ("render-hash", "figure render hash mismatch", "test_provenance_and_path_gates"),
            ("path", "figure path escapes", "test_provenance_and_path_gates"),
            ("record", "invalid figure record", "test_provenance_and_path_gates"),
            ("orphan", "orphan figure", "test_provenance_and_path_gates"),
            ("svg", "SVG external resource", "test_svg_and_raw_resource_gates"),
            ("svg-code", "SVG executable content", "test_svg_and_raw_resource_gates"),
            ("svg-declaration", "SVG external declaration", "test_svg_and_raw_resource_gates"),
            ("raw-html", "raw HTML forbidden", "test_svg_and_raw_resource_gates"),
            ("image-target", "image must use a local", "test_image_syntax_and_targets"),
            ("image-manifest", "image absent from figure manifest", "test_image_syntax_and_targets"),
            ("pages", "PDF page count mismatch", "test_build_and_pdf_negatives"),
            ("embedding", "PDF font is not embedded", "test_build_and_pdf_negatives"),
            ("family", "PDF font family missing", "test_build_and_pdf_negatives"),
        ]
        # Recreate fixtures between mutants: setup cannot be the failure witness.
        for name, message, witness in cases:
            with self.subTest(gate=name):
                shutil.rmtree(self.book)
                book.scaffold(self.book, "en")
                original = book.require
                exercised = []
                def weakened(condition, text):
                    if message in text:
                        exercised.append(True)
                        return
                    original(condition, text)
                result = unittest.TestResult()
                with patch.object(book, "require", side_effect=weakened):
                    BookTests(witness).run(result)
                self.assertTrue(result.failures, "mutant survived its witness")
                self.assertFalse(result.errors, "unrelated fixture error is not a kill")
                self.assertTrue(all("Refusal not raised" in detail or "does not match" in detail
                                    for _, detail in result.failures), result.failures)
                self.assertTrue(exercised, "mutant gate was not exercised")

    # Claim: the Lua witness catches accepting unknown adjacent badges, and the
    # publication witness catches writing the renderer's partial PDF live.
    def test_lua_and_atomic_mutants(self):
        assets = self.root / "mutant-assets"
        shutil.copytree(book.ASSETS, assets)
        lua = assets / "filters/book.lua"
        text = lua.read_text()
        plant = 'error("unknown status marker: " .. label)'
        self.assertEqual(text.count(plant), 1)
        lua.write_text(text.replace(plant, "return pandoc.Str(label)"))
        result = unittest.TestResult()
        with patch.object(book, "ASSETS", assets):
            BookTests("test_lua_status_and_figure_controls").run(result)
        self.assertFalse(result.errors)
        self.assertEqual(len(result.failures), 1)
        self.assertIn("0 == 0", result.failures[0][1])
        original = book.build
        source = inspect.getsource(original)
        plant = 'pdf = temp / "book.pdf"'
        self.assertEqual(source.count(plant), 1)
        try:
            exec(source.replace(plant, "pdf = output"), book.__dict__)
            result = unittest.TestResult()
            BookTests("test_atomic_publication").run(result)
            self.assertFalse(result.errors)
            self.assertEqual(len(result.failures), 1)
            self.assertIn("b'partial' != b'previous output'", result.failures[0][1])
        finally:
            book.build = original


if __name__ == "__main__":
    unittest.main()
