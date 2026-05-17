"""Crop browser chrome (top) + system taskbar/dock (bottom) z screenshotow.

Cross-platform (Windows / macOS / Linux). Wymaga: Pillow.

Instalacja:
    pip install Pillow

Uzycie:
    python crop_screenshots.py <folder_ze_screenshotami>
    python crop_screenshots.py <folder> --pattern "Screenshot*.png"
    python crop_screenshots.py <folder> --out <folder_wyjsciowy>

Domyslnie:
    - pattern: wszystkie *.png w folderze
    - out: <folder>/_crops/
    - wykrywa gore (koniec chrome przegladarki = pierwszy ciemny wiersz)
      i dol (start taskbara/docka = ostatni czysto czarny wiersz)
    - uzywa wspolnych granic dla wszystkich plikow (rowne wysokosci - dobre do siatki)
"""
import argparse
import sys
from pathlib import Path
from typing import Optional, Tuple

try:
    from PIL import Image
except ImportError:
    sys.exit("[FAIL] Brak Pillow. Zainstaluj: pip install Pillow")


def find_chrome_boundary(img):
    # type: (Image.Image) -> Tuple[int, int]
    """Znajdz y_top (koniec chrome) i y_bot (start taskbara/docka).

    Zalozenie: strona ma ciemne (czarne) tlo. Chrome przegladarki to jasne tlo
    (RGB ~235+), taskbar Windows/dock macOS to ciemny obszar z jasnymi ikonami.
    """
    w, h = img.size
    rgb = img.convert("RGB")
    # Probkujemy gesto po calej szerokosci - 3 kolumny to za malo,
    # bo ikony taskbara/docka czesto wypadaja miedzy probkami.
    n_samples = max(32, w // 20)
    cols = [int(i * (w - 1) / (n_samples - 1)) for i in range(n_samples)]

    def row_avg(y: int) -> float:
        return sum(sum(rgb.getpixel((x, y))) / 3 for x in cols) / len(cols)

    def row_max(y: int) -> int:
        return max(max(rgb.getpixel((x, y))) for x in cols)

    # Gora: pierwszy wiersz z avg < 60 (czarne tlo strony).
    y_top = 0
    for y in range(0, h // 3):
        if row_avg(y) < 60:
            y_top = y
            break

    # Dol: szukamy GORNEJ krawedzi taskbara/docka. Taskbar = pasek na dole
    # z jasnymi ikonami (max > 150). Znajdujemy najwyzej polozony wiersz z
    # jasnym pikselem w dolnej 1/3 obrazu - to gorna krawedz ikon taskbara.
    y_bot = h
    bright_threshold = 150
    search_from = (2 * h) // 3
    for y in range(search_from, h):
        if row_max(y) > bright_threshold:
            y_bot = y
            break

    return y_top, y_bot


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def crop_folder(src: Path, pattern: str, out: Path) -> int:
    # Default ("*.png") - lapiemy WSZYSTKIE obrazki case-insensitive,
    # zeby uzytkownik nie musial sie martwic o .PNG vs .png vs .jpg.
    if pattern == "*.png":
        files = sorted(p for p in src.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    else:
        files = sorted(src.glob(pattern))
    if not files:
        # Pokaz co naprawde jest w folderze - latwiej zdiagnozowac.
        all_files = sorted(p.name for p in src.iterdir() if p.is_file())
        print(f"[WARN] Brak pasujacych plikow w: {src}")
        print(f"       pattern: {pattern}")
        if all_files:
            print(f"       Pliki w folderze ({len(all_files)}):")
            for n in all_files[:20]:
                print(f"         - {n}")
            if len(all_files) > 20:
                print(f"         ... i {len(all_files) - 20} wiecej")
        else:
            print("       Folder jest pusty.")
        return 1

    print(f"[INFO] Znaleziono {len(files)} plikow")
    boundaries = []
    for f in files:
        with Image.open(f) as img:
            y_top, y_bot = find_chrome_boundary(img)
            boundaries.append((f, img.size, y_top, y_bot))
            print(f"  {f.name}: {img.size}  top={y_top}  bot={y_bot}  H={y_bot - y_top}")

    common_top = max(b[2] for b in boundaries)
    common_bot = min(b[3] for b in boundaries)
    print(f"\n[INFO] Wspolny crop: top={common_top}  bot={common_bot}  H={common_bot - common_top}")

    out.mkdir(parents=True, exist_ok=True)
    for f, (w, _h), _yt, _yb in boundaries:
        with Image.open(f) as img:
            cropped = img.crop((0, common_top, w, common_bot))
            out_path = out / f.name
            cropped.save(out_path, "PNG", optimize=True)
            print(f"  [OK] {out_path.name}  {cropped.size}  {out_path.stat().st_size // 1024} KB")

    print(f"\n[DONE] Pliki w: {out}")
    return 0


def pick_folder_gui():
    # type: () -> Optional[Path]
    """Pokaz GUI do wyboru folderu (dwuklik na .py bez argumentow)."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError:
        print("[FAIL] Tkinter niedostepny. Podaj folder jako argument:")
        print("       python3 crop_screenshots.py /sciezka/do/folderu")
        return None

    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Wybierz folder ze screenshotami")
    if not folder:
        return None
    return Path(folder)


def main() -> int:
    ap = argparse.ArgumentParser(description="Crop browser chrome + taskbar/dock from screenshots.")
    ap.add_argument("folder", type=Path, nargs="?", help="Folder ze screenshotami (jak pusty - GUI picker)")
    ap.add_argument("--pattern", default="*.png", help="Glob (np. 'Screenshot*.png'). Default: *.png")
    ap.add_argument("--out", type=Path, default=None, help="Folder wyjsciowy. Default: <folder>/_crops/")
    args = ap.parse_args()

    if args.folder is None:
        picked = pick_folder_gui()
        if picked is None:
            print("[INFO] Anulowano.")
            return 0
        src = picked.expanduser().resolve()
    else:
        # Wklejona sciezka czesto ma cudzyslowy lub spacje na koncach.
        raw = str(args.folder).strip().strip('"').strip("'")
        src = Path(raw).expanduser().resolve()

    if not src.is_dir():
        print(f"[FAIL] Folder nie istnieje: {src}")
        try:
            input("Nacisnij Enter aby zamknac...")
        except EOFError:
            pass
        return 2

    out = args.out.expanduser().resolve() if args.out else src / "_crops"
    rc = crop_folder(src, args.pattern, out)
    # Pauza zeby okno terminala nie zniknelo po dwukliku
    if args.folder is None:
        try:
            input("\nNacisnij Enter aby zamknac...")
        except EOFError:
            pass
    return rc


raise SystemExit(main())
