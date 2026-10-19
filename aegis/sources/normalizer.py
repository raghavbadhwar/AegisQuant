"""Safe bounded document normalization and injection scanning."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from xml.etree import ElementTree

from aegis.contracts import NormalizedDocument, RawDocumentReceipt, SourceManifest, SourceTime


class NormalizationError(ValueError):
    pass


_INJECTION_PATTERNS = {
    "agent_instruction": re.compile(
        r"(?i)\b(ignore|override) (all |the )?(previous|system) instructions?\b"
    ),
    "credential_request": re.compile(r"(?i)\b(api key|password|secret token|credentials?)\b"),
    "exfiltration": re.compile(r"(?i)\b(exfiltrate|send .* secrets?|upload .* credentials?)\b"),
    "encoded_command": re.compile(r"(?i)\b(base64|powershell|curl\s+https?://)\b"),
    "suspicious_link": re.compile(r"(?i)(javascript:|data:text/html)"),
}


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip = 0
        self._title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        if tag == "title":
            self._title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if tag == "title":
            self._title = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        cleaned = " ".join(data.split())
        if cleaned:
            self.parts.append(cleaned)
            if self._title:
                self.title_parts.append(cleaned)


def scan_injection(text: str) -> list[str]:
    flags = [name for name, pattern in _INJECTION_PATTERNS.items() if pattern.search(text)]
    if any(0x202A <= ord(character) <= 0x202E for character in text):
        flags.append("hidden_unicode")
    return sorted(flags)


def _extract(receipt: RawDocumentReceipt) -> tuple[str | None, str, str]:
    body = __import__("pathlib").Path(receipt.raw_uri).read_bytes()
    media_type = receipt.media_type.split(";", 1)[0].lower()
    if media_type == "text/html":
        parser = _TextHTMLParser()
        parser.feed(body.decode("utf-8", errors="replace"))
        return " ".join(parser.title_parts) or None, "\n".join(parser.parts), "html-v1"
    if media_type == "application/json":
        payload = json.loads(body)
        return None, json.dumps(payload, sort_keys=True, ensure_ascii=False), "json-v1"
    if media_type in {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}:
        root = ElementTree.fromstring(body)
        text = "\n".join(value.strip() for value in root.itertext() if value.strip())
        title = next(
            (
                value.strip()
                for node in root.iter()
                if node.tag.endswith("title")
                for value in node.itertext()
                if value.strip()
            ),
            None,
        )
        return title, text, "xml-v1"
    if media_type in {"text/plain", "text/markdown", "text/csv"}:
        return None, body.decode("utf-8", errors="replace"), "text-v1"
    raise NormalizationError(f"unsupported media type: {media_type}")


def normalize(
    receipt: RawDocumentReceipt,
    manifest: SourceManifest,
    *,
    available_at: datetime,
    entity_ids: list[str],
    document_type: str,
) -> NormalizedDocument:
    title, text, parser_version = _extract(receipt)
    text = text.strip()
    if not text:
        raise NormalizationError("normalized document is empty")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return NormalizedDocument(
        document_id=f"doc-{digest[:24]}",
        source_id=manifest.source_id,
        source_url=receipt.url,
        title=title,
        text=text,
        document_type=document_type,
        entity_ids=sorted(set(entity_ids)),
        source_time=SourceTime(
            available_at=available_at,
            retrieved_at=receipt.fetched_at,
        ),
        raw_receipt=receipt,
        normalized_content_hash=digest,
        injection_flags=scan_injection(text),
        parser_version=parser_version,
        extraction_confidence=0.95,
    )
