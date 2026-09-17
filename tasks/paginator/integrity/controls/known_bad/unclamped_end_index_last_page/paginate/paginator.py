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
        return (self.total_items + self.per_page - 1) // self.per_page

    def page(self, n):
        if n < 1 or n > self.num_pages:
            raise ValueError(f"page {n} out of range (1..{self.num_pages})")
        start_index = (n - 1) * self.per_page
        # BUG: assumes every page is full-sized; never clamps to total_items,
        # so the final (possibly partial) page's end_index runs past the end
        # of the collection.
        end_index = start_index + self.per_page
        return Page(
            number=n,
            start_index=start_index,
            end_index=end_index,
            has_previous=n > 1,
            has_next=n < self.num_pages,
        )
