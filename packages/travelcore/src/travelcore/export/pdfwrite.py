"""Minimal PDF writer: one JPEG image per page. No PyMuPDF.

``PageLayout /TwoPageRight`` opens the cover on the right so the following
sheets pair as verso|recto spreads.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from travelcore.exceptions import ExportError

_POINTS_PER_MM = 72.0 / 25.4


def write_jpeg_pdf(
    pages: Sequence[tuple[bytes, int, int]],
    destination: Path,
    *,
    width_mm: float,
    height_mm: float,
) -> Path:
    """Write DeviceRGB JPEG pages. ``pages`` is ``(jpeg_bytes, pixel_w, pixel_h)``."""

    if not pages:
        raise ExportError("PDF ohne Seiten.")
    page_w = float(width_mm) * _POINTS_PER_MM
    page_h = float(height_mm) * _POINTS_PER_MM
    count = len(pages)
    kids = " ".join(f"{3 + 3 * index} 0 R" for index in range(count))
    bodies: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R /PageLayout /TwoPageRight >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode("ascii"),
    ]
    for jpeg, pixel_w, pixel_h in pages:
        page_id = len(bodies) + 1
        content_id = page_id + 1
        image_id = page_id + 2
        content = f"q\n{page_w:.2f} 0 0 {page_h:.2f} 0 0 cm\n/Im Do\nQ\n".encode("ascii")
        bodies.append(
            (
                f"<< /Type /Page /Parent 2 0 R "
                f"/MediaBox [0 0 {page_w:.2f} {page_h:.2f}] "
                f"/Contents {content_id} 0 R "
                f"/Resources << /XObject << /Im {image_id} 0 R >> >> >>"
            ).encode("ascii")
        )
        bodies.append(f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"endstream")
        header = (
            f"<< /Type /XObject /Subtype /Image /Width {int(pixel_w)} /Height {int(pixel_h)} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
            f"/Length {len(jpeg)} >>\nstream\n"
        ).encode("ascii")
        bodies.append(header + jpeg + b"\nendstream")

    buf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(bodies, start=1):
        offsets.append(len(buf))
        buf.extend(f"{index} 0 obj\n".encode("ascii"))
        buf.extend(body)
        if not body.endswith(b"\n"):
            buf.extend(b"\n")
        buf.extend(b"endobj\n")
    xref_at = len(buf)
    buf.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    buf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    buf.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode("ascii")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(bytes(buf))
    return destination
