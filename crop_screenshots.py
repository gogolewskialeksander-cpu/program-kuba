"""Crop browser chrome (top) + system taskbar/dock (bottom) z screenshotow.

Tryby:
    AUTO   - automatyczne wykrycie chrome (gora) i taskbara/docka (dol).
    MANUAL - sam zaznaczasz obszar myszka (przeciagnij prostokat) - dla
             dowolnego wycinka, np. miniatury.

Wejscie: pojedynczy plik LUB caly folder.

Cross-platform (Windows / macOS / Linux). Wymaga: Pillow.

Instalacja:
    pip install Pillow

Uzycie:
    python crop_screenshots.py                      # GUI - wybor pliku/folderu
    python crop_screenshots.py /sciezka/plik.png    # jeden plik (auto)
    python crop_screenshots.py /sciezka/folder      # caly folder (auto)
    python crop_screenshots.py /sciezka --manual    # tryb reczny (rysuj myszka)
    python crop_screenshots.py /sciezka --out /inny/folder

Domyslnie wynik: <folder>/_crops/  (lub obok pliku w trybie 1-pliku)
"""
import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from PIL import Image
except ImportError:
    sys.exit("[FAIL] Brak Pillow. Zainstaluj: pip install Pillow")

# OpenCV jest opcjonalne - jak jest, uzywamy edge detection (precyzyjniej).
# Jak nie ma - fallback na heurystyke jasnosci.
try:
    import cv2
    import numpy as np
    HAS_CV = True
except ImportError:
    HAS_CV = False


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def find_chrome_boundary_cv(img_path):
    # type: (Path) -> Optional[Tuple[int, int]]
    """OpenCV: znajdz granice przez detekcje poziomych krawedzi (Canny).

    Chrome przegladarki ma duzo elementow z poziomymi krawedziami (tabs,
    pasek URL, bookmarks). Taskbar/dock ma wyrazna gorna krawedz.
    Szukamy wierszy, w ktorych co najmniej polowa pikseli to krawedzie.
    """
    if not HAS_CV:
        return None
    gray = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None
    h, w = gray.shape
    edges = cv2.Canny(gray, 50, 150)
    # ile pikseli krawedzi w kazdym wierszu, znormalizowane do [0,1]
    row_density = (edges > 0).sum(axis=1).astype(float) / max(1, w)
    threshold = 0.5

    # Gora: ostatni "mocny" poziomy wiersz w gornych 30% (= koniec chrome).
    y_top = 0
    top_limit = int(h * 0.30)
    for y in range(top_limit - 1, -1, -1):
        if row_density[y] >= threshold:
            y_top = min(y + 1, h)
            break

    # Dol: pierwszy "mocny" poziomy wiersz w dolnych 25% (= gora taskbara).
    y_bot = h
    bot_start = int(h * 0.75)
    for y in range(bot_start, h):
        if row_density[y] >= threshold:
            y_bot = y
            break

    return y_top, y_bot


def find_chrome_boundary(img):
    # type: (Image.Image) -> Tuple[int, int]
    """Znajdz y_top (koniec chrome) i y_bot (start taskbara/docka)."""
    w, h = img.size
    rgb = img.convert("RGB")
    n_samples = max(32, w // 20)
    cols = [int(i * (w - 1) / (n_samples - 1)) for i in range(n_samples)]

    def row_avg(y):
        return sum(sum(rgb.getpixel((x, y))) / 3 for x in cols) / len(cols)

    def row_max(y):
        return max(max(rgb.getpixel((x, y))) for x in cols)

    y_top = 0
    for y in range(0, h // 3):
        if row_avg(y) < 60:
            y_top = y
            break

    y_bot = h
    bright_threshold = 150
    for y in range((2 * h) // 3, h):
        if row_max(y) > bright_threshold:
            y_bot = y
            break

    return y_top, y_bot


def collect_files(src, pattern):
    # type: (Path, str) -> List[Path]
    """Zbierz pliki obrazow: pojedynczy plik lub wszystkie w folderze."""
    if src.is_file():
        return [src]
    if pattern == "*.png":
        return sorted(p for p in src.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    return sorted(src.glob(pattern))


def manual_select_region(img_path):
    # type: (Path) -> Optional[Tuple[int, int, int, int]]
    """Otworz okno tkinter, pozwol uzytkownikowi przeciagnac prostokat.

    Zwraca (left, top, right, bottom) w wspolrzednych ORYGINALNEGO obrazu
    albo None gdy uzytkownik pominal / zamknal okno.
    """
    try:
        import tkinter as tk
        from PIL import ImageTk
    except ImportError as e:
        print(f"[FAIL] Tryb reczny wymaga tkinter + Pillow: {e}")
        return None

    img = Image.open(img_path)
    w, h = img.size

    root = tk.Tk()
    root.title(f"Zaznacz obszar: {img_path.name}  (przeciagnij myszka)")

    screen_w = root.winfo_screenwidth() - 80
    screen_h = root.winfo_screenheight() - 200
    scale = min(screen_w / w, screen_h / h, 1.0)
    disp_w = max(1, int(w * scale))
    disp_h = max(1, int(h * scale))

    img_disp = img.resize((disp_w, disp_h))
    photo = ImageTk.PhotoImage(img_disp)

    canvas = tk.Canvas(root, width=disp_w, height=disp_h, cursor="crosshair", bg="black")
    canvas.pack()
    canvas.create_image(0, 0, anchor="nw", image=photo)

    state = {"start": None, "rect_id": None, "box": None}

    def on_press(e):
        state["start"] = (e.x, e.y)
        if state["rect_id"] is not None:
            canvas.delete(state["rect_id"])
        state["rect_id"] = canvas.create_rectangle(
            e.x, e.y, e.x, e.y, outline="red", width=2
        )

    def on_drag(e):
        if state["start"] and state["rect_id"] is not None:
            x0, y0 = state["start"]
            canvas.coords(state["rect_id"], x0, y0, e.x, e.y)

    def on_release(e):
        if not state["start"]:
            return
        x0, y0 = state["start"]
        x1, y1 = e.x, e.y
        l = int(min(x0, x1) / scale)
        t = int(min(y0, y1) / scale)
        r = int(max(x0, x1) / scale)
        b = int(max(y0, y1) / scale)
        l = max(0, min(l, w))
        t = max(0, min(t, h))
        r = max(0, min(r, w))
        b = max(0, min(b, h))
        if r - l >= 5 and b - t >= 5:
            state["box"] = (l, t, r, b)
            info.config(text=f"Zaznaczono: {r - l} x {b - t} px  (kliknij OK aby zapisac)")
        else:
            state["box"] = None
            info.config(text="Zaznaczenie za male - sprobuj jeszcze raz")

    def on_ok():
        root.destroy()

    def on_skip():
        state["box"] = None
        root.destroy()

    canvas.bind("<Button-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Return>", lambda e: on_ok())
    root.bind("<Escape>", lambda e: on_skip())

    bar = tk.Frame(root)
    bar.pack(fill="x")
    tk.Button(bar, text="OK (Enter)", command=on_ok, width=12).pack(side="left", padx=4, pady=4)
    tk.Button(bar, text="Pomin (Esc)", command=on_skip, width=12).pack(side="left", padx=4, pady=4)
    info = tk.Label(bar, text="Przeciagnij myszka aby zaznaczyc prostokat")
    info.pack(side="right", padx=10)

    root.mainloop()
    img.close()
    return state["box"]


def pick_path_gui():
    # type: () -> Optional[Path]
    """GUI: zapytaj uzytkownika czy chce wybrac plik czy folder."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError:
        print("[FAIL] Tkinter niedostepny. Podaj sciezke jako argument:")
        print("       python3 crop_screenshots.py /sciezka/do/pliku_lub_folderu")
        return None

    root = tk.Tk()
    root.withdraw()
    use_file = messagebox.askyesno(
        "Wybor zrodla",
        "Co chcesz wybrac?\n\nTAK = pojedynczy PLIK (zdjecie)\nNIE = caly FOLDER",
    )
    if use_file:
        chosen = filedialog.askopenfilename(
            title="Wybierz zdjecie",
            filetypes=[
                ("Obrazy", "*.png *.jpg *.jpeg *.webp *.bmp"),
                ("Wszystkie pliki", "*.*"),
            ],
        )
    else:
        chosen = filedialog.askdirectory(title="Wybierz folder ze screenshotami")
    root.destroy()
    if not chosen:
        return None
    return Path(chosen)


def warn_no_files(src, pattern):
    # type: (Path, str) -> None
    if src.is_file():
        return
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


def auto_boxes(files):
    # type: (List[Path]) -> List[Tuple[Path, Tuple[int, int, int, int]]]
    """Auto-wykryj wspolny crop dla wszystkich plikow."""
    mode = "OpenCV edges" if HAS_CV else "brightness fallback"
    print(f"[INFO] Auto detection: {mode}")
    rows = []
    for f in files:
        cv_result = find_chrome_boundary_cv(f) if HAS_CV else None
        with Image.open(f) as img:
            if cv_result is not None:
                y_top, y_bot = cv_result
            else:
                y_top, y_bot = find_chrome_boundary(img)
            rows.append((f, img.size, y_top, y_bot))
            print(f"  {f.name}: {img.size}  top={y_top}  bot={y_bot}  H={y_bot - y_top}")

    common_top = max(r[2] for r in rows)
    common_bot = min(r[3] for r in rows)
    common_w = min(r[1][0] for r in rows)
    print(f"\n[INFO] Wspolny crop: top={common_top}  bot={common_bot}  H={common_bot - common_top}")
    return [(f, (0, common_top, common_w, common_bot)) for f, _, _, _ in rows]


def manual_boxes(files):
    # type: (List[Path]) -> List[Tuple[Path, Tuple[int, int, int, int]]]
    """Pozwol uzytkownikowi recznie zaznaczyc obszar dla kazdego pliku."""
    items = []
    for f in files:
        print(f"  [GUI] Otwieram: {f.name}")
        box = manual_select_region(f)
        if box is None:
            print(f"    [SKIP] {f.name}")
            continue
        items.append((f, box))
        print(f"    [SEL] {f.name} -> {box}")
    return items


def save_crops(items, out):
    # type: (List[Tuple[Path, Tuple[int, int, int, int]]], Path) -> None
    out.mkdir(parents=True, exist_ok=True)
    for f, box in items:
        with Image.open(f) as img:
            cropped = img.crop(box)
            out_path = out / f.name
            cropped.save(out_path, "PNG", optimize=True)
            print(f"  [OK] {out_path.name}  {cropped.size}  {out_path.stat().st_size // 1024} KB")
    print(f"\n[DONE] Pliki w: {out}")


def process(src, pattern, out, manual):
    # type: (Path, str, Path, bool) -> int
    files = collect_files(src, pattern)
    if not files:
        warn_no_files(src, pattern)
        return 1

    print(f"[INFO] Znaleziono {len(files)} plik(ow). Tryb: {'RECZNY' if manual else 'AUTO'}")
    if manual:
        items = manual_boxes(files)
    else:
        if not HAS_CV:
            print("[HINT] Zainstaluj OpenCV dla lepszej auto-detekcji:")
            print("       pip install opencv-python numpy")
        items = auto_boxes(files)

    if not items:
        print("[WARN] Nic nie zostalo zaznaczone - nic do zapisania.")
        return 1

    save_crops(items, out)
    return 0


def main():
    # type: () -> int
    ap = argparse.ArgumentParser(description="Crop screenshots: auto (chrome+taskbar) lub recznie myszka.")
    ap.add_argument("path", type=Path, nargs="?", help="Plik LUB folder. Pusty = GUI picker.")
    ap.add_argument("--pattern", default="*.png", help="Glob dla folderu. Default: wszystkie obrazy.")
    ap.add_argument("--out", type=Path, default=None, help="Folder wyjsciowy. Default: <folder>/_crops/")
    ap.add_argument("--manual", "-m", action="store_true", help="Tryb reczny: rysuj prostokat myszka.")
    args = ap.parse_args()

    if args.path is None:
        picked = pick_path_gui()
        if picked is None:
            print("[INFO] Anulowano.")
            return 0
        src = picked.expanduser().resolve()
    else:
        raw = str(args.path).strip().strip('"').strip("'")
        src = Path(raw).expanduser().resolve()

    if not src.exists():
        print(f"[FAIL] Sciezka nie istnieje: {src}")
        try:
            input("Nacisnij Enter aby zamknac...")
        except EOFError:
            pass
        return 2

    if args.out:
        out = args.out.expanduser().resolve()
    elif src.is_file():
        out = src.parent / "_crops"
    else:
        out = src / "_crops"

    rc = process(src, args.pattern, out, args.manual)

    if args.path is None:
        try:
            input("\nNacisnij Enter aby zamknac...")
        except EOFError:
            pass
    return rc


raise SystemExit(main())
