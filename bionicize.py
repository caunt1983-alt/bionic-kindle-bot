"""Bionic-конвертер EPUB. Оборачивает первую половину каждого слова в <b>."""
from __future__ import annotations

import math
import warnings
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, XMLParsedAsHTMLWarning
from ebooklib import epub, ITEM_DOCUMENT

warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")
warnings.filterwarnings("ignore", category=FutureWarning, module="ebooklib")
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

BOLD_RATIO = 0.5
MIN_WORD_LEN = 4
SKIP_TAGS = {"style", "script", "code", "pre", "b", "strong", "kbd", "samp", "tt"}


def bionic_word(word: str) -> tuple[str, str] | None:
    letters = [c for c in word if c.isalpha()]
    if len(letters) < MIN_WORD_LEN:
        return None
    bold_letters = math.ceil(len(letters) * BOLD_RATIO)
    seen = 0
    cut = 0
    for i, ch in enumerate(word):
        if ch.isalpha():
            seen += 1
            if seen == bold_letters:
                cut = i + 1
                break
    return word[:cut], word[cut:]


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    buf: list[str] = []
    in_space = text[:1].isspace() if text else False
    for ch in text:
        is_space = ch.isspace()
        if is_space != in_space:
            tokens.append("".join(buf))
            buf = [ch]
            in_space = is_space
        else:
            buf.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tokens


def has_forbidden_ancestor(node: NavigableString) -> bool:
    for parent in node.parents:
        name = getattr(parent, "name", None)
        if name and name.lower() in SKIP_TAGS:
            return True
    return False


def process_soup(root, factory) -> int:
    count = 0
    text_nodes = [
        n for n in root.find_all(string=True)
        if isinstance(n, NavigableString) and n.strip() and not has_forbidden_ancestor(n)
    ]
    for node in text_nodes:
        tokens = tokenize(str(node))
        new_parts: list = []
        changed = False
        for tok in tokens:
            if not tok or tok.isspace():
                new_parts.append(NavigableString(tok))
                continue
            result = bionic_word(tok)
            if result is None:
                new_parts.append(NavigableString(tok))
                continue
            bold_part, rest = result
            b_tag = factory.new_tag("b")
            b_tag.string = bold_part
            new_parts.append(b_tag)
            if rest:
                new_parts.append(NavigableString(rest))
            count += 1
            changed = True
        if changed:
            node.replace_with(*new_parts)
    return count


def process_epub(src: Path, dst: Path) -> tuple[int, int]:
    """Возвращает (обработано документов, слов сделано bionic)."""
    book = epub.read_epub(str(src))
    docs = 0
    words = 0
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        # lxml (HTML) корректно ест XHTML + XML-декларацию, в отличие от html.parser и lxml-xml.
        soup = BeautifulSoup(item.content, "lxml")
        body = soup.find("body")
        if body is None:
            continue
        w = process_soup(body, soup)
        if w > 0:
            inner = body.decode_contents()
            item.content = f"<html><body>{inner}</body></html>".encode("utf-8")
            docs += 1
            words += w
    dst.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(dst), book)
    return docs, words
