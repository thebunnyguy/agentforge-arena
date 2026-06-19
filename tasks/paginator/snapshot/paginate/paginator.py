class Page:
    """One page of a paginated collection (a plain data holder).

    Attributes:
      * ``number``       - the 1-based page number.
      * ``start_index``  - 0-based inclusive index of the first item.
      * ``end_index``    - 0-based exclusive index just past the last item.
      * ``has_previous`` - True when this is not the first page.
      * ``has_next``     - True when this is not the last page.
    """

    def __init__(self, number, start_index, end_index, has_previous, has_next):
        self.number = number
        self.start_index = start_index
        self.end_index = end_index
        self.has_previous = has_previous
        self.has_next = has_next


class Paginator:
    """Splits a collection of ``total_items`` into pages of ``per_page`` items.

    Contract:
      * ``num_pages`` is ``ceil(total_items / per_page)``, and ``0`` when
        ``total_items`` is ``0``.
      * ``page(n)`` returns a :class:`Page` for the 1-based page number ``n``
        with ``start_index`` (0-based, inclusive), ``end_index`` (0-based,
        exclusive; equals ``total_items`` on the last page), ``has_previous``
        (``n > 1``) and ``has_next`` (``n < num_pages``).
      * ``page(n)`` raises ``ValueError`` if ``n < 1`` or ``n > num_pages``.

    STUB: num_pages and page() are not implemented yet.
    """

    def __init__(self, total_items, per_page):
        self.total_items = total_items
        self.per_page = per_page

    @property
    def num_pages(self):
        raise NotImplementedError("Paginator.num_pages is not implemented yet")

    def page(self, n):
        raise NotImplementedError("Paginator.page is not implemented yet")
