#!/usr/bin/env python3
"""
split_grid.py — split a photographed or PDF character-practice grid into one image per cell.

How it works:
  1. Finds the outer bordered rectangle in the page (via color thresholding, a
     morphological filter that keeps only long straight lines, and contour
     detection) and reads its 4 corners, even if the photo was taken at a slight
     angle. The grid can be red, green or blue, or "dark" for grayscale scans;
     --line-color auto (the default) picks per page.
  2. Perspective-warps that region so the grid is perfectly rectilinear.
  3. Detects the internal grid line positions on the rectified image and fits
     them to an evenly-spaced grid (robust to a few lines being faint/obscured
     by ink).
  4. Crops each cell (with a small inward padding so the grid lines aren't
     included) and saves it as its own PNG, named row{R}_col{C}.png.

Usage:
    python3 split_grid.py input.jpg output_dir/ [--cols N] [--rows M]
    python3 split_grid.py input.pdf output_dir/ [--pages 3 | 3-7 | 1,4,9-11] [--dpi N]

With a PDF input, every selected page is rendered to an image and split; its cells
are named page{P}_row{R}_col{C}.png. Omit --pages to do the whole document.

If --cols/--rows are omitted, the script infers the count from the detected
line spacing. If detection looks wrong, pass them explicitly (recommended —
it's the most reliable option since you can just count them once by eye). With
them given, the grid is spaced evenly between the outer borders, which survives
both faint lines and the dotted per-cell guides. For the PDFs here that means:

    python3 split_grid.py 3000行书常用.pdf out/ --cols 11 --rows 15
    python3 split_grid.py "3000行书常用(grayscale).pdf" out/ --cols 11 --rows 15 --pages 2-20
    python3 split_grid.py 常用3500字硬笔行书.pdf out/ --cols 12 --rows 16
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import tempfile

import cv2
import numpy as np

LINE_COLORS = ("auto", "red", "green", "blue", "dark")


def line_mask(img, color, loose=False):
    """255 where a pixel could be grid-line ink of the given color.

    For a named color, that channel must beat the other two by a margin. "dark" is for
    grayscale scans: anything noticeably darker than the paper. That also catches the
    characters, so pair it with keep_long_lines(). `loose` lowers the thresholds to
    pick up faint/anti-aliased line pixels once we already know where the grid is.
    """
    if color == "dark":
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(int)
        paper = np.median(gray)  # the page is mostly blank paper
        return ((paper - gray) > (12 if loose else 20)).astype(np.uint8) * 255
    b, g, r = cv2.split(img.astype(int))
    main, other1, other2 = {"red": (r, g, b), "green": (g, r, b), "blue": (b, r, g)}[
        color
    ]
    diff, floor = (15, 60) if loose else (30, 100)
    return (
        ((main - other1) > diff) & ((main - other2) > diff) & (main > floor)
    ).astype(np.uint8) * 255


def keep_long_lines(mask, min_len, horizontal=True, vertical=True):
    """Keep only straight horizontal/vertical runs at least min_len px long.

    Strips out character strokes, dashed/dotted guides and the diagonal guides of a
    米字格, leaving the solid grid lines.
    """
    out = np.zeros_like(mask)
    if horizontal:
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (min_len, 1))
        out |= cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    if vertical:
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_len))
        out |= cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    return out


def _corner_line_mask(img, color):
    mask = line_mask(img, color)
    # Thicken a copy so lines that are slightly tilted (photos) survive the opening, then
    # use it only to choose which of the original pixels to keep.
    thick = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
    lines = keep_long_lines(thick, max(15, min(img.shape[:2]) // 40))
    return mask & cv2.dilate(lines, np.ones((3, 3), np.uint8), iterations=1)


def detect_line_color(img):
    """Guess the grid color: whichever of red/green/blue has the most line-shaped pixels,
    or "dark" if none has a meaningful amount (e.g. a grayscale page)."""
    counts = {
        c: np.count_nonzero(_corner_line_mask(img, c)) for c in ("red", "green", "blue")
    }
    best = max(counts, key=counts.get)
    return best if counts[best] > 0.002 * img.shape[0] * img.shape[1] else "dark"


def get_outer_corners(img, color):
    mask = _corner_line_mask(img, color)
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            corners = order_points(approx.reshape(-1, 2).astype(np.float32))
            # A blob that merged with something else (e.g. a dark scan edge) can give a
            # quad with repeated corners; skip it rather than warp to garbage.
            if len({tuple(p) for p in corners}) == 4:
                return corners
    raise RuntimeError(
        "Could not find a 4-cornered outer border. Crop closer to "
        "the grid before running, try a different --line-color, or "
        "supply corners manually."
    )


def order_points(pts):
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).flatten()
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def warp(img, corners):
    tl, tr, br, bl = corners
    width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    dst = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    M = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(img, M, (width, height)), width, height


def find_line_centers(profile, thresh, min_gap=15):
    above = profile > thresh
    runs, in_run, start = [], False, 0
    for i, v in enumerate(above):
        if v and not in_run:
            in_run, start = True, i
        elif not v and in_run:
            in_run = False
            runs.append((start, i - 1))
    if in_run:
        runs.append((start, len(above) - 1))
    merged = []
    for s, e in runs:
        if merged and s - merged[-1][1] < min_gap:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return [(s + e) / 2 for s, e in merged]


def fit_grid(centers, n_lines, anchor=False):
    centers = np.array(centers)
    if anchor:
        # We know how many lines there should be, and the outermost detected ones are
        # the outer border the image was warped to — so just space the grid evenly
        # between them. Robust to interior lines being missed (faint print) or to
        # extra ones being picked up (the dotted per-cell guides).
        spacing = (centers[-1] - centers[0]) / (n_lines - 1)
        return centers[0] + spacing * np.arange(n_lines)
    spacing0 = np.median(np.diff(centers))
    idx = np.round((centers - centers[0]) / spacing0).astype(int)
    A = np.vstack([idx, np.ones_like(idx)]).T
    spacing, offset = np.linalg.lstsq(A, centers, rcond=None)[0]
    return offset + spacing * np.arange(n_lines)


def detect_grid_lines(warped, axis, color, n_lines_hint=None, thresh_frac=0.15):
    mask = line_mask(warped, color, loose=True)
    # axis=0 sums down columns, so it's looking for vertical lines; axis=1 for horizontal.
    length = warped.shape[1 - axis] // 20
    mask = keep_long_lines(
        mask, max(15, length), horizontal=axis == 1, vertical=axis == 0
    )
    profile = mask.sum(axis=axis) / 255
    centers = find_line_centers(profile, profile.max() * thresh_frac)
    if len(centers) < 2:
        raise RuntimeError(
            f"found {len(centers)} grid line(s) along axis {axis}; "
            "this page probably isn't a character grid"
        )
    n_lines = n_lines_hint if n_lines_hint else len(centers)
    return fit_grid(centers, n_lines, anchor=n_lines_hint is not None)


def parse_pages(spec, n_pages):
    """Turn '3', '3-7', '1,4,9-11' into a sorted list of 1-based page numbers."""
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", part)
        if not m:
            raise SystemExit(f"Bad --pages part {part!r}; expected N or A-B")
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        if lo > hi:
            raise SystemExit(f"Bad --pages range {part!r}: {lo} is after {hi}")
        if lo < 1 or hi > n_pages:
            raise SystemExit(f"--pages {part!r} is outside the document (1-{n_pages})")
        pages.update(range(lo, hi + 1))
    if not pages:
        raise SystemExit("--pages selected no pages")
    return sorted(pages)


def _pymupdf():
    """The PyMuPDF module if it's installed, else None (we fall back to poppler)."""
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # PyMuPDF < 1.24 only exposes the fitz name
        except ImportError:
            return None
    return pymupdf


def _pdf_page_count(path):
    pymupdf = _pymupdf()
    if pymupdf is not None:
        with pymupdf.open(path) as doc:
            return doc.page_count

    if shutil.which("pdfinfo"):
        out = subprocess.run(
            ["pdfinfo", path], capture_output=True, text=True, check=True
        ).stdout
        m = re.search(r"^Pages:\s*(\d+)", out, re.M)
        if m:
            return int(m.group(1))
    if shutil.which("pdftoppm"):
        raise SystemExit(
            "Need pdfinfo (poppler) to count PDF pages, or install PyMuPDF "
            "(pip install pymupdf)."
        )
    raise SystemExit(
        "No PDF backend found. Install PyMuPDF (pip install pymupdf) or "
        "poppler-utils (provides pdftoppm/pdfinfo)."
    )


def render_pdf_pages(path, pages, dpi):
    """Yield (page_number, BGR image) for each requested page, one at a time."""
    pymupdf = _pymupdf()
    if pymupdf is not None:
        with pymupdf.open(path) as doc:
            for n in pages:
                pix = doc.load_page(n - 1).get_pixmap(dpi=dpi)
                buf = np.frombuffer(pix.samples, np.uint8).reshape(
                    pix.height, pix.width, pix.n
                )
                if pix.n == 1:
                    img = cv2.cvtColor(buf, cv2.COLOR_GRAY2BGR)
                elif pix.n == 4:
                    img = cv2.cvtColor(buf, cv2.COLOR_RGBA2BGR)
                else:
                    img = cv2.cvtColor(buf, cv2.COLOR_RGB2BGR)
                yield n, img
        return

    if not shutil.which("pdftoppm"):
        raise SystemExit(
            "No PDF backend found. Install PyMuPDF (pip install pymupdf) or "
            "poppler-utils (provides pdftoppm/pdfinfo)."
        )
    with tempfile.TemporaryDirectory() as tmp:
        for n in pages:
            prefix = os.path.join(tmp, f"page{n}")
            subprocess.run(
                [
                    "pdftoppm",
                    "-r",
                    str(dpi),
                    "-f",
                    str(n),
                    "-l",
                    str(n),
                    "-png",
                    path,
                    prefix,
                ],
                check=True,
            )
            # pdftoppm zero-pads the page suffix to the document's digit count.
            matches = sorted(glob.glob(prefix + "*.png"))
            if not matches:
                raise SystemExit(f"pdftoppm produced no image for page {n}")
            img = cv2.imread(matches[0])
            for f in matches:
                os.remove(f)
            yield n, img


def process_page(img, args, thresh, prefix):
    color = detect_line_color(img) if args.line_color == "auto" else args.line_color
    corners = get_outer_corners(img, color)
    warped, w, h = warp(img, corners)

    col_lines = detect_grid_lines(
        warped,
        axis=0,
        color=color,
        n_lines_hint=(args.cols + 1) if args.cols else None,
        thresh_frac=thresh,
    )
    row_lines = detect_grid_lines(
        warped,
        axis=1,
        color=color,
        n_lines_hint=(args.rows + 1) if args.rows else None,
        thresh_frac=thresh,
    )

    n_cols, n_rows = len(col_lines) - 1, len(row_lines) - 1
    if n_cols < 1 or n_rows < 1:
        raise RuntimeError(f"degenerate grid ({n_rows} rows x {n_cols} cols)")
    print(f"Detected grid: {n_rows} rows x {n_cols} cols ({color} lines)")

    count = 0
    for r in range(n_rows):
        y0, y1 = int(row_lines[r]) + args.pad, int(row_lines[r + 1]) - args.pad
        for c in range(n_cols):
            x0, x1 = int(col_lines[c]) + args.pad, int(col_lines[c + 1]) - args.pad
            cell = warped[y0:y1, x0:x1]
            cv2.imwrite(
                os.path.join(
                    args.output_dir, f"{prefix}row{r + 1:02d}_col{c + 1:02d}.png"
                ),
                cell,
            )
            count += 1
    return count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="image (.jpg/.png/...) or .pdf")
    ap.add_argument("output_dir")
    ap.add_argument(
        "--cols", type=int, default=None, help="number of character columns"
    )
    ap.add_argument("--rows", type=int, default=None, help="number of character rows")
    ap.add_argument(
        "--pad", type=int, default=6, help="inward padding in px to skip the grid line"
    )
    ap.add_argument(
        "--pages",
        default=None,
        help="PDF only: page or range, e.g. 3, 3-7, 1,4,9-11 (default: all)",
    )
    ap.add_argument(
        "--dpi", type=int, default=200, help="PDF only: render resolution (default 200)"
    )
    ap.add_argument(
        "--line-color",
        choices=LINE_COLORS,
        default="auto",
        dest="line_color",
        help="color of the grid lines; 'dark' for grayscale scans. 'auto' (default) "
        "picks per page",
    )
    ap.add_argument(
        "--line-thresh",
        type=float,
        default=None,
        dest="line_thresh",
        help="grid-line detection threshold as a fraction of the max line profile "
        "(default 0.3 for PDF, 0.15 for images)",
    )
    args = ap.parse_args()

    is_pdf = args.input.lower().endswith(".pdf")
    if args.pages and not is_pdf:
        raise SystemExit("--pages only applies to PDF input")
    thresh = (
        args.line_thresh if args.line_thresh is not None else (0.3 if is_pdf else 0.15)
    )

    os.makedirs(args.output_dir, exist_ok=True)

    if not is_pdf:
        img = cv2.imread(args.input)
        if img is None:
            raise SystemExit(f"Could not read {args.input}")
        count = process_page(img, args, thresh, "")
        print(f"Saved {count} cell images to {args.output_dir}/")
        return

    n_pages = _pdf_page_count(args.input)
    pages = (
        parse_pages(args.pages, n_pages) if args.pages else list(range(1, n_pages + 1))
    )

    total, skipped = 0, []
    for n, img in render_pdf_pages(args.input, pages, args.dpi):
        if img is None:
            print(f"warning: page {n} skipped — could not read the rendered image")
            skipped.append(n)
            continue
        print(f"--- page {n} ---")
        try:
            total += process_page(img, args, thresh, f"page{n:02d}_")
        except Exception as e:
            print(f"warning: page {n} skipped — {e}")
            skipped.append(n)
    print(
        f"Saved {total} cell images from {len(pages) - len(skipped)} page(s) to {args.output_dir}/"
    )
    if skipped:
        raise SystemExit(f"skipped page(s): {', '.join(str(n) for n in skipped)}")


if __name__ == "__main__":
    main()
