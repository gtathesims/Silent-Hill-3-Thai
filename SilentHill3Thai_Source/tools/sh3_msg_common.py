#!/usr/bin/env python3
"""Shared verified helpers for Silent Hill 3 PC msg.arc text tooling."""

from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass


EXPECTED_BASELINE_SHA256 = 'B9F987CD0E995F9AF7936E679F536A7B611724916E67875A8FCC92A7D5480DD9'
FONT_ENTRY_INDICES = (276, 277, 343)
ENGLISH_ENTRY_INDICES = tuple(range(0, 259, 2)) + (266, 270)
TOKEN_RE = re.compile(r'⟦([0-9A-F]{2}|[0-9A-F]{4})⟧')


@dataclass(frozen=True)
class ArchiveEntry:
    index: int
    offset: int
    metadata: int
    packed_size: int
    unpacked_size: int


@dataclass(frozen=True)
class MessageTable:
    pointers_words: tuple[int, ...]
    records: tuple[bytes, ...]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def archive_entries(data: bytes) -> tuple[ArchiveEntry, ...]:
    if len(data) < 0x10:
        raise ValueError('Archive is too small')
    count = struct.unpack_from('<I', data, 4)[0]
    if count != 371:
        raise ValueError(f'Unexpected msg.arc entry count: {count}')
    entries: list[ArchiveEntry] = []
    for index in range(count):
        offset, metadata, packed, unpacked = struct.unpack_from(
            '<IIII', data, 0x10 + index * 0x10
        )
        if packed != unpacked:
            raise ValueError(f'Compressed entry {index} is not supported')
        if offset + packed > len(data):
            raise ValueError(f'Entry {index} extends beyond the archive')
        entries.append(ArchiveEntry(index, offset, metadata, packed, unpacked))
    return tuple(entries)


def entry_payload(data: bytes, entry: ArchiveEntry) -> bytes:
    return data[entry.offset : entry.offset + entry.packed_size]


def parse_message_table(payload: bytes) -> MessageTable:
    if len(payload) < 2:
        raise ValueError('Message table is too small')
    count = struct.unpack_from('<H', payload, 0)[0]
    if count == 0 or count * 2 > len(payload):
        raise ValueError(f'Invalid message record count: {count}')
    pointers = struct.unpack_from(f'<{count}H', payload, 0)
    if pointers[0] != count:
        raise ValueError('First message pointer does not equal the table word count')
    if any(left > right for left, right in zip(pointers, pointers[1:])):
        raise ValueError('Message pointers are not monotonic')
    if pointers[-1] * 2 > len(payload):
        raise ValueError('Final message pointer exceeds entry size')
    end_words = pointers[1:] + (len(payload) // 2,)
    records = tuple(payload[start * 2 : end * 2] for start, end in zip(pointers, end_words))
    if any(len(record) % 2 for record in records):
        raise ValueError('Message record is not word-aligned')
    return MessageTable(tuple(pointers), records)


def rebuild_message_table(records: list[bytes] | tuple[bytes, ...]) -> bytes:
    if not records:
        raise ValueError('Cannot rebuild an empty message table')
    if any(len(record) % 2 for record in records):
        raise ValueError('All message records must be word-aligned')
    cursor_words = len(records)
    pointers: list[int] = []
    for record in records:
        if cursor_words > 0xFFFF:
            raise ValueError('Message pointer exceeds the 16-bit format limit')
        pointers.append(cursor_words)
        cursor_words += len(record) // 2
    if cursor_words > 0x10000:
        raise ValueError('Rebuilt message entry exceeds the 16-bit format limit')
    return struct.pack(f'<{len(pointers)}H', *pointers) + b''.join(records)


def rebuild_archive(source: bytes, payloads: list[bytes]) -> bytes:
    entries = archive_entries(source)
    if len(payloads) != len(entries):
        raise ValueError('Payload count does not match the archive')
    first_data_offset = entries[0].offset
    prefix = bytearray(source[:first_data_offset])
    cursor = first_data_offset
    output_payloads: list[bytes] = []
    for entry, payload in zip(entries, payloads):
        table_offset = 0x10 + entry.index * 0x10
        struct.pack_into('<I', prefix, table_offset, cursor)
        struct.pack_into('<I', prefix, table_offset + 8, len(payload))
        struct.pack_into('<I', prefix, table_offset + 12, len(payload))
        output_payloads.append(payload)
        cursor += len(payload)
    return bytes(prefix) + b''.join(output_payloads)


def tokenize_record(record: bytes) -> str:
    output: list[str] = []
    index = 0
    while index < len(record):
        value = record[index]
        if value == 0xFF:
            if index + 1 >= len(record):
                raise ValueError('Dangling 0xFF control byte')
            output.append(f'⟦FF{record[index + 1]:02X}⟧')
            index += 2
        elif value >= 0x60:
            output.append(f'⟦{value:02X}⟧')
            index += 1
        else:
            output.append(chr(value + 0x20))
            index += 1
    return ''.join(output)


def token_signature(markup: str) -> tuple[str, ...]:
    # tokenize_record also wraps extended single-byte *glyphs* (for example the
    # accented e in cafe) so translators can round-trip them.  They are text,
    # not layout/control codes, and may legitimately disappear in Thai.  Only
    # compare the verified record framing/layout controls.
    structural_single_byte = {'80', '8E', '90'}
    return tuple(
        token
        for match in TOKEN_RE.finditer(markup)
        for token in (match.group(1),)
        if token in structural_single_byte or (len(token) == 4 and token.startswith('FF'))
    )


def visible_text(markup: str) -> str:
    return TOKEN_RE.sub('', markup).strip()


def encode_markup(markup: str, thai_to_code: dict[str, int]) -> bytes:
    # A legacy one-byte renderer cannot place Thai combining marks correctly.
    # Phase 7 therefore maps frequently used precomposed sequences (for example
    # "ที่") to one byte.  Always try the longest mapping at the current cursor
    # before falling back to a single character.
    mapping_keys = tuple(sorted(thai_to_code, key=lambda item: (-len(item), item)))
    output = bytearray()
    cursor = 0
    while cursor < len(markup):
        match = TOKEN_RE.match(markup, cursor)
        if match:
            token = match.group(1)
            output.extend(bytes.fromhex(token))
            cursor = match.end()
            continue
        char = markup[cursor]
        codepoint = ord(char)
        if 0x20 <= codepoint <= 0x7F:
            output.append(codepoint - 0x20)
        else:
            mapped = next(
                (key for key in mapping_keys if markup.startswith(key, cursor)),
                None,
            )
            if mapped is None:
                raise ValueError(
                    f'No game encoding at U+{codepoint:04X} {char!r}'
                )
            mapped_code = thai_to_code[mapped]
            if mapped_code < 0xE0:
                output.append(mapped_code)
            elif mapped_code < 0x7FFF:
                # SH3's text reader treats E0 as an escape followed by a
                # little-endian 16-bit glyph index.  This preserves all legacy
                # one-byte mappings while opening the existing multibyte path.
                output.extend((0xE0, mapped_code & 0xFF, mapped_code >> 8))
            else:
                raise ValueError(
                    f'Game glyph code for {mapped!r} is outside 0000-7FFE'
                )
            cursor += len(mapped)
            continue
        cursor += 1
    return bytes(output)


def stable_id(entry_index: int, record_index: int) -> str:
    return f'msg-e{entry_index:03d}-r{record_index:03d}'
