import re
from typing import Dict, List, Optional

import requests

from app.models.diff import DiffResponse, SectionDiff
from app.models.revision import Revision
from app.models.wiki_structure import Section
from app.services.revision_store import load_revision_snapshot, save_revision_snapshot

try:
    from app.ai.similarity_scoring import score_article_pair
except Exception:
    score_article_pair = None

USER_AGENT = "SymmetryUnified/1.0"


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip()).lower()


def _safe_similarity(text_a: str, text_b: str) -> float:
    text_a = text_a or ""
    text_b = text_b or ""

    if callable(score_article_pair):
        try:
            result = score_article_pair(text_a, text_b)
            if isinstance(result, (int, float)):
                return float(result)
            if isinstance(result, dict):
                for key in ("similarity", "score", "overall_similarity"):
                    value = result.get(key)
                    if isinstance(value, (int, float)):
                        return float(value)
        except Exception:
            pass

    words_a = set(text_a.split())
    words_b = set(text_b.split())

    if not words_a and not words_b:
        return 1.0

    return len(words_a & words_b) / max(len(words_a | words_b), 1)


def _parse_sections_from_content(content: str) -> List[Section]:
    if not content:
        return []

    lines = content.splitlines()
    sections: List[Section] = []

    current_title = "Lead section"
    current_lines: List[str] = []

    heading_pattern = re.compile(r"^(={2,6})\s*(.*?)\s*\1$")

    def flush_section() -> None:
        nonlocal current_title, current_lines
        text = "\n".join(current_lines).strip()
        if text:
            sections.append(
                Section(
                    title=current_title,
                    raw_content=text,
                    clean_content=text,
                    citations=[],
                    citation_position=[],
                )
            )
        current_lines = []

    for line in lines:
        match = heading_pattern.match(line.strip())
        if match:
            flush_section()
            current_title = match.group(2).strip() or "Untitled section"
        else:
            current_lines.append(line)

    flush_section()
    return sections


def _fetch_revision_by_id(title: str, lang: str, revid: int) -> Revision:
    url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "revisions",
        "revids": revid,
        "rvprop": "ids|timestamp|user|comment|content",
        "rvslots": "main",
        "format": "json",
        "formatversion": 2,
    }

    response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    data = response.json()

    pages = data.get("query", {}).get("pages", [])
    if not pages:
        raise ValueError(f"Revision {revid} not found")

    page = pages[0]
    revisions_data = page.get("revisions", [])
    if not revisions_data:
        raise ValueError(f"Revision {revid} not found")

    rev = revisions_data[0]
    slots = rev.get("slots", {})
    content = ""

    if isinstance(slots, dict) and "main" in slots:
        content = slots["main"].get("content") or ""
    else:
        content = rev.get("*") or ""

    cleaned = re.sub(r"\{\{.*?\}\}", "", content, flags=re.DOTALL)
    cleaned = re.sub(r"<!--.*?-->", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"\[\[File:.*?\]\]", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"\[\[|\]\]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    revision = Revision(
        revid=rev.get("revid"),
        parentid=rev.get("parentid"),
        timestamp=rev.get("timestamp"),
        user=rev.get("user"),
        comment=rev.get("comment"),
        content=cleaned,
        sections=_parse_sections_from_content(content),
    )
    save_revision_snapshot(title, lang, revision)
    return revision


def _load_or_fetch_revision(title: str, lang: str, revid: int) -> Revision:
    cached = load_revision_snapshot(title, lang, revid)
    if cached:
        if not cached.sections:
            cached.sections = _parse_sections_from_content(cached.content or "")
        return cached

    return _fetch_revision_by_id(title, lang, revid)


def compute_diff(title: str, lang: str, revid_a: int, revid_b: int) -> DiffResponse:
    rev_a = _load_or_fetch_revision(title, lang, revid_a)
    rev_b = _load_or_fetch_revision(title, lang, revid_b)

    text_a = rev_a.content or ""
    text_b = rev_b.content or ""

    overall_similarity = _safe_similarity(text_a, text_b)

    sections_a: Dict[str, Section] = {
        _normalize_title(section.title): section for section in (rev_a.sections or [])
    }
    sections_b: Dict[str, Section] = {
        _normalize_title(section.title): section for section in (rev_b.sections or [])
    }

    sections_added = [
        section.title
        for key, section in sections_b.items()
        if key not in sections_a
    ]

    sections_removed = [
        section.title
        for key, section in sections_a.items()
        if key not in sections_b
    ]

    sections_modified: List[SectionDiff] = []

    for key in set(sections_a.keys()) & set(sections_b.keys()):
        old_section = sections_a[key]
        new_section = sections_b[key]

        if (old_section.clean_content or "") != (new_section.clean_content or ""):
            sections_modified.append(
                SectionDiff(
                    title=new_section.title,
                    old_content=old_section.clean_content,
                    new_content=new_section.clean_content,
                    similarity=_safe_similarity(
                        old_section.clean_content or "", new_section.clean_content or ""
                    ),
                )
            )

    return DiffResponse(
        title=title,
        lang=lang,
        revid_a=revid_a,
        revid_b=revid_b,
        overall_similarity=overall_similarity,
        sections_added=sections_added,
        sections_removed=sections_removed,
        sections_modified=sections_modified,
    )