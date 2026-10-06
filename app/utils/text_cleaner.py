from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

_WHITESPACE_RE = re.compile(r"\s+")


def html_to_text(html: str) -> str:
    """Strip HTML and normalize whitespace. Used on ATS job descriptions."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    return normalize_whitespace(text)


def normalize_whitespace(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def normalize_tech_name(name: str) -> str:
    """Normalize tech names for stack signals.

    Rules:
      - lowercase, trimmed
      - strip version suffixes ("React 18" -> "react")
      - common synonyms collapsed
    """
    s = name.strip().lower()
    s = re.sub(r"\s*\d+(\.\d+)*\s*$", "", s)  # trailing versions
    s = s.replace(".js", "").replace("js framework", "")
    synonyms = {
        "reactjs": "react",
        "nextjs": "next",
        "next.js": "next",
        "vuejs": "vue",
        "node.js": "node",
        "nodejs": "node",
        "typescript": "typescript",
        "ts": "typescript",
        "golang": "go",
    }
    return synonyms.get(s, s)
