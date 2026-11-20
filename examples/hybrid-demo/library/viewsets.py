"""library API: BaseViewSet subclasses, auto-routed: `karni make viewset <Model>`."""

from karni.api import Access, BaseViewSet, Owned

from library.models import Book


class BookViewSet(BaseViewSet):
    model = Book
    access = Access(read=Owned("owner"), write=Owned("owner"))
