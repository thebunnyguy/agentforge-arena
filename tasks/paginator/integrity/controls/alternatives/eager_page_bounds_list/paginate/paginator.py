class Page:
    def __init__(self, number, start_index, end_index, has_previous, has_next):
        self.number = number
        self.start_index = start_index
        self.end_index = end_index
        self.has_previous = has_previous
        self.has_next = has_next


class Paginator:
    def __init__(self, total_items, per_page):
        self.total_items = total_items
        self.per_page = per_page
        # Eagerly precompute the (start, end) bounds of every page up front,
        # rather than deriving them arithmetically on each .page() call.
        bounds = []
        start = 0
        while start < total_items:
            end = start + per_page
            if end > total_items:
                end = total_items
            bounds.append((start, end))
            start = end
        self._page_bounds = bounds

    @property
    def num_pages(self):
        return len(self._page_bounds)

    def page(self, n):
        if n < 1 or n > self.num_pages:
            raise ValueError(f"page {n} out of range (1..{self.num_pages})")
        start_index, end_index = self._page_bounds[n - 1]
        return Page(
            number=n,
            start_index=start_index,
            end_index=end_index,
            has_previous=n > 1,
            has_next=n < self.num_pages,
        )
