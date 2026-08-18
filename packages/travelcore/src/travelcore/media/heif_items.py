"""Extract JPEG items from HEIF/HEIC ISO-BMFF boxes. Originals are read-only."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _Box:
    type: bytes
    start: int
    header: int
    size: int

    @property
    def payload_start(self) -> int:
        return self.start + self.header

    @property
    def end(self) -> int:
        return self.start + self.size


def extract_heif_jpeg_item(data: bytes) -> bytes | None:
    """Return the largest ``jpeg``/``jpg `` item payload from a HEIF container."""

    best: bytes | None = None
    best_len = 0
    for item_id, item_type in _item_types(data):
        if item_type not in {b"jpeg", b"jpg "}:
            continue
        payload = _item_payload(data, item_id)
        if payload is None:
            continue
        jpeg = _as_jpeg(payload)
        if jpeg is not None and len(jpeg) > best_len:
            best = jpeg
            best_len = len(jpeg)
    return best


def _item_types(data: bytes) -> list[tuple[int, bytes]]:
    found: list[tuple[int, bytes]] = []
    for box in _walk(data, 0, len(data)):
        if box.type != b"meta":
            continue
        meta_payload = box.payload_start + 4  # FullBox version+flags
        for child in _walk(data, meta_payload, box.end):
            if child.type != b"iinf":
                continue
            found.extend(_parse_iinf(data, child))
    return found


def _parse_iinf(data: bytes, box: _Box) -> list[tuple[int, bytes]]:
    cursor = box.payload_start
    if cursor + 4 > box.end:
        return []
    version = data[cursor]
    cursor += 4
    if version == 0:
        if cursor + 2 > box.end:
            return []
        count = int.from_bytes(data[cursor : cursor + 2], "big")
        cursor += 2
    else:
        if cursor + 4 > box.end:
            return []
        count = int.from_bytes(data[cursor : cursor + 4], "big")
        cursor += 4
    items: list[tuple[int, bytes]] = []
    for nested in _walk(data, cursor, box.end):
        if nested.type != b"infe" or len(items) >= count:
            continue
        parsed = _parse_infe(data, nested)
        if parsed is not None:
            items.append(parsed)
    return items


def _parse_infe(data: bytes, box: _Box) -> tuple[int, bytes] | None:
    cursor = box.payload_start
    if cursor + 4 > box.end:
        return None
    version = data[cursor]
    cursor += 4
    if version >= 2:
        width = 4 if version >= 3 else 2
        if cursor + width + 2 + 4 > box.end:
            return None
        item_id = int.from_bytes(data[cursor : cursor + width], "big")
        cursor += width + 2  # skip protection index
        item_type = data[cursor : cursor + 4]
        return item_id, item_type
    if cursor + 4 > box.end:
        return None
    item_id = int.from_bytes(data[cursor : cursor + 2], "big")
    return item_id, b""


def _item_payload(data: bytes, item_id: int) -> bytes | None:
    idat = b""
    for box in _walk(data, 0, len(data)):
        if box.type == b"meta":
            for child in _walk(data, box.payload_start + 4, box.end):
                if child.type == b"idat":
                    idat = data[child.payload_start : child.end]
                if child.type == b"iloc":
                    loc = _iloc_extent(data, child, item_id)
                    if loc is None:
                        continue
                    construction, offset, length = loc
                    if construction == 1:
                        return idat[offset : offset + length]
                    return data[offset : offset + length]
        if box.type == b"mdat":
            continue
    return None


def _iloc_extent(data: bytes, box: _Box, item_id: int) -> tuple[int, int, int] | None:
    cursor = box.payload_start
    if cursor + 6 > box.end:
        return None
    version = data[cursor]
    cursor += 4
    sizes = data[cursor]
    extra = data[cursor + 1]
    cursor += 2
    offset_size = sizes >> 4
    length_size = sizes & 0x0F
    base_offset_size = extra >> 4
    index_size = extra & 0x0F if version in {1, 2} else 0
    if version < 2:
        if cursor + 2 > box.end:
            return None
        count = int.from_bytes(data[cursor : cursor + 2], "big")
        cursor += 2
        id_size = 2
    else:
        if cursor + 4 > box.end:
            return None
        count = int.from_bytes(data[cursor : cursor + 4], "big")
        cursor += 4
        id_size = 4
    for _ in range(count):
        if cursor + id_size > box.end:
            return None
        current_id = int.from_bytes(data[cursor : cursor + id_size], "big")
        cursor += id_size
        construction = 0
        if version in {1, 2}:
            if cursor + 2 > box.end:
                return None
            construction = data[cursor + 1] & 0x0F
            cursor += 2
        if cursor + 2 + base_offset_size > box.end:
            return None
        cursor += 2  # data_reference_index
        base = int.from_bytes(data[cursor : cursor + base_offset_size], "big") if base_offset_size else 0
        cursor += base_offset_size
        if cursor + 2 > box.end:
            return None
        extent_count = int.from_bytes(data[cursor : cursor + 2], "big")
        cursor += 2
        first: tuple[int, int, int] | None = None
        for _extent in range(extent_count):
            if index_size:
                cursor += index_size
            if cursor + offset_size + length_size > box.end:
                return None
            extent_offset = int.from_bytes(data[cursor : cursor + offset_size], "big") if offset_size else 0
            cursor += offset_size
            extent_length = int.from_bytes(data[cursor : cursor + length_size], "big") if length_size else 0
            cursor += length_size
            if current_id == item_id and first is None:
                first = (construction, base + extent_offset, extent_length)
        if first is not None:
            return first
    return None


def _as_jpeg(payload: bytes) -> bytes | None:
    marker = payload.find(b"\xff\xd8")
    if marker < 0 or marker > 16:
        return None
    blob = payload[marker:]
    if b"\xff\xd9" not in blob:
        return None
    return blob


def _walk(data: bytes, start: int, end: int) -> list[_Box]:
    boxes: list[_Box] = []
    offset = start
    while offset + 8 <= end:
        size = int.from_bytes(data[offset : offset + 4], "big")
        typ = data[offset + 4 : offset + 8]
        header = 8
        if size == 1:
            if offset + 16 > end:
                break
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header = 16
        elif size == 0:
            size = end - offset
        if size < header or offset + size > end:
            break
        boxes.append(_Box(typ, offset, header, size))
        if typ in {b"moov", b"meta", b"dinf", b"iprp", b"ipco", b"iref"}:
            inner_start = offset + header + (4 if typ in {b"meta", b"iref"} else 0)
            boxes.extend(_walk(data, inner_start, offset + size))
        offset += size
    return boxes
