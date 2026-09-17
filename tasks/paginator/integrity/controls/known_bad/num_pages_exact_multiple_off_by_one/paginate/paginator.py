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

    @property
    def num_pages(self):
        if self.total_items == 0:
            return 0
        # BUG: floor(total/per_page) + 1 — the classic "divide then add one
        # for the remainder" mistake. Matches the correct ceiling when
        # total_items % per_page != 0, but overcounts by exactly one page
        # when total_items is an exact multiple of per_page.
        return self.total_items // self.per_page + 1

    def page(self, n):
        if n < 1 or n > self.num_pages:
            raise ValueError(f"page {n} out of range (1..{self.num_pages})")
        start_index = (n - 1) * self.per_page
        end_index = min(start_index + self.per_page, self.total_items)
        return Page(
            number=n,
            start_index=start_index,
            end_index=end_index,
            has_previous=n > 1,
            has_next=n < self.num_pages,
        )
