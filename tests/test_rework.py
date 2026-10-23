"""Regression witnesses for installed environments, fetches and font programs."""
import hashlib
import http.server
import inspect
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import unittest
from unittest.mock import patch

import test_book
ROOT, book = test_book.ROOT, test_book.book


class ReworkTests(unittest.TestCase):
    setUp = test_book.BookTests.setUp
    manifest = test_book.BookTests.manifest
    write_manifest = test_book.BookTests.write_manifest
    # Reuse fixture helpers without running the inherited contract suite twice.
    def cli(self, *args, package=ROOT, env=None):
        return subprocess.run([str(package / "scripts/platform-book"), *map(str, args)],
                              env=env, text=True, capture_output=True)

    # Claim: the exported launcher retains the activated ordinary venv despite a
    # base-interpreter PATH prefix; an invalid activation refuses without fallback.
    # Real Curator installation is separately exercised by check_curator.py.
    def test_venv_launcher(self):
        import sys
        self.assertNotEqual(sys.prefix, sys.base_prefix, "run tests in the documented venv")
        env = os.environ.copy()
        env["VIRTUAL_ENV"] = sys.prefix
        env["PATH"] = str(Path(sys._base_executable).parent) + os.pathsep + env["PATH"]
        good = self.cli("ready", env=env)
        self.assertEqual(good.returncode, 0, good.stderr)
        del env["VIRTUAL_ENV"]
        bad = self.cli("ready", env=env)
        self.assertEqual(bad.returncode, 2)
        self.assertIn("activate the provisioned Python venv", bad.stderr)
        env["VIRTUAL_ENV"] = str(self.root / "absent-venv")
        bad = self.cli("ready", env=env)
        self.assertEqual(bad.returncode, 2)
        self.assertIn("activated VIRTUAL_ENV has no Python interpreter", bad.stderr)
        # Existing but wrong environment must also refuse, never use its base.
        wrong = self.root / "wrong-venv/bin"
        wrong.mkdir(parents=True)
        (wrong / "python3").symlink_to(sys._base_executable)
        env["VIRTUAL_ENV"] = str(wrong.parent)
        bad = self.cli("ready", env=env)
        self.assertEqual(bad.returncode, 2)
        self.assertTrue("outside the activated VIRTUAL_ENV" in bad.stderr or
                        "missing pinned Python dependency" in bad.stderr, bad.stderr)

    def witness_server(self):
        hits = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.end_headers()
                self.wfile.write(b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
            def log_message(self, *args):
                pass
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        def stop():
            server.shutdown()
            server.server_close()
            thread.join()
        self.addCleanup(stop)
        return f"http://127.0.0.1:{server.server_port}/witness.svg", hits

    # Claim: the production figures/build commands reject style and other
    # resource-bearing attributes across AST node types before fetching, while
    # ordinary dimensions, classes and citation links remain buildable.
    def test_markdown_attribute_fetch_regression(self):
        url, hits = self.witness_server()
        original = self.chapter.read_text()
        positive = original.replace("(../diagrams/reading-flow.svg)",
                                    "(../diagrams/reading-flow.svg){#flow .tall width=80% height=100px}")
        positive += "\n[Reference](" + url + ")\n"
        self.chapter.write_text(positive)
        output = self.root / "published.pdf"
        good = self.cli("figures", self.book)
        self.assertEqual(good.returncode, 0, good.stderr)
        good = self.cli("build", self.book, output)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(hits, [])
        saved = output.read_bytes()
        variants = [
            original.replace("(../diagrams/reading-flow.svg)",
                             f'(../diagrams/reading-flow.svg){{style="background-image:url({url})"}}'),
            original + f'\n::: {{style="background:url({url})"}}\nText\n:::\n',
            original + f'\n[Text]{{style="background:url({url})"}}\n',
            original + f'\n# Heading {{style="background:url({url})"}}\n',
            original + f'\n[Reference]({url}){{rel=attachment}}\n',
            original.replace("(../diagrams/reading-flow.svg)",
                             f'(../diagrams/reading-flow.svg){{srcset="{url}"}}'),
        ]
        for text in variants:
            with self.subTest(text=text[-80:]):
                self.chapter.write_text(text)
                for command in [("figures", self.book), ("build", self.book, output)]:
                    refused = self.cli(*command)
                    self.assertEqual(refused.returncode, 2, refused.stderr)
                    self.assertIn("Markdown attribute forbidden:", refused.stderr)
                self.assertEqual(output.read_bytes(), saved)
                self.assertEqual(hits, [])
        self.chapter.write_text(original.replace("(../diagrams/reading-flow.svg)",
                                                '(../diagrams/reading-flow.svg){width="url(file:///missing)"}'))
        bad = self.cli("figures", self.book)
        self.assertEqual(bad.returncode, 2)
        self.assertIn("Markdown dimension must be a nonnegative length", bad.stderr)

    # Claim: the renderer itself refuses network, undeclared file and data URLs,
    # including escaped CSS syntax and nested SVG requests; it never delegates
    # a refused URL to a default opener. Declared image/font/CSS bytes still work.
    def test_renderer_resource_boundary(self):
        url, hits = self.witness_server()
        html = self.root / "input.html"
        output = self.root / "rendered.pdf"
        html.write_text('<p>Control</p><img src="../diagrams/reading-flow.svg">')
        book.render_pdf(self.book, "en", html, output)
        self.assertTrue(output.read_bytes().startswith(b"%PDF"))
        for target in [url, (self.chapter).as_uri(), "data:image/svg+xml,%3Csvg/%3E"]:
            for source in [f'<img src="{target}">',
                           f'<p style="background-image:u\\72l({target})">Text</p>',
                           f'<style>@import "{target}";</style><p>Text</p>']:
                with self.subTest(target=target, source=source[:40]):
                    html.write_text(source)
                    with self.assertRaisesRegex(book.Refusal, "renderer resource is not declared"):
                        book.render_pdf(self.book, "en", html, output)
                    self.assertEqual(hits, [])
        render = self.book / "diagrams/reading-flow.svg"
        original = render.read_bytes()
        render.write_bytes(original + b"\n")
        with self.assertRaisesRegex(book.Refusal, "renderer asset changed after validation"):
            book.render_pdf(self.book, "en", html, output)
        render.write_bytes(original)
        # A nested SVG request tests the same allow-list below HTML/CSS parsing.
        svg = self.book / "diagrams/reading-flow.svg"
        svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><image href="{url}" width="10" height="10"/></svg>')
        manifest = self.manifest()
        manifest["reading-flow"]["render_sha256"] = hashlib.sha256(svg.read_bytes()).hexdigest()
        self.write_manifest(manifest)
        html.write_text('<img src="../diagrams/reading-flow.svg">')
        with self.assertRaisesRegex(book.Refusal, "renderer resource is not declared"):
            book.render_pdf(self.book, "en", html, output)
        self.assertEqual(hits, [])

    def malformed_font_pdf(self, good, target, variant):
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import (NameObject, NullObject, TextStringObject,
                                   DecodedStreamObject, IndirectObject)
        writer = PdfWriter()
        writer.clone_document_from_reader(PdfReader(good))
        changed = 0
        for page in writer.pages:
            for font in page["/Resources"]["/Font"].values():
                font = font.get_object()
                for child in font.get("/DescendantFonts", [font]):
                    descriptor = child.get_object()["/FontDescriptor"].get_object()
                    for key in ["/FontFile", "/FontFile2", "/FontFile3"]:
                        if key not in descriptor:
                            continue
                        if variant == "null":
                            program = NullObject()
                        elif variant == "non-stream":
                            program = TextStringObject("not a font program")
                        elif variant == "unresolved":
                            program = IndirectObject(999999, 0, writer)
                        else:
                            program = DecodedStreamObject()
                            program.set_data(b"")
                        descriptor[NameObject(key)] = writer._add_object(program) if variant == "empty" else program
                        changed += 1
        self.assertGreater(changed, 0, "font mutation not applied")
        writer.write(target)

    # Claim: real embedded fonts pass both check-pdf and independent pdffonts;
    # null, empty, non-stream and dangling programs fail with the exact stream
    # diagnostic despite preserved page count and extractable text. A malformed
    # renderer result cannot replace a previously published PDF.
    def test_font_stream_regressions(self):
        good = self.root / "real.pdf"
        book.build(self.book, good, 2)
        verdict = self.cli("check-pdf", good, "--expected-pages", "2", "--fonts", "PT Serif", "PT Sans", "PT Mono")
        self.assertEqual(verdict.returncode, 0, verdict.stderr)
        independent = subprocess.run(["pdffonts", str(good)], capture_output=True, text=True, check=True)
        flags = [re.search(r"\s+(yes|no)\s+(yes|no)\s+(yes|no)\s+\d+\s+\d+\s*$", line)
                 for line in independent.stdout.splitlines()[2:]]
        self.assertTrue(flags)
        self.assertTrue(all(flag and flag[1] == "yes" for flag in flags), independent.stdout)
        output = self.root / "published.pdf"
        saved = good.read_bytes()
        output.write_bytes(saved)
        for variant in ("null", "empty", "non-stream", "unresolved"):
            with self.subTest(variant=variant):
                bad = self.root / (variant + ".pdf")
                self.malformed_font_pdf(good, bad, variant)
                refused = self.cli("check-pdf", bad, "--expected-pages", "2", "--fonts", "PT Serif", "PT Sans", "PT Mono")
                self.assertEqual(refused.returncode, 2, refused.stderr)
                self.assertIn("PDF embedded font program must be a nonempty stream", refused.stderr)
                def invalid_renderer(book_dir, language, html, pdf):
                    pdf.write_bytes(bad.read_bytes())
                with patch.object(book, "render_pdf", side_effect=invalid_renderer):
                    with self.assertRaisesRegex(book.Refusal, "PDF embedded font program must be a nonempty stream"):
                        book.build(self.book, output, 2)
                self.assertEqual(output.read_bytes(), saved)
                self.assertFalse(list(self.root.glob(".platform-book-*")))

    # Claim: descendant-font validation is also reached through Form XObjects,
    # including indirect resource dictionaries, without requiring a page font.
    def test_form_font_stream(self):
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        good = self.root / "real.pdf"
        book.build(self.book, good, 2)
        writer = PdfWriter()
        writer.clone_document_from_reader(PdfReader(good))
        visited = set()
        for page in writer.pages:
            resources = page["/Resources"]
            if id(resources) in visited:
                continue
            visited.add(id(resources))
            form = DecodedStreamObject()
            form.set_data(b"")
            form[NameObject("/Subtype")] = NameObject("/Form")
            form[NameObject("/Resources")] = writer._add_object(DictionaryObject({NameObject("/Font"): resources["/Font"]}))
            resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Fm1"): writer._add_object(form)})
            del resources["/Font"]
        nested = self.root / "form.pdf"
        writer.write(nested)
        book.check_pdf(nested, 2, ("PT Serif", "PT Sans", "PT Mono"))
        font = next(iter(form["/Resources"]["/Font"].values())).get_object()["/DescendantFonts"][0].get_object()
        font["/FontDescriptor"][NameObject("/FontFile2")] = writer._add_object(DecodedStreamObject())
        writer.write(nested)
        with self.assertRaisesRegex(book.Refusal, "PDF embedded font program must be a nonempty stream"):
            book.check_pdf(nested)

    # Claim: independent narrowing plants for the attribute policy, dimensions,
    # fetch allow-list and stream validator are detected at their intended gate.
    def test_new_gate_mutants(self):
        ast = {"t": "Span", "c": [["", [], [["style", "background:url(https://example.org/x)"]]], []]}
        original = book.require
        for label, node, message in [
            ("attribute", ast, "Markdown attribute forbidden:"),
            ("dimension", {"t": "Image", "c": [["", [], [["width", "url(x)"]]], [], ["x", ""]]}, "Markdown dimension")]:
            with self.subTest(gate=label):
                def weakened(ok, msg):
                    if msg.startswith(message):
                        return
                    original(ok, msg)
                with self.assertRaisesRegex(book.Refusal, message):
                    book.check_attributes(node)
                with patch.object(book, "require", side_effect=weakened):
                    with self.assertRaisesRegex(AssertionError, "Refusal not raised"):
                        with self.assertRaisesRegex(book.Refusal, message):
                            book.check_attributes(node)
        good = self.root / "real.pdf"
        book.build(self.book, good, 2)
        for variant in ("null", "empty", "non-stream", "unresolved"):
            bad = self.root / (variant + ".pdf")
            self.malformed_font_pdf(good, bad, variant)
            with self.assertRaisesRegex(book.Refusal, "nonempty stream"):
                book.check_pdf(bad)
            def weakened(ok, msg):
                if msg == "PDF embedded font program must be a nonempty stream":
                    return
                original(ok, msg)
            with patch.object(book, "require", side_effect=weakened):
                with self.assertRaisesRegex(AssertionError, "Refusal not raised"):
                    with self.assertRaisesRegex(book.Refusal, "nonempty stream"):
                        book.check_pdf(bad)
        render = self.book / "diagrams/reading-flow.svg"
        render.write_bytes(render.read_bytes() + b"\n")
        html = self.root / "snapshot.html"
        html.write_text('<img src="../diagrams/reading-flow.svg">')
        with self.assertRaisesRegex(book.Refusal, "renderer asset changed after validation"):
            book.render_pdf(self.book, "en", html, self.root / "snapshot.pdf")
        def weakened(ok, msg):
            if msg == "renderer asset changed after validation":
                return
            original(ok, msg)
        with patch.object(book, "require", side_effect=weakened):
            with self.assertRaisesRegex(AssertionError, "Refusal not raised"):
                with self.assertRaisesRegex(book.Refusal, "renderer asset changed after validation"):
                    book.render_pdf(self.book, "en", html, self.root / "snapshot.pdf")
        render.write_bytes(render.read_bytes()[:-1])
        # Narrow the fetch policy for a loopback-only known violation. The
        # positive assertion below establishes that the server itself works.
        url, hits = self.witness_server()
        html = self.root / "plant.html"
        html.write_text(f'<img src="{url}">')
        output = self.root / "plant.pdf"
        with self.assertRaisesRegex(book.Refusal, "renderer resource is not declared"):
            book.render_pdf(self.book, "en", html, output)
        self.assertEqual(hits, [])
        source = inspect.getsource(book.render_pdf)
        plant = 'denied.append(True)\n                raise FatalURLFetchingError("renderer resource is not declared")'
        self.assertEqual(source.count(plant), 1)
        original_render = book.render_pdf
        try:
            exec(source.replace(plant, "return super().fetch(url, headers)"), book.__dict__)
            book.render_pdf(self.book, "en", html, output)
            self.assertEqual(hits, ["/witness.svg"], "fetch plant did not exercise the intended violation")
            with self.assertRaisesRegex(AssertionError, "Lists differ"):
                self.assertEqual(hits, [], "forbidden fetch must never reach the server")
        finally:
            book.render_pdf = original_render


    # Claim: ignoring VIRTUAL_ENV is caught by the same launcher positive
    # control under a canonical-base PATH; no custom Python wrapper is used.
    def test_launcher_narrowing_mutant(self):
        import sys
        package = self.root / "mutant"
        shutil.copytree(ROOT / "scripts", package / "scripts")
        shutil.copytree(ROOT / "assets", package / "assets")
        launcher = package / "scripts/platform-book"
        source = launcher.read_text()
        plant = 'interpreter="$VIRTUAL_ENV/bin/python3"'
        self.assertEqual(source.count(plant), 1)
        env = os.environ.copy()
        env["VIRTUAL_ENV"] = sys.prefix
        env["PATH"] = str(Path(sys._base_executable).parent) + os.pathsep + env["PATH"]
        self.assertEqual(self.cli("ready", package=package, env=env).returncode, 0)
        launcher.write_text(source.replace(plant, "interpreter=python3"))
        bad = self.cli("ready", package=package, env=env)
        self.assertEqual(bad.returncode, 2, bad.stderr)
        self.assertTrue("outside the activated VIRTUAL_ENV" in bad.stderr or
                        "missing pinned Python dependency" in bad.stderr, bad.stderr)
        with self.assertRaisesRegex(AssertionError, "2 != 0"):
            self.assertEqual(bad.returncode, 0, "activated venv must survive canonical PATH")
