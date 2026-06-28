#!/usr/bin/env python3
"""Generate wireframe mockup sketches for pipeline robustness testing."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

BACKEND_DIR = Path(__file__).resolve().parents[1]


def draw_dashboard(path: Path) -> None:
    img = Image.new("RGB", (800, 600), "white")
    d = ImageDraw.Draw(img)

    # Header
    d.rectangle([0, 0, 800, 60], outline="black", width=3)
    d.text((20, 20), "Dashboard", fill="black")

    # Sidebar
    d.rectangle([0, 60, 160, 600], outline="black", width=2)
    d.text((20, 90), "Home", fill="black")
    d.text((20, 130), "Settings", fill="black")
    d.text((20, 170), "Reports", fill="black")

    # Stat card 1
    d.rectangle([200, 100, 470, 220], outline="black", width=2)
    d.text((220, 120), "Revenue", fill="gray")
    d.text((220, 160), "$12,400", fill="black")

    # Stat card 2
    d.rectangle([510, 100, 780, 220], outline="black", width=2)
    d.text((530, 120), "Users", fill="gray")
    d.text((530, 160), "1,284", fill="black")

    img.save(path, "JPEG", quality=90)
    print(f"Wrote {path} ({path.stat().st_size} bytes)")


def draw_list(path: Path) -> None:
    img = Image.new("RGB", (800, 600), "white")
    d = ImageDraw.Draw(img)

    # Header
    d.rectangle([0, 0, 800, 60], outline="black", width=3)
    d.text((20, 20), "Users", fill="black")

    # Search input
    d.rectangle([520, 80, 760, 120], outline="black", width=2)
    d.text((530, 90), "Search...", fill="gray")

    # Table header row
    d.rectangle([40, 150, 760, 190], outline="black", width=2)
    d.text((60, 160), "Name", fill="black")
    d.text((280, 160), "Email", fill="black")
    d.text((520, 160), "Role", fill="black")

    rows = [
        ("Alice Smith", "alice@example.com", "Admin"),
        ("Bob Jones", "bob@example.com", "Editor"),
        ("Carol Lee", "carol@example.com", "Viewer"),
        ("Dan Wu", "dan@example.com", "Editor"),
    ]
    y = 200
    for name, email, role in rows:
        d.rectangle([40, y, 760, y + 50], outline="black", width=1)
        d.text((60, y + 15), name, fill="black")
        d.text((280, y + 15), email, fill="gray")
        d.text((520, y + 15), role, fill="gray")
        y += 50

    img.save(path, "JPEG", quality=90)
    print(f"Wrote {path} ({path.stat().st_size} bytes)")


def main() -> None:
    draw_dashboard(BACKEND_DIR / "test_sketch_dashboard.jpg")
    draw_list(BACKEND_DIR / "test_sketch_list.jpg")


if __name__ == "__main__":
    main()
