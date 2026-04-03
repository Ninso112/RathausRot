from dataclasses import dataclass, field
from typing import List


@dataclass
class CouncilItem:
    id: str
    title: str
    url: str
    item_type: str
    date: str
    body_text: str
    pdf_texts: List[str] = field(default_factory=list)
    pdf_urls: List[str] = field(default_factory=list)
    source_system: str = "unknown"
    city_name: str = ""


@dataclass
class Session:
    id: str
    title: str
    date: str
    url: str
    body_name: str = ""
