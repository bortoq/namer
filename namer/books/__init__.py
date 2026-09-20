"""Public facade of the isolated books domain."""
from namer.books.detect import BOOK_EXTENSIONS, book_kind, find_book_files, is_book_path
from namer.books.fusion import fuse_opinions
from namer.books.identify import build_query, identify_book
from namer.books.naming import (
    TEMPLATE_BOOK,
    TEMPLATE_BOOK_SERIES,
    generate_book_name,
    render_book_name,
)
from namer.books.pipeline import process_books_directory

__all__ = [
    'BOOK_EXTENSIONS', 'book_kind', 'find_book_files', 'is_book_path',
    'build_query', 'identify_book', 'fuse_opinions',
    'TEMPLATE_BOOK', 'TEMPLATE_BOOK_SERIES',
    'generate_book_name', 'render_book_name', 'process_books_directory',
]
