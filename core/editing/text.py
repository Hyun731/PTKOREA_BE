"""Block text <-> token string, so a text edit (by a person or a model) can change words without
inventing numbers.

Token string syntax, one string per paragraph:
  {{F-…}} {{DF-…}} a fact (or derived fact) chip. Only facts the deck already shows may be used; the chip keeps the
                  formatter/display the deck already computed for that fact.
  {{p:N}}         keep the N-th non-text part of the original block as is (date, meta, link, quote, name).
  [[name]]        a fixed name (may contain digits). Only names the deck already uses are allowed.
  **text**        bold text.
Everything else is plain text, and plain text must not contain digits (QC UNBOUND_NUMBER).
"""
from __future__ import annotations

import re
from typing import Iterable

from core.schemas.slidespec import Paragraph, Part, SlideSpec, TableBlock, TextBlock

TOKEN = re.compile(r"\{\{(D?F-[0-9a-f]{20})\}\}|\{\{p:(\d+)\}\}|\[\[(.+?)\]\]|\*\*(.+?)\*\*")
DIGIT = re.compile(r"\d")


class TextEditError(ValueError):
    pass


def kept_parts(block: TextBlock) -> list[Part]:
    """Non-text, non-fact parts of a block in reading order: what {{p:N}} refers to."""
    return [p for para in block.paragraphs for p in para.parts if p.type not in ("text", "fact")]


def to_tokens(block: TextBlock) -> list[str]:
    kept = kept_parts(block)
    out = []
    for para in block.paragraphs:
        s = ""
        for p in para.parts:
            if p.type == "text":
                s += f"**{p.text}**" if p.bold and (p.text or "").strip() else (p.text or "")
            elif p.type == "fact":
                s += "{{" + (p.fact_id or "") + "}}"
            else:
                s += "{{p:" + str(kept.index(p)) + "}}"
        out.append(s)
    return out


def readable(block: TextBlock) -> list[str]:
    """What the slide shows, paragraph by paragraph (for model context)."""
    return [p.plain() for p in block.paragraphs]


class DeckVocabulary:
    """Facts and names already present in a deck — the only ones an edit may reuse."""

    def __init__(self, slides: Iterable[SlideSpec]):
        self.facts: dict[str, Part] = {}
        self.names: set[str] = set()
        for s in slides:
            for p in _all_parts(s):
                if p.type == "fact" and p.fact_id and p.fact_id not in self.facts:
                    self.facts[p.fact_id] = p
                elif p.type == "name" and p.text:
                    self.names.add(p.text)


def _all_parts(slide: SlideSpec):
    for b in slide.blocks:
        if isinstance(b, TextBlock):
            for para in b.paragraphs:
                yield from para.parts
        elif isinstance(b, TableBlock):
            for row in b.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        yield from para.parts


def from_tokens(lines: list[str], original: TextBlock, vocab: DeckVocabulary, *, allow_digits: bool = False) -> list[Paragraph]:
    """Token strings -> paragraphs. Paragraph-level style (bullet, color, weight) is carried over
    position by position from the original block; new paragraphs copy the last original one."""
    kept = kept_parts(original)
    paras: list[Paragraph] = []
    for i, line in enumerate(lines):
        base = original.paragraphs[min(i, len(original.paragraphs) - 1)] if original.paragraphs else Paragraph()
        bullet = base.bullet
        if bullet and line.startswith(bullet):  # the model may echo the bullet literally
            line = line[len(bullet):].lstrip()
        parts: list[Part] = []
        pos = 0
        for m in TOKEN.finditer(line):
            if m.start() > pos:
                parts.append(_text(line[pos:m.start()], allow_digits))
            fid, kept_i, name, bold = m.groups()
            if fid:
                if fid not in vocab.facts:
                    raise TextEditError(f"덱에 없는 수치 {fid}는 쓸 수 없습니다")
                parts.append(vocab.facts[fid].model_copy())
            elif kept_i is not None:
                k = int(kept_i)
                if k >= len(kept):
                    raise TextEditError(f"원래 문장에 없는 조각 {{{{p:{k}}}}}")
                parts.append(kept[k].model_copy())
            elif name is not None:
                if name not in vocab.names and DIGIT.search(name) and not allow_digits:
                    raise TextEditError(f"덱에 없는 이름 [[{name}]]에 숫자를 쓸 수 없습니다")
                parts.append(Part(type="name", text=name))
            else:
                p = _text(bold, allow_digits)
                p.bold = True
                parts.append(p)
            pos = m.end()
        if pos < len(line):
            parts.append(_text(line[pos:], allow_digits))
        paras.append(base.model_copy(update={"parts": parts}))
    return paras


def _text(s: str, allow_digits: bool) -> Part:
    if not allow_digits and DIGIT.search(s):
        raise TextEditError(f"근거 없는 숫자: '{s.strip()}' — 숫자는 덱에 있는 수치 칩으로만 넣을 수 있습니다")
    return Part(type="text", text=s)
