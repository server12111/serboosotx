from dataclasses import dataclass

PAGE_SIZE = 8


@dataclass
class Page:
    offset: int
    limit: int
    page: int
    has_prev: bool
    has_next: bool


def paginate(page: int, total: int, page_size: int = PAGE_SIZE) -> Page:
    page = max(page, 0)
    offset = page * page_size
    has_next = offset + page_size < total
    has_prev = page > 0
    return Page(offset=offset, limit=page_size, page=page, has_prev=has_prev, has_next=has_next)
