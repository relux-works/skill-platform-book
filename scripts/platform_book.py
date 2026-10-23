"""Build the bundled book format without installing tools or fetching assets."""
import argparse
import hashlib
import importlib.metadata
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from urllib.parse import urldefrag

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


class Refusal(Exception):
    pass


def require(condition, message):
    if not condition:
        raise Refusal(message)


def run(argv):
    result = subprocess.run(list(map(str, argv)), text=True, capture_output=True)
    require(result.returncode == 0, f"{Path(str(argv[0])).name} failed: {result.stderr.strip()}")
    return result.stdout, result.stderr


def readiness():
    pins = json.loads((ASSETS / "toolchain.json").read_text())
    require(sys.version.split()[0] == pins["python"], "Python version differs from toolchain.json")
    for tool in ("pandoc",):
        require(shutil.which(tool), f"missing tool: {tool}")
        output, _ = run([tool, "--version"])
        version = output.splitlines()[0].split()[-1]
        require(version == pins[tool], f"{tool} version differs from toolchain.json")
    for package in ("pypdf", "weasyprint"):
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            raise Refusal(f"missing pinned Python dependency: {package}") from None
        require(version == pins[package], f"{package} version differs from toolchain.json")
    virtual_env = os.environ.get("VIRTUAL_ENV")
    require(virtual_env and Path(sys.prefix).resolve() == Path(virtual_env).resolve(),
            "Python is outside the activated VIRTUAL_ENV")
    try:
        import weasyprint  # Also prove that the provisioned native libraries load.
    except OSError:
        raise Refusal("WeasyPrint native libraries unavailable; see README provisioning") from None
    for name, digest in pins["fonts"].items():
        path = ASSETS / "fonts" / name
        require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest,
                f"missing or modified bundled font: {name}")
    return pins


def settings(book):
    require(book.is_dir(), "book directory missing")
    config = json.loads((book / "book.json").read_text())
    require(config.get("language") in ("en", "ru"), "language must be en or ru")
    require(type(config.get("toc")) is bool, "toc must be boolean")
    chapters = sorted((book / config["language"]).glob("[0-9][0-9]-*.md"))
    require(bool(chapters), "no numbered chapters")
    require(not (book / config["language"]).is_symlink() and
            all(path.is_file() and not path.is_symlink() for path in chapters), "chapter symlink forbidden")
    return config, chapters


def contained(book, value):
    require(isinstance(value, str) and value and "\\" not in value, "invalid figure path")
    relative = Path(value)
    require(not relative.is_absolute() and ".." not in relative.parts, "figure path escapes book")
    path = book / relative
    require(not any((book / Path(*relative.parts[:i])).is_symlink()
                    for i in range(1, len(relative.parts) + 1)),
            "figure symlink forbidden")
    require(path.is_file() and path.resolve().is_relative_to(book.resolve()), "missing figure file")
    return path


def check_svg(path):
    text = path.read_text()
    require(not re.search(r"<!DOCTYPE|<!ENTITY", text, re.I), "SVG external declaration forbidden")
    tree = ET.fromstring(text)
    for node in tree.iter():
        require(node.tag.split("}")[-1] not in ("script", "foreignObject"), "SVG executable content forbidden")
        for key, value in node.attrib.items():
            if key.split("}")[-1] in ("href", "src"):
                require(value.startswith("#"), "SVG external resource forbidden")
        # Paint servers may refer to internal fragment IDs, never external files.
        for value in [*node.attrib.values(), node.text or ""]:
            require(not re.search(r"@import", value, re.I), "SVG external resource forbidden")
            for target in re.findall(r"url\(([^)]*)\)", value, re.I):
                require(target.strip().strip("'\"").startswith("#"), "SVG external resource forbidden")


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def check_attributes(node):
    # Attr is shared by headers, spans, divs, links, images, tables and cells.
    # Inspect its structural representation, including nested table attributes.
    if (isinstance(node, list) and len(node) == 3 and isinstance(node[0], str)
            and isinstance(node[1], list) and all(isinstance(c, str) for c in node[1])
            and isinstance(node[2], list) and all(isinstance(p, list) and len(p) == 2
                and all(isinstance(v, str) for v in p) for p in node[2])):
        for key, value in node[2]:
            require(key in ("width", "height"), f"Markdown attribute forbidden: {key}")
            if key in ("width", "height"):
                require(re.fullmatch(r"(?:[0-9]+(?:\.[0-9]+)?)(?:%|px|pt|em|rem|mm|cm|in)?", value),
                        "Markdown dimension must be a nonnegative length")
    if isinstance(node, dict):
        for value in node.values():
            check_attributes(value)
    elif isinstance(node, list):
        for value in node:
            check_attributes(value)


def check_figures(book):
    config, chapters = settings(book)
    # Pandoc's AST covers inline, reference-style and attribute-bearing images.
    output, _ = run(["pandoc", *chapters, "--from", "markdown", "--to", "json"])
    ast = json.loads(output)
    check_attributes(ast)
    manifest = json.loads((book / "src/figures.json").read_text())
    require(isinstance(manifest, dict), "figure manifest must be an object")
    declared = set()
    for stem, figure in manifest.items():
        require(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", stem), "invalid figure name")
        require(set(figure) == {"source", "render", "source_sha256", "render_sha256"}, "invalid figure record")
        for kind, directory in (("source", "src"), ("render", "diagrams")):
            path = contained(book, figure[kind])
            require(path.parent == book / directory and path.stem == stem, "figure name/directory mismatch")
            require(figure[kind] not in declared, "duplicate figure path")
            declared.add(figure[kind])
            require(hashlib.sha256(path.read_bytes()).hexdigest() == figure[kind + "_sha256"],
                    f"figure {kind} hash mismatch: {stem}")
            if path.suffix.lower() == ".svg":
                check_svg(path)
    for node in walk(ast):
        if node.get("t") == "Image":
            target = node["c"][2][0]
            require(re.fullmatch(r"\.\./diagrams/[a-z0-9]+(?:-[a-z0-9]+)*\.(png|svg|jpg|jpeg)", target),
                    "image must use a local ../diagrams/ render")
            render = target.removeprefix("../")
            require(render in declared and any(f["render"] == render for f in manifest.values()),
                    "image absent from figure manifest")
        if node.get("t") in ("RawBlock", "RawInline"):
            require(node["c"][0] not in ("html", "html5"),
                    "raw HTML forbidden; use Markdown figures and attributes")
    for directory in ("src", "diagrams"):
        for path in (book / directory).rglob("*"):
            require(not path.is_symlink(), "figure symlink forbidden")
            if path.is_file() and path.name not in ("figures.json", ".gitkeep"):
                require(path.relative_to(book).as_posix() in declared, "orphan figure source/render")
    return config, chapters


def check_pdf(path, pages=None, fonts=()):
    from pypdf import PdfReader
    from pypdf.generic import StreamObject
    pdf = PdfReader(path)
    require(len(pdf.pages) > 0 and (pages is None or len(pdf.pages) == pages), "PDF page count mismatch")
    found = set()
    seen = set()

    def inspect(resources):
        if hasattr(resources, "get_object"):
            resources = resources.get_object()
        if id(resources) in seen:
            return
        seen.add(id(resources))
        font_refs = resources.get("/Font", {})
        if hasattr(font_refs, "get_object"):
            font_refs = font_refs.get_object()
        for ref in font_refs.values():
            font = ref.get_object()
            descendants = font.get("/DescendantFonts", [font])
            for ref in descendants:
                item = ref.get_object()
                desc = item.get("/FontDescriptor")
                require(desc is not None, "PDF font descriptor missing")
                descriptor = desc.get_object()
                keys = [k for k in ("/FontFile", "/FontFile2", "/FontFile3") if k in descriptor]
                require(bool(keys), "PDF font is not embedded")
                for key in keys:
                    try:
                        program = descriptor.raw_get(key).get_object()
                        valid = isinstance(program, StreamObject) and bool(program.get_data().strip())
                    except Exception:
                        valid = False
                    require(valid, "PDF embedded font program must be a nonempty stream")
                found.add(re.sub(r"[^a-z]", "", str(item.get("/BaseFont", "")).lower()))
        objects = resources.get("/XObject", {})
        if hasattr(objects, "get_object"):
            objects = objects.get_object()
        for ref in objects.values():
            inspect(ref.get_object().get("/Resources", {}))

    for page in pdf.pages:
        inspect(page.get("/Resources", {}))
    require(bool(found), "PDF has no embedded text fonts")
    for family in fonts:
        require(any(re.sub(r"[^a-z]", "", family.lower()) in name for name in found),
                f"PDF font family missing: {family}")
    require(any(page.extract_text().strip() for page in pdf.pages), "PDF has no extractable text")
    return {"pages": len(pdf.pages), "embedded_fonts": sorted(found)}


def render_pdf(book, language, html, pdf):
    from weasyprint import HTML
    from weasyprint.urls import URLFetcher, URLFetcherResponse, FatalURLFetchingError
    # Snapshot only authorized bytes, then serve them without an OS/network
    # opener. Every fetch, including nested SVG and CSS URLs, uses this object.
    resources = {}
    pins = json.loads((ASSETS / "toolchain.json").read_text())
    manifest = json.loads((book / "src/figures.json").read_text())
    paths = [(ASSETS / "style.css", None)]
    paths += [(ASSETS / "fonts" / name, digest) for name, digest in pins["fonts"].items()]
    paths += [(contained(book, f["render"]), f["render_sha256"]) for f in manifest.values()]
    for path, digest in paths:
        data = path.read_bytes()
        require(digest is None or hashlib.sha256(data).hexdigest() == digest,
                "renderer asset changed after validation")
        resources[path.resolve().as_uri()] = data

    denied = []
    class DeclaredAssets(URLFetcher):
        def fetch(self, url, headers=None):
            target, _ = urldefrag(url)
            if target not in resources:
                # WeasyPrint intentionally catches ordinary fetch exceptions.
                # Nested SVG rendering can catch even fatal exceptions. Keep a
                # denial flag as well, so no such PDF can pass publication.
                denied.append(True)
                raise FatalURLFetchingError("renderer resource is not declared")
            mime = mimetypes.guess_type(target)[0] or "application/octet-stream"
            return URLFetcherResponse(url, resources[target], {"Content-Type": mime})

    fetcher = DeclaredAssets()
    errors = []
    class Errors(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                errors.append(record.getMessage())
    logger = logging.getLogger("weasyprint")
    handler = Errors()
    logger.addHandler(handler)
    try:
        HTML(string=html.read_text(), base_url=(book / language).resolve().as_uri() + "/",
             url_fetcher=fetcher).write_pdf(pdf, stylesheets=[(ASSETS / "style.css").resolve().as_uri()])
    except FatalURLFetchingError:
        raise Refusal("renderer resource is not declared") from None
    finally:
        logger.removeHandler(handler)
    require(not denied, "renderer resource is not declared")
    require(not errors, "renderer reported a missing or invalid resource")


def build(book, output, pages=None):
    readiness()
    config, chapters = check_figures(book)
    require(output.suffix.lower() == ".pdf", "output must end in .pdf")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".platform-book-", dir=output.parent) as temporary:
        temp = Path(temporary)
        html = temp / "book.html"
        command = ["pandoc", *chapters, "--from", "markdown", "--to", "html5", "--standalone",
                   "--template", ASSETS / "template.html", "--lua-filter", ASSETS / "filters/book.lua",
                   "--section-divs", "--syntax-highlighting=none", "--number-sections", "--number-offset=-1",
                   "--metadata", "lang=" + config["language"], "--metadata", "toc-title=" + ("Contents" if config["language"] == "en" else "Содержание"),
                   "--output", html]
        if config["toc"]:
            command += ["--toc", "--toc-depth=2"]
        run(command)
        pdf = temp / "book.pdf"
        render_pdf(book, config["language"], html, pdf)
        result = check_pdf(pdf, pages, ("PT Serif", "PT Sans"))
        os.replace(pdf, output)
    return result


def scaffold(destination, language):
    require(not destination.exists() and not destination.is_symlink(), "destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Prepare beside the destination so a failed scaffold cannot publish half a book.
    with tempfile.TemporaryDirectory(prefix=".platform-book-new-", dir=destination.parent) as temporary:
        prepared = Path(temporary) / "book"
        shutil.copytree(ASSETS / "scaffold", prepared)
        shutil.rmtree(prepared / ("ru" if language == "en" else "en"))
        (prepared / "book.json").write_text(json.dumps({"language": language, "toc": False}, indent=2) + "\n")
        prepared.rename(destination)


def main():
    parser = argparse.ArgumentParser(prog="platform-book", description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("ready")
    new = subs.add_parser("new")
    new.add_argument("directory", type=Path); new.add_argument("--language", choices=("en", "ru"), default="en")
    figures = subs.add_parser("figures"); figures.add_argument("book", type=Path)
    render = subs.add_parser("build")
    render.add_argument("book", type=Path); render.add_argument("output", type=Path)
    render.add_argument("--expected-pages", type=int)
    pdf = subs.add_parser("check-pdf")
    pdf.add_argument("pdf", type=Path); pdf.add_argument("--expected-pages", type=int)
    pdf.add_argument("--fonts", nargs="*", default=[])
    args = parser.parse_args()
    try:
        if args.command == "ready":
            readiness(); print("toolchain and bundled fonts: ready")
        elif args.command == "new":
            scaffold(args.directory.resolve(), args.language); print("book scaffolded")
        elif args.command == "figures":
            check_figures(args.book.resolve()); print("figures: ok")
        elif args.command == "build":
            print(json.dumps(build(args.book.resolve(), args.output.resolve(), args.expected_pages)))
        elif args.command == "check-pdf":
            print(json.dumps(check_pdf(args.pdf, args.expected_pages, args.fonts)))
    except (Refusal, OSError, ValueError, KeyError, TypeError, ImportError, ET.ParseError) as error:
        print(f"platform-book: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
