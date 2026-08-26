"""Decode HEIC previews via the Windows Shell / WIC. Originals are read-only.

Uses the same thumbnail provider as Explorer when the HEIF Image Extensions
are installed. No extra Python packages and no GPL image codecs.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import POINTER, byref, c_void_p, c_wchar_p, sizeof
from ctypes.wintypes import DWORD, HBITMAP, LONG, WORD
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

_SIIGBF_RESIZETOFIT = 0x00
_SIIGBF_BIGGERSIZEOK = 0x01
_SIIGBF_THUMBNAILONLY = 0x08
_GENERIC_READ = 0x80000000
_WIC_DECODE_ON_DEMAND = 0
_COINIT_APARTMENTTHREADED = 0x2
_CLSCTX_INPROC_SERVER = 0x1
_RPC_E_CHANGED_MODE = -2147417850  # 0x80010106
_DIB_RGB_COLORS = 0
_BI_RGB = 0
HRESULT = ctypes.HRESULT if hasattr(ctypes, "HRESULT") else ctypes.c_long


class _GUID(ctypes.Structure):
    _fields_ = (
        ("Data1", DWORD),
        ("Data2", WORD),
        ("Data3", WORD),
        ("Data4", ctypes.c_ubyte * 8),
    )


class _SIZE(ctypes.Structure):
    _fields_ = (("cx", LONG), ("cy", LONG))


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = (
        ("biSize", DWORD),
        ("biWidth", LONG),
        ("biHeight", LONG),
        ("biPlanes", WORD),
        ("biBitCount", WORD),
        ("biCompression", DWORD),
        ("biSizeImage", DWORD),
        ("biXPelsPerMeter", LONG),
        ("biYPelsPerMeter", LONG),
        ("biClrUsed", DWORD),
        ("biClrImportant", DWORD),
    )


def _guid(text: str) -> _GUID:
    hexed = text.replace("-", "")
    data4 = (ctypes.c_ubyte * 8)(*[int(hexed[16 + index : 18 + index], 16) for index in range(0, 16, 2)])
    return _GUID(int(hexed[0:8], 16), int(hexed[8:12], 16), int(hexed[12:16], 16), data4)


_IID_ISHELL_ITEM_IMAGE_FACTORY = _guid("bcc18b79-ba16-442f-80c4-8a59c30c463b")
_CLSID_WIC_FACTORY = _guid("cacaf262-9370-4615-a13b-9f5539da4c0a")
_IID_WIC_FACTORY = _guid("ec5ec8a9-c395-4314-9c77-54d7a935ff70")
_GUID_24BGR = _guid("6fddc324-4e03-4bfe-b185-3d77768dc90c")


def decode_heic_preview(path: Path, *, size: int = 256) -> Image.Image | None:
    """Return a Pillow image via Windows Shell/WIC, or None.

    Works for HEIC and other formats Explorer can preview (RAW, video).
    """

    return decode_windows_thumbnail(path, size=size)


def decode_windows_thumbnail(path: Path, *, size: int = 256) -> Image.Image | None:
    """Return a Shell/WIC thumbnail for any path Windows can preview."""

    if sys.platform != "win32":
        return None
    try:
        image = _shell_thumbnail(path, size)
        if image is not None:
            return image
        return _wic_frame(path)
    except Exception:  # noqa: BLE001 - Shell/WIC failures must not abort import
        logger.debug("Windows thumbnail decode failed for %s", path.name, exc_info=True)
        return None


def _com_func(obj: c_void_p, index: int, restype, *argtypes):
    vptr = ctypes.cast(obj, POINTER(c_void_p))[0]
    slot = ctypes.cast(vptr, POINTER(c_void_p))[index]
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(slot)


def _release(obj: c_void_p | None) -> None:
    if not obj:
        return
    try:
        _com_func(obj, 2, ctypes.c_ulong)(obj)
    except OSError:
        return


def _ensure_com() -> None:
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx.argtypes = [c_void_p, DWORD]
    ole32.CoInitializeEx.restype = HRESULT
    status = int(ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED))
    if status < 0 and status != _RPC_E_CHANGED_MODE:
        logger.debug("CoInitializeEx returned 0x%08X", status & 0xFFFFFFFF)


def _shell_thumbnail(path: Path, size: int) -> Image.Image | None:
    _ensure_com()
    factory = c_void_p()
    shell32 = ctypes.windll.shell32
    shell32.SHCreateItemFromParsingName.restype = HRESULT
    shell32.SHCreateItemFromParsingName.argtypes = [c_wchar_p, c_void_p, POINTER(_GUID), POINTER(c_void_p)]
    status = shell32.SHCreateItemFromParsingName(
        str(path.resolve()),
        None,
        byref(_IID_ISHELL_ITEM_IMAGE_FACTORY),
        byref(factory),
    )
    if status < 0 or not factory:
        return None
    bitmap = HBITMAP()
    try:
        get_image = _com_func(factory, 3, HRESULT, _SIZE, ctypes.c_int, POINTER(HBITMAP))
        flags = _SIIGBF_THUMBNAILONLY | _SIIGBF_BIGGERSIZEOK | _SIIGBF_RESIZETOFIT
        status = get_image(factory, _SIZE(size, size), flags, byref(bitmap))
    finally:
        _release(factory)
    if status < 0 or not bitmap:
        return None
    try:
        return _hbitmap_to_image(bitmap)
    finally:
        ctypes.windll.gdi32.DeleteObject(bitmap)


def _hbitmap_to_image(handle: HBITMAP) -> Image.Image | None:
    gdi32 = ctypes.windll.gdi32
    gdi32.GetDIBits.argtypes = [
        ctypes.c_void_p,
        HBITMAP,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    hdc = ctypes.windll.user32.GetDC(None)
    if not hdc:
        return None
    try:
        header = _BITMAPINFOHEADER()
        header.biSize = sizeof(_BITMAPINFOHEADER)
        gdi32.GetDIBits(hdc, handle, 0, 0, None, byref(header), _DIB_RGB_COLORS)
        width, height = header.biWidth, abs(header.biHeight)
        if width <= 0 or height <= 0 or width > 8192 or height > 8192:
            return None
        header.biBitCount = 24
        header.biCompression = _BI_RGB
        header.biHeight = -height
        stride = (width * 3 + 3) & ~3
        buffer = (ctypes.c_ubyte * (stride * height))()
        copied = gdi32.GetDIBits(
            hdc,
            handle,
            0,
            height,
            ctypes.cast(buffer, c_void_p),
            byref(header),
            _DIB_RGB_COLORS,
        )
        if copied == 0:
            return None
        raw = bytes(buffer)
        rows = [raw[row * stride : row * stride + width * 3] for row in range(height)]
        packed = b"".join(rows)
        return Image.frombytes("RGB", (width, height), packed, "raw", "BGR")
    finally:
        ctypes.windll.user32.ReleaseDC(None, hdc)


def _wic_frame(path: Path) -> Image.Image | None:
    _ensure_com()
    ole32 = ctypes.windll.ole32
    ole32.CoCreateInstance.restype = HRESULT
    ole32.CoCreateInstance.argtypes = [
        POINTER(_GUID),
        c_void_p,
        DWORD,
        POINTER(_GUID),
        POINTER(c_void_p),
    ]
    factory = c_void_p()
    status = ole32.CoCreateInstance(
        byref(_CLSID_WIC_FACTORY),
        None,
        _CLSCTX_INPROC_SERVER,
        byref(_IID_WIC_FACTORY),
        byref(factory),
    )
    if status < 0 or not factory:
        return None
    decoder = c_void_p()
    source = c_void_p()
    try:
        create = _com_func(
            factory,
            3,
            HRESULT,
            c_wchar_p,
            POINTER(_GUID),
            DWORD,
            ctypes.c_uint,
            POINTER(c_void_p),
        )
        status = create(
            factory,
            str(path.resolve()),
            None,
            _GENERIC_READ,
            _WIC_DECODE_ON_DEMAND,
            byref(decoder),
        )
        if status < 0 or not decoder:
            return None
        get_thumb = _com_func(decoder, 9, HRESULT, POINTER(c_void_p))
        status = get_thumb(decoder, byref(source))
        if status < 0 or not source:
            frame = c_void_p()
            get_frame = _com_func(decoder, 11, HRESULT, ctypes.c_uint, POINTER(c_void_p))
            status = get_frame(decoder, 0, byref(frame))
            source = frame if status >= 0 else c_void_p()
        return _wic_source_to_image(factory, source) if source else None
    finally:
        _release(source)
        _release(decoder)
        _release(factory)


def _wic_source_to_image(factory: c_void_p, source: c_void_p) -> Image.Image | None:
    converter = c_void_p()
    create_conv = _com_func(factory, 10, HRESULT, POINTER(c_void_p))
    if create_conv(factory, byref(converter)) < 0 or not converter:
        return None
    init = _com_func(
        converter,
        8,
        HRESULT,
        c_void_p,
        POINTER(_GUID),
        ctypes.c_int,
        c_void_p,
        ctypes.c_double,
        ctypes.c_int,
    )
    status = init(converter, source, byref(_GUID_24BGR), 0, None, 0.0, 0)
    if status < 0:
        _release(converter)
        return None
    width = ctypes.c_uint()
    height = ctypes.c_uint()
    get_size = _com_func(converter, 3, HRESULT, POINTER(ctypes.c_uint), POINTER(ctypes.c_uint))
    if get_size(converter, byref(width), byref(height)) < 0:
        _release(converter)
        return None
    w, h = int(width.value), int(height.value)
    if w <= 0 or h <= 0 or w > 8192 or h > 8192:
        _release(converter)
        return None
    stride = (w * 3 + 3) & ~3
    buffer = (ctypes.c_ubyte * (stride * h))()
    copy = _com_func(
        converter,
        7,
        HRESULT,
        c_void_p,
        ctypes.c_uint,
        ctypes.c_uint,
        c_void_p,
    )
    status = copy(converter, None, stride, stride * h, ctypes.cast(buffer, c_void_p))
    _release(converter)
    if status < 0:
        return None
    raw = bytes(buffer)
    rows = [raw[row * stride : row * stride + w * 3] for row in range(h)]
    return Image.frombytes("RGB", (w, h), b"".join(rows), "raw", "BGR")
