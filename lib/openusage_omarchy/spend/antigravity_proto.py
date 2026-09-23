"""Antigravity protobuf decoder. Generation fields only."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GenerationEvent:
    model_id: str | None
    label: str | None
    input_tokens: int
    output_tokens: int
    cache_read: int
    timestamp_s: int


def decode_varint(blob: bytes, offset: int = 0) -> tuple[int, int] | None:
    if offset < 0 or offset >= len(blob):
        return None
    value = 0
    for index in range(10):
        pos = offset + index
        if pos >= len(blob):
            return None
        byte = blob[pos]
        payload = byte & 0x7F
        if index == 9 and payload > 1:
            return None
        value |= payload << (index * 7)
        if not byte & 0x80:
            return value, pos + 1
    return None


def _field(number: int, blob: bytes) -> tuple[str, bytes | int] | None:
    offset = 0
    while offset < len(blob):
        tag = decode_varint(blob, offset)
        if tag is None:
            return None
        value, nxt = tag
        field_no = value >> 3
        if field_no == 0:
            return None
        wire = value & 0x7
        if wire == 0:
            decoded = decode_varint(blob, nxt)
            if decoded is None:
                return None
            number_value, end = decoded
            if field_no == number:
                return "varint", number_value
            offset = end
        elif wire == 2:
            decoded = decode_varint(blob, nxt)
            if decoded is None:
                return None
            length, start = decoded
            if length > len(blob) - start or length < 0:
                return None
            end = start + length
            if field_no == number:
                return "bytes", blob[start:end]
            offset = end
        elif wire in (1, 5):
            width = 8 if wire == 1 else 4
            if len(blob) - nxt < width:
                return None
            offset = nxt + width
        else:
            return None
    return None


def bytes_field(number: int, blob: bytes) -> bytes | None:
    found = _field(number, blob)
    if found is None or found[0] != "bytes":
        return None
    result = found[1]
    return bytes(result) if isinstance(result, (bytes, bytearray)) else None


def varint_field(number: int, blob: bytes) -> int | None:
    found = _field(number, blob)
    if found is None or found[0] != "varint":
        return None
    value = found[1]
    return int(value) if isinstance(value, int) else None


def _stamp(message: bytes) -> int | None:
    seconds = varint_field(1, message)
    if seconds is None or seconds <= 0:
        return None
    return seconds


def step_timestamp(step: bytes) -> int | None:
    inner = bytes_field(1, step)
    return _stamp(inner) if inner is not None else None


def _text(number: int, message: bytes) -> str | None:
    raw = bytes_field(number, message)
    if raw is None:
        return None
    try:
        text = bytes(raw).decode("utf-8").strip()
    except UnicodeError:
        return None
    return text or None


def generation_event(blob: bytes, step: bytes | None = None) -> GenerationEvent | None:
    wrapped = bytes_field(1, blob)
    if wrapped is None:
        return None
    model_id = _text(19, wrapped)
    label = _text(21, wrapped)
    usage = bytes_field(4, wrapped)
    if usage is None:
        return None
    system = varint_field(1, usage) or 0
    inp = varint_field(2, usage) or 0
    output = varint_field(3, usage) or 0
    read = varint_field(5, usage) or 0
    try:
        billable = system + inp
    except OverflowError:
        return None
    generated = inp != 0 or output != 0 or read != 0
    if model_id is None and label is None and not generated:
        return None
    if not generated and billable == 0:
        return None
    timing = bytes_field(9, wrapped)
    embedded = None
    if timing is not None:
        inner = bytes_field(4, timing)
        embedded = _stamp(inner) if inner is not None else None
    stamp = embedded or (step_timestamp(step) if step is not None else None)
    if stamp is None:
        return None
    return GenerationEvent(
        model_id=model_id, label=label, input_tokens=billable,
        output_tokens=output, cache_read=read, timestamp_s=stamp)
