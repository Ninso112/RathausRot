from dataclasses import dataclass, field


@dataclass
class CouncilItem:
    id: str
    title: str
    url: str
    item_type: str
    date: str
    body_text: str
    pdf_texts: list[str] = field(default_factory=list)
    pdf_urls: list[str] = field(default_factory=list)
    source_system: str = "unknown"
    city_name: str = ""


@dataclass
class Session:
    id: str
    title: str
    date: str
    url: str
    body_name: str = ""
