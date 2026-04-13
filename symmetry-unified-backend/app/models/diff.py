from typing import List, Optional

from pydantic import BaseModel


class SectionDiff(BaseModel):
    title: str
    old_content: Optional[str] = None
    new_content: Optional[str] = None
    similarity: Optional[float] = None


class DiffResponse(BaseModel):
    title: str
    lang: str
    revid_a: int
    revid_b: int
    overall_similarity: float
    sections_added: List[str]
    sections_removed: List[str]
    sections_modified: List[SectionDiff]