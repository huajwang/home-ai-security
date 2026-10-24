"""Render a page and hand it to the IPP printer already on the LAN."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from hub import config

_FONTS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
)


def uri_from_avahi(text: str, name: str) -> str:
    """Read one IPP URI from `avahi-browse -rptk _ipp._tcp` output."""
    wanted = name.lower()
    for line in text.splitlines():
        if wanted not in line.lower() or not line.startswith("="):
            continue
        parts = line.split(";")
        if len(parts) < 9:
            continue
        address = parts[7].strip()
        port = parts[8].strip() or "631"
        resource = "ipp/print"
        for field in parts[9:]:
            piece = field.strip().strip('"')
            if piece.startswith("rp="):
                resource = piece.split("=", 1)[1].strip("/")
        if address:
            return f"ipp://{address}:{port}/{resource}"
    return ""


def lp_command(path: Path, name: str, uri: str = "") -> list[str]:
    del uri
    return ["lp", "-d", name, "-t", "Home AI", str(path)]


def print_document(title: str, body: str, pictures: Optional[list[Path]] = None) -> dict[str, Any]:
    page = _render(title, body, pictures or [])
    if page is None:
        return {"ok": False, "message": "Could not render the page."}
    result = _send(page)
    return result


def _send(path: Path) -> dict[str, Any]:
    name = config.PRINTER_NAME or "ET788C77E2BF92"
    uri = config.PRINTER_URI or _discover(name)
    if shutil.which("lp") is None:
        return {"ok": False, "message": "The printer command is not installed on the hub."}
    completed = subprocess.run(lp_command(path, name), capture_output=True, text=True, timeout=60)
    if completed.returncode == 0:
        return {"ok": True, "message": "Sent to the printer."}
    detail = (completed.stderr or completed.stdout or "").lower()
    if uri and ("unknown destination" in detail or "not found" in detail or "no such" in detail):
        added = _add_queue(name, uri)
        if added:
            retry = subprocess.run(lp_command(path, name), capture_output=True, text=True, timeout=60)
            if retry.returncode == 0:
                return {"ok": True, "message": "Sent to the printer."}
            return {"ok": False, "message": (retry.stderr or "The printer did not accept the page.").strip()[:300]}
    detail = (completed.stderr or completed.stdout or "The printer did not accept the page.").strip()
    return {"ok": False, "message": detail[:300]}


def _discover(name: str) -> str:
    browse = shutil.which("avahi-browse")
    if browse is None:
        return ""
    try:
        completed = subprocess.run(
            [browse, "-rptk", "_ipp._tcp"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return uri_from_avahi(completed.stdout, name)


def _add_queue(name: str, uri: str) -> bool:
    lpadmin = shutil.which("lpadmin")
    if lpadmin is None:
        return False
    completed = subprocess.run(
        [lpadmin, "-p", name, "-E", "-v", uri, "-m", "everywhere"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.returncode == 0


def _render(title: str, body: str, pictures: list[Path]) -> Optional[Path]:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return _render_text(title, body)
    font = _font(ImageFont, 36)
    small = _font(ImageFont, 28)
    width = 1240
    margin = 64
    lines = _wrap(title, font, width - margin * 2) + [""] + _wrap(body, small, width - margin * 2)
    line_height = 48
    height = margin * 2 + line_height * max(len(lines), 1) + 40
    images = []
    for picture in pictures:
        try:
            image = Image.open(picture).convert("RGB")
        except OSError:
            continue
        image.thumbnail((width - margin * 2, 900))
        images.append(image)
        height += image.height + 24
    page = Image.new("RGB", (width, max(height, 400)), "white")
    draw = ImageDraw.Draw(page)
    y = margin
    for index, line in enumerate(lines):
        draw.text((margin, y), line, fill="black", font=font if index == 0 else small)
        y += line_height
    y += 12
    for image in images:
        page.paste(image, (margin, y))
        y += image.height + 24
    dest = Path(tempfile.mkdtemp(prefix="home-ai-print-")) / "note.png"
    page.save(dest, format="PNG")
    return dest


def _font(image_font: Any, size: int) -> Any:
    for path in _FONTS:
        if Path(path).is_file():
            try:
                return image_font.truetype(path, size=size)
            except OSError:
                continue
    return image_font.load_default()


def _wrap(text: str, font: Any, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in (text or "").splitlines() or [""]:
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            trial = current + char
            try:
                size = font.getlength(trial)
            except Exception:
                size = len(trial) * 18
            if current and size > width:
                lines.append(current)
                current = char
            else:
                current = trial
        if current:
            lines.append(current)
    return lines or [""]


def _render_text(title: str, body: str) -> Optional[Path]:
    dest = Path(tempfile.mkdtemp(prefix="home-ai-print-")) / "note.txt"
    dest.write_text(f"{title}\n\n{body}\n", encoding="utf-8")
    return dest
