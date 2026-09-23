"""Create browser-sized WebP textures and a manifest from the root image/ folder.

Run with the project's Python environment: backend/.venv/Scripts/python.exe
frontend/scripts/generate_gallery.py. Original images are never changed.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "image"
PUBLIC = ROOT / "frontend" / "public" / "gallery"
MANIFEST = ROOT / "frontend" / "src" / "data" / "gallery.json"
EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".avif"}


def main() -> None:
    originals = sorted((p for p in SOURCE.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS), key=lambda p: p.name.casefold())
    if not originals:
        raise SystemExit("No usable images found in project image/")
    # ponytail: cap large collections at 36 evenly spaced images; revisit only if curation is needed.
    chosen = originals if len(originals) <= 40 else [originals[round(i * (len(originals) - 1) / 35)] for i in range(36)]
    PUBLIC.mkdir(parents=True, exist_ok=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    items = []
    for index, source in enumerate(chosen, 1):
        image_id = f"{index:03d}"
        output = PUBLIC / f"{image_id}.webp"
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            image.save(output, "WEBP", quality=82, method=6)
            width, height = image.size
        items.append({
            "id": image_id,
            "image": f"/gallery/{image_id}.webp",
            "title": source.stem.removeprefix("【哲风壁纸】"),
            "width": width,
            "height": height,
        })
        print(f"{source.name} -> {output.name} ({width}x{height}, {output.stat().st_size // 1024} KiB)")
    MANIFEST.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(items)} local gallery textures and {MANIFEST}")


if __name__ == "__main__":
    main()
