"""Saturday Multiverse — The Infinite Library.

Imports documents (PDF, EPUB, TXT, Markdown, HTML, DOCX and existing
world packs) into a local, searchable index. Source files are stored
verbatim on disk and never modified; the database holds metadata and
heading-aware chunks for context-aware retrieval during play — so a whole
novel can inform the Game Master without ever fitting in one prompt.

Parsing uses only the standard library except PDF (optional `pypdf`).
Malicious files are handled defensively: size caps, entry caps, no
entity expansion (ElementTree never resolves external entities), and
every parse failure is a clean 400 for the user, never a crash.
"""
from __future__ import annotations

import hashlib
import html as html_mod
import io
import json
import re
import zipfile
from xml.etree import ElementTree as ET

from . import config, db
from .db import jdumps, new_id, utcnow

MAX_DOCUMENT_BYTES = 40 * 1024 * 1024     # uploaded file
MAX_EXTRACTED_CHARS = 8 * 1024 * 1024     # decompressed text (zip-bomb guard)
MAX_ZIP_ENTRIES = 2000
CHUNK_TARGET = 1100                       # chars per chunk
WORLD_PACK_TYPES = {"worldpack"}

_DOC_TABLE = "library_docs"
_CHUNK_TABLE = "library_chunks"
_FTS_TABLE = "library_fts"


class LibraryError(ValueError):
    pass


# ==========================================================================
# Text extraction (per format)
# ==========================================================================

def _clean(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()[:MAX_EXTRACTED_CHARS]


def _extract_txt(data: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return _clean(data.decode(enc))
        except (UnicodeDecodeError, LookupError):
            continue
    return _clean(data.decode("utf-8", errors="replace"))


def _extract_md(data: bytes) -> str:
    return _extract_txt(data)


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\n{3,}")


def _extract_html(data: bytes) -> str:
    raw = data.decode("utf-8", errors="replace")
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h[1-6]>|</li>", "\n", raw)
    raw = re.sub(r"(?i)<h([1-6])[^>]*>", lambda m: f"\n\n## ", raw)
    text = _TAG_RE.sub(" ", raw)
    text = html_mod.unescape(text)
    return _clean(_WS_RE.sub("\n\n", text))


def _zip_guard(zf: zipfile.ZipFile) -> None:
    if len(zf.namelist()) > MAX_ZIP_ENTRIES:
        raise LibraryError("that archive has too many entries to read safely")
    total = sum(i.file_size for i in zf.infolist())
    if total > MAX_DOCUMENT_BYTES * 3:
        raise LibraryError("that archive decompresses to an unsafe size")


def _extract_docx(data: bytes) -> str:
    """Word .docx: a zip of XML. Paragraphs carry optional heading styles."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(bytes(data)))
    except zipfile.BadZipFile:
        raise LibraryError("that DOCX file is not a valid zip document")
    _zip_guard(zf)
    if "word/document.xml" not in zf.namelist():
        raise LibraryError("that DOCX file has no readable body")
    xml = zf.read("word/document.xml")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise LibraryError("that DOCX body could not be parsed")
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    out: list[str] = []
    for para in root.iter(ns + "p"):
        style = ""
        ppr = para.find(ns + "pPr")
        if ppr is not None:
            st = ppr.find(ns + "pStyle")
            if st is not None:
                style = (st.get(ns + "val") or "").lower()
        text = "".join(t.text or "" for t in para.iter(ns + "t")).strip()
        if not text:
            continue
        if style.startswith("heading") or style.startswith("titre"):
            try:
                level = int(style[-1])
            except ValueError:
                level = 1
            out.append("#" * max(1, min(4, level)) + " " + text)
        else:
            out.append(text)
    if not out:
        raise LibraryError("no readable text found in that DOCX")
    return _clean("\n".join(out))


def _extract_epub(data: bytes) -> tuple[str, dict]:
    """EPUB: zip of XHTML chapters; metadata from the OPF package."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(bytes(data)))
    except zipfile.BadZipFile:
        raise LibraryError("that EPUB file is not a valid zip document")
    _zip_guard(zf)
    meta: dict = {}
    container = zf.read("META-INF/container.xml")
    root = ET.fromstring(container)
    ns = "{urn:oasis:names:tc:opendocument:xmlns:container}"
    opf_path = None
    for rf in root.iter(ns + "rootfile"):
        opf_path = rf.get("full-path")
        break
    if not opf_path:
        raise LibraryError("that EPUB has no package manifest")
    opf = ET.fromstring(zf.read(opf_path))
    opf_ns = opf.tag[: opf.tag.index("}") + 1] if "}" in opf.tag else ""
    dc = opf_ns + "dc" if opf_ns else "{http://www.idpf.org/2007/opf}"
    for el in opf.iter():
        tag = el.tag.split("}")[-1]
        if tag in ("title", "creator") and (el.text or "").strip():
            meta.setdefault(tag, el.text.strip())
    # spine order -> readable documents
    manifest: dict[str, str] = {}
    for item in opf.iter():
        if item.tag.split("}")[-1] == "item":
            iid, href, mtype = item.get("id"), item.get("href"), item.get("media-type", "")
            if iid and href and "html" in mtype:
                manifest[iid] = href
    order: list[str] = []
    for item in opf.iter():
        if item.tag.split("}")[-1] == "itemref":
            idref = item.get("idref")
            if idref in manifest:
                order.append(manifest[idref])
    if not order:
        order = [n for n in zf.namelist() if n.endswith((".xhtml", ".html"))]
    opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
    parts: list[str] = []
    for href in order[:400]:
        path = (opf_dir + href) if not href.startswith("TEXT/") and (opf_dir + href) in zf.namelist() else href
        # resolve relative hrefs defensively
        candidates = [href, opf_dir + href]
        real = next((c for c in candidates if c in zf.namelist()), None)
        if not real:
            continue
        try:
            raw = zf.read(real)
        except (KeyError, RuntimeError):
            continue
        part = _extract_html(raw)
        if part:
            parts.append(part)
        if sum(len(p) for p in parts) > MAX_EXTRACTED_CHARS:
            break
    if not parts:
        raise LibraryError("no readable chapters found in that EPUB")
    return _clean("\n\n".join(parts)), {k: v for k, v in meta.items()}


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise LibraryError(
            "PDF support needs the optional 'pypdf' package — install it with "
            "`pip install pypdf`, then re-import this document"
        )
    import io
    try:
        reader = PdfReader(io.BytesIO(bytes(data)))
        if len(reader.pages) > 4000:
            raise LibraryError("that PDF is too large to read safely")
        pages = []
        total = 0
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            pages.append(text)
            total += len(text)
            if total > MAX_EXTRACTED_CHARS:
                break
    except LibraryError:
        raise
    except Exception:
        raise LibraryError("that PDF could not be parsed")
    joined = "\n\n".join(p for p in pages if p)
    if not joined.strip():
        raise LibraryError("no extractable text in that PDF (it may be a scan)")
    return _clean(joined)


# ==========================================================================
# Chunking (heading-aware)
# ==========================================================================

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$")


def chunk_text(text: str) -> list[dict]:
    """Split into heading-aware chunks of roughly CHUNK_TARGET characters."""
    chunks: list[dict] = []
    heading = ""
    buf: list[str] = []
    size = 0

    def flush():
        nonlocal buf, size
        body = "\n".join(buf).strip()
        if body:
            chunks.append({"heading": heading, "text": body,
                           "word_count": len(body.split())})
        buf, size = [], 0

    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        m = _HEADING_RE.match(para)
        if m:
            flush()
            heading = m.group(2)[:120]
            continue
        if size + len(para) > CHUNK_TARGET and size > CHUNK_TARGET * 0.4:
            flush()
        buf.append(para)
        size += len(para) + 1
        if len(chunks) >= 20000:
            break
    flush()
    return chunks


# ==========================================================================
# Import / list / search / delete
# ==========================================================================

def import_document(data: bytes, filename: str, *, title: str = "",
                    author: str = "", source_url: str = "",
                    license: str = "Private", attribution: str = "",
                    private: bool = False) -> dict:
    if len(data) > MAX_DOCUMENT_BYTES:
        raise LibraryError("that file is too large for the library (40 MB limit)")
    if not data:
        raise LibraryError("that file is empty")
    filename = (filename or "document.txt").strip()[:200]
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"

    meta: dict = {}
    doc_type = ext if ext in ("txt", "md", "html", "docx", "epub", "pdf") else "txt"
    if ext in ("htm", "xhtml"):
        doc_type = "html"
    if ext == "markdown":
        doc_type = "md"
    if doc_type == "txt" and ext == "json":
        raise LibraryError("use the world-pack import endpoint for pack JSON")

    if doc_type in ("txt", "md"):
        text = _extract_txt(data)
    elif doc_type == "html":
        text = _extract_html(data)
    elif doc_type == "docx":
        text = _extract_docx(data)
    elif doc_type == "epub":
        text, meta = _extract_epub(data)
        if not author and meta.get("creator"):
            author = meta["creator"]
        if not title and meta.get("title"):
            title = meta["title"]
    elif doc_type == "pdf":
        text = _extract_pdf(data)
    else:
        text = _extract_txt(data)

    if len(text) < 25:
        raise LibraryError("not enough readable text in that document")

    doc_id = new_id("doc")
    file_hash = hashlib.sha256(data).hexdigest()
    config.LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    original = config.LIBRARY_DIR / f"{doc_id}.orig"
    original.write_bytes(data)  # verbatim; the library never edits sources

    if not title:
        title = filename.rsplit(".", 1)[0].replace("_", " ").strip()[:160] or "Untitled"
    chunks = chunk_text(text)
    db.execute(
        f"INSERT INTO {_DOC_TABLE} (id, title, author, doc_type, source_url, license,"
        " attribution, file_hash, original_path, n_chunks, n_words, private, meta_json,"
        " added_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (doc_id, title[:160], author[:120], doc_type, source_url[:300],
         license[:120], attribution[:300], file_hash, str(original),
         len(chunks), sum(c["word_count"] for c in chunks),
         1 if private else 0, jdumps(meta), utcnow()),
    )
    _write_chunks(doc_id, chunks)
    db.log_event("library", "library_import", {"doc_id": doc_id, "title": title[:80],
                                               "chunks": len(chunks)})
    return doc_view(doc_id)


def _write_chunks(doc_id: str, chunks: list[dict]) -> None:
    rows = [(new_id("chk"), doc_id, i, c["heading"][:120], c["text"][:2000], c["word_count"])
            for i, c in enumerate(chunks)]
    db.get_conn().executemany(
        f"INSERT INTO {_CHUNK_TABLE} (id, doc_id, seq, heading, text, word_count)"
        " VALUES (?,?,?,?,?,?)", rows,
    )
    db.execute(f"UPDATE {_DOC_TABLE} SET n_chunks=? WHERE id=?", (len(rows), doc_id))
    _fts_write(doc_id, rows)


def _fts_write(doc_id: str, rows: list[tuple]) -> None:
    try:
        db.get_conn().executemany(
            f"INSERT INTO {_FTS_TABLE} (doc_id, seq, heading, text) VALUES (?,?,?,?)",
            [(r[1], r[2], r[3], r[4]) for r in rows],
        )
    except Exception:
        pass  # FTS unavailable: LIKE search still works


def _fts_delete(doc_id: str) -> None:
    try:
        db.execute(f"DELETE FROM {_FTS_TABLE} WHERE doc_id=?", (doc_id,))
    except Exception:
        pass


def doc_view(doc_id: str) -> dict:
    row = db.query_one(f"SELECT * FROM {_DOC_TABLE} WHERE id=?", (doc_id,))
    if not row:
        raise LibraryError("no such document in the library")
    d = dict(row)
    d["meta"] = json.loads(d.pop("meta_json") or "{}")
    return d


def list_docs(include_private: bool = True) -> list[dict]:
    q = f"SELECT * FROM {_DOC_TABLE}"
    if not include_private:
        q += " WHERE private=0"
    q += " ORDER BY added_at DESC"
    return [dict(r) for r in db.query(q)]


def delete_doc(doc_id: str) -> None:
    row = db.query_one(f"SELECT original_path FROM {_DOC_TABLE} WHERE id=?", (doc_id,))
    if not row:
        raise LibraryError("no such document")
    _fts_delete(doc_id)
    db.execute(f"DELETE FROM {_CHUNK_TABLE} WHERE doc_id=?", (doc_id,))
    db.execute(f"DELETE FROM {_DOC_TABLE} WHERE id=?", (doc_id,))
    import pathlib
    try:
        pathlib.Path(row["original_path"]).unlink(missing_ok=True)
    except OSError:
        pass


def search(query: str, doc_id: str | None = None, k: int = 8) -> list[dict]:
    """Full-text search across the library (or one document)."""
    query = (query or "").strip()[:200]
    if not query:
        return []
    results: list[dict] = []
    where = "WHERE doc_id=?" if doc_id else ""
    params = (doc_id,) if doc_id else ()
    try:
        words_in = [w for w in re.findall(r"\w+", query) if w.upper() not in ("OR", "AND", "NOT")]
        match = " OR ".join(words_in or [query])[:200]
        rows = db.query(
            f"SELECT doc_id, seq, heading, text,"
            f" bm25({_FTS_TABLE}) AS rank FROM {_FTS_TABLE} {where}"
            f"{' AND' if doc_id else ' WHERE'} {_FTS_TABLE} MATCH ?"
            f" ORDER BY rank LIMIT ?",  # type: ignore[arg-type]
            (*params, match, max(1, min(50, k))),
        )
        for r in rows:
            results.append(dict(r))
    except Exception:
        results = []
    if not results:
        words = [w for w in re.findall(r"\w+", query.lower()) if w not in ("or", "and", "not")][:5]
        clauses = " AND ".join("lower(text) LIKE ?" for _ in words)
        binds = [f"%{w}%" for w in words]
        rows = db.query(
            f"SELECT doc_id, seq, heading, text, 0 AS rank FROM {_CHUNK_TABLE} {where}"
            + (" AND " if doc_id else " WHERE ") + clauses + " LIMIT ?",
            (*params, *binds, max(1, min(50, k))),
        )
        results = [dict(r) for r in rows]
    return results


def retrieve_for_prompt(doc_id: str, context: dict, k: int = 4) -> list[str]:
    """Context-sensitive retrieval for the GM. No random fallback: if nothing
    matches the player's actual situation, return no passages rather than
    surfacing unrelated (potentially spoiling) parts of the book.

    context keys (all optional): action_text, scene_title, scene_brief,
    location_name, npc_names, quest_titles, horizon (int: max chunk seq
    revealed so far), after (int: min chunk seq).
    """
    if not isinstance(context, dict):
        context = {"action_text": str(context)}
    terms: list[str] = []
    for source in (context.get("action_text"), context.get("scene_title"),
                   context.get("scene_brief"), context.get("location_name")):
        if isinstance(source, str):
            terms.extend(_key_terms(source, max_terms=8))
    for name in (context.get("npc_names") or []):
        if isinstance(name, str) and len(name) >= 3:
            terms.append(name.strip()[:40])
    for q in (context.get("quest_titles") or []):
        if isinstance(q, str):
            terms.extend(_key_terms(q, max_terms=4))
    # dedupe, keep order, cap
    seen: list[str] = []
    for t in terms:
        if t.lower() not in [s.lower() for s in seen]:
            seen.append(t)
    seen = seen[:12]
    if not seen:
        return []
    hits = search(" ".join(seen), doc_id=doc_id, k=k * 2)
    if not hits:
        return []
    horizon = context.get("horizon")
    after = context.get("after")
    out = []
    for h in hits:
        seq = h.get("seq")
        if isinstance(horizon, int) and isinstance(seq, int) and seq > horizon:
            continue  # beyond the story's revealed horizon: never surface
        if isinstance(after, int) and isinstance(seq, int) and seq < after:
            continue
        out.append(f"[{h['heading']}] {h['text'][:600]}")
        if len(out) >= k:
            break
    return out


def _key_terms(action_text: str, max_terms: int = 8) -> list[str]:
    stop = {"the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "at", "i",
            "my", "me", "we", "is", "are", "was", "were", "it", "for", "with", "as",
            "you", "your", "he", "she", "they", "them", "his", "her", "do", "does",
            "what", "who", "where", "when", "how", "this", "that", "then", "than"}
    words = re.findall(r"[A-Za-z0-9']{3,}", (action_text or "").lower())
    seen: list[str] = []
    for w in words:
        if w in stop or w in seen:
            continue
        seen.append(w)
        if len(seen) >= max_terms:
            break
    return seen


def doc_text_stats(doc_id: str) -> dict:
    row = db.query_one(f"SELECT n_chunks, n_words FROM {_DOC_TABLE} WHERE id=?", (doc_id,))
    if not row:
        raise LibraryError("no such document")
    return {"chunks": row["n_chunks"], "words": row["n_words"]}
