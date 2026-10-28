#!/usr/bin/env python3
"""
Onde2Vid — transforme des MP3 en vidéos MP4 animées (visualiseur), prêtes pour YouTube.
https://github.com/ulrikadam/Onde2Vid — licence GNU GPL v3.0

  python3 Onde2Vid.py            → ouvre l'interface dans le navigateur
  python3 Onde2Vid.py --batch    → convertit tout input/ sans interface
                                   (avec les derniers réglages enregistrés)
  python3 Onde2Vid.py --batch --force   → reconvertit aussi ce qui existe déjà

Sans terminal : au premier lancement, Onde2Vid crée son raccourci (Mac : Onde2Vid.app,
Windows : menu Démarrer ou double-clic sur Onde2Vid.pyw, Linux : menu des applications).

Dossiers (à côté du script, créés automatiquement) :
  input/            tes MP3 (+ images de fond éventuelles)
  input/jaquettes/  les jaquettes ajoutées depuis l'interface (une par morceau)
  output/           les vidéos MP4

Jaquette d'un morceau, par ordre de priorité :
  1. celle ajoutée depuis l'interface (case à gauche du morceau)
  2. une image portant le même nom que le MP3, dans input/
  3. la pochette intégrée au fichier MP3
  4. la « jaquette par défaut » choisie dans les réglages

FFmpeg : pose le fichier "ffmpeg" (ou ffmpeg.exe) à côté du script,
ou installe-le (Mac : brew install ffmpeg / Windows : winget install ffmpeg).

Aucune bibliothèque Python à installer. Compatible Python 3.9+ (macOS inclus).
"""

from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import math
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from array import array
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

APP_NAME = "Onde2Vid"
FROZEN = bool(getattr(sys, "frozen", False))        # version autonome (sans Python)
MS_STORE = FROZEN and "\\windowsapps\\" in sys.executable.lower()   # installé depuis le Microsoft Store
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))   # fichiers fournis
if os.environ.get("ONDE2VID_DIR"):                  # dossier de travail choisi à la main
    SCRIPT_DIR = Path(os.environ["ONDE2VID_DIR"]).expanduser()
elif FROZEN:                                        # version autonome : Documents/Onde2Vid
    _docs = Path.home() / "Documents"
    SCRIPT_DIR = (_docs if _docs.is_dir() else Path.home()) / APP_NAME
else:                                               # script Python : tout à côté du script
    SCRIPT_DIR = Path(__file__).resolve().parent
INPUT_DIR = SCRIPT_DIR / "input"
COVER_DIR = INPUT_DIR / "jaquettes"
OUTPUT_DIR = SCRIPT_DIR / "output"
SETTINGS_FILE = SCRIPT_DIR / "reglages.json"
TRACKS_FILE = SCRIPT_DIR / "reglages_morceaux.json"   # réglages propres à certains morceaux
TMP = Path(tempfile.mkdtemp(prefix="onde2vid_"))

LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<defs><linearGradient id="o2v" gradientUnits="userSpaceOnUse" x1="12" y1="0" x2="89" y2="0">'
    '<stop offset="0" stop-color="#00e8ff"/><stop offset=".35" stop-color="#168dff"/>'
    '<stop offset=".7" stop-color="#a33dff"/><stop offset="1" stop-color="#ff2bf1"/>'
    '</linearGradient></defs>'
    '<rect width="100" height="100" rx="24" fill="#080a17"/>'
    '<g fill="url(#o2v)" stroke="url(#o2v)">'
    '<rect x="13" y="34" width="10.4" height="33" rx="5.2" stroke="none"/>'
    '<rect x="26.2" y="19.8" width="10.4" height="60.6" rx="5.2" stroke="none"/>'
    '<rect x="39.3" y="28.2" width="10.4" height="45.4" rx="5.2" stroke="none"/>'
    '<rect x="52.5" y="38.1" width="10.4" height="30" rx="5.2" stroke="none"/>'
    '<rect x="65.6" y="44.6" width="9.2" height="19" rx="4.6" stroke="none"/>'
    '<path d="M79.5 50 L79.5 59 L87 54.5 Z" stroke-width="3.2" stroke-linejoin="round"/>'
    '</g></svg>'
)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".alac", ".ogg", ".oga", ".opus", ".wma",
             ".aif", ".aiff", ".aifc", ".caf", ".mp2", ".ac3", ".ape", ".wv", ".mka", ".amr"}   # lus par FFmpeg
STYLES = ["circle", "retro", "mirror", "tunnel", "cubes", "aurora",
          "cqt", "bars", "waves", "spectrum", "scope"]
MASK_STYLES = {"circle", "retro", "mirror", "cubes", "aurora"}   # colorés avec un schéma
ROUND_STYLES = {"circle", "tunnel"}                              # jaquette ronde au centre
PALETTES = ["intensity", "rainbow", "fire", "cool", "magma", "viridis", "plasma", "nebulae"]
SCHEMES = {
    "neon":    ["#00e5ff", "#7a5cff", "#ff3df5"],
    "rainbow": ["#ff3b3b", "#ff9f1a", "#ffe53b", "#3dff7a", "#00d5ff", "#4d6bff", "#b33dff", "#ff3dc1"],
    "fire":    ["#a3001b", "#ff3d00", "#ff9d00", "#ffe14d", "#fff6c9"],
    "ice":     ["#123a8a", "#0a84ff", "#22d3ff", "#d6fbff"],
    "sunset":  ["#5b2bff", "#d43dff", "#ff4d8d", "#ffae42"],
    "vu":      ["#22e05a", "#22e05a", "#b7f03c", "#ffd23d", "#ff3d3d"],
}
AMP_SCHEMES = {"fire", "ice", "vu"}          # dégradé selon la hauteur (sinon selon la fréquence)
SCHEME_NAMES = list(SCHEMES) + ["cover", "duo", "solid"]
QUALITY = {"720p": 720, "1080p": 1080, "1440p": 1440, "4k": 2160}
ASPECTS = {"16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1)}
ROTATE_MINUTES = [1, 2, 3, 5, 10, 15, 20, 30]
PREVIEW_SHORT = 480          # petit côté de l'aperçu vidéo
PREVIEW_SECONDS = 6

DEFAULTS = {
    "style": "circle",        # type de visualiseur
    "colors": "neon",         # schéma de couleurs (nouveaux visualiseurs)
    "color": "#00e5ff",       # couleur principale
    "color2": "#ff3df5",      # 2e couleur (dégradé)
    "palette": "intensity",   # palette du spectrogramme / tunnel
    "viz_size": 35,           # taille du visualiseur (% de l'image)
    "viz_pos": "bottom",      # top / center / bottom
    "glow": True,             # lueur néon
    "sensitivity": 50,        # hauteur des barres
    "image": "__auto__",      # fond : __auto__ (jaquette) / __none__ / nom d'une image de input/
    "layout": "auto",         # jaquette au 1er plan : auto / cover (carrée) / round / fill (aucune)
    "effect": "both",         # effet sur le fond : none / blur / dark / both
    "bg_color": "#000000",    # couleur de fond sans image
    "cover_default": "__none__",  # jaquette si le MP3 n'en a pas
    "pulse": 40,              # pulsation sur les basses (0 = aucune)
    "pulse_bg": True,         # le fond « pompe » aussi
    "title": True,            # afficher le titre
    "title_src": "auto",      # auto (tags puis nom du fichier) / file
    "subtitle": "",           # 2e ligne de texte (ex. nom de la chaîne)
    "progress": False,        # barre de progression en bas
    "fade": True,             # fondu au noir au début et à la fin
    "aspect": "16:9",         # 16:9 / 9:16 (Shorts) / 1:1
    "resolution": "1080p",
    "fps": 30,
    "crf": 20,                # qualité vidéo (plus bas = meilleur)
    "preset": "veryfast",     # vitesse d'encodage
    "compression": "fast",    # fast : puce graphique si possible ; compact : processeur (libx264)
    "audio_kbps": 320,
    "same_for_all": True,     # mêmes réglages pour toute la playlist (sinon : réglages de chaque morceau)
    "rotate": False,          # changer de visualiseur pendant le morceau
    "rotate_styles": [],      # visualiseurs qui alternent (au moins 2)
    "rotate_minutes": 10,     # durée de chaque visualiseur
    "rotate_order": "random", # random (tirage fixe pour chaque morceau) / order
}

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]
FONT_REGULAR = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
]

# ──────────────────────────────────────────────────────────────────────────────
# Outils : ffmpeg, police, petites fonctions
# ──────────────────────────────────────────────────────────────────────────────

TOOLS = {"ffmpeg": None, "drawtext": False, "x264": False, "font": None, "font2": None}
ASSET_LOCK = threading.RLock()      # préparation des images/cartes (un seul fil à la fois)
PREVIEW_LOCK = threading.Lock()
NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}   # pas de fenêtre noire


def prepare_local_binary(path: Path) -> None:
    """Rend exécutable le ffmpeg téléchargé (et, sur Mac, retire le blocage Gatekeeper)."""
    if sys.platform == "win32":
        return
    try:
        path.chmod(path.stat().st_mode | 0o111)
        if sys.platform == "darwin":
            subprocess.run(["xattr", "-d", "com.apple.quarantine", str(path)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def find_ffmpeg() -> str | None:
    for folder in ([BUNDLE_DIR] if FROZEN else []) + [SCRIPT_DIR, BUNDLE_DIR]:
        for name in ("ffmpeg", "ffmpeg.exe"):
            local = folder / name
            if local.is_file():
                prepare_local_binary(local)
                return str(local)
    found = shutil.which("ffmpeg")
    if found:
        return found
    for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if Path(p).is_file():
            return p
    return None


def run_text(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", stdin=subprocess.DEVNULL, **NO_WINDOW)


def ensure_tools() -> None:
    """Détecte ffmpeg et ses capacités (relancé tant que ffmpeg est absent)."""
    if TOOLS["ffmpeg"]:
        return
    ff = find_ffmpeg()
    if not ff:
        return
    TOOLS["ffmpeg"] = ff
    try:
        TOOLS["drawtext"] = "drawtext" in run_text([ff, "-hide_banner", "-filters"]).stdout
        TOOLS["x264"] = "libx264" in run_text([ff, "-hide_banner", "-encoders"]).stdout
    except OSError:
        TOOLS["ffmpeg"] = None
        return
    TOOLS["font"] = next((f for f in FONT_CANDIDATES if Path(f).is_file()), None)
    TOOLS["font2"] = next((f for f in FONT_REGULAR if Path(f).is_file()), TOOLS["font"])


def title_ok() -> bool:
    return bool(TOOLS["drawtext"] and TOOLS["font"])


def ffcolor(hex_color: str) -> str:
    return "0x" + hex_color.lstrip("#").upper()


def ffpath(p) -> str:
    """Chemin utilisable dans un filtre FFmpeg (entre apostrophes)."""
    return Path(p).as_posix().replace(":", "\\:")


def even(n: float) -> int:
    return max(2, int(n) // 2 * 2)


def short_hash(*parts) -> str:
    return hashlib.md5(json.dumps(parts, default=str).encode()).hexdigest()[:16]


def last_line(err: str, default: str = "erreur inconnue") -> str:
    lines = [l for l in (err or "").strip().splitlines() if l.strip()]
    return lines[-1] if lines else default


def ffmpeg(*args, what: str = "FFmpeg") -> None:
    r = run_text([TOOLS["ffmpeg"], "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
                  *[str(a) for a in args]])
    if r.returncode != 0:
        raise RuntimeError(f"{what} : {last_line(r.stderr)}")


def make_asset(out: Path, *args, what: str = "Préparation") -> Path:
    """Crée un fichier avec ffmpeg (écriture atomique ; réutilisé s'il existe déjà)."""
    if out.exists():
        return out
    part = out.with_name(out.stem + ".part" + out.suffix)
    ffmpeg(*args, part, what=what)
    os.replace(part, out)
    return out


def file_key(p: Path | None):
    if not p:
        return None
    try:
        st = p.stat()
        return (str(p), st.st_mtime, st.st_size)
    except OSError:
        return (str(p), 0, 0)


# ──────────────────────────────────────────────────────────────────────────────
# Réglages
# ──────────────────────────────────────────────────────────────────────────────

def _pick(value, allowed, default):
    try:
        if isinstance(default, int) and not isinstance(default, bool):
            value = int(value)
    except (TypeError, ValueError):
        return default
    return value if value in allowed else default


def _clamp_int(value, lo, hi, default):
    try:
        return min(hi, max(lo, int(value)))
    except (TypeError, ValueError):
        return default


def clean_settings(raw) -> dict:
    s = dict(DEFAULTS)
    if isinstance(raw, dict):
        s.update({k: raw[k] for k in DEFAULTS if k in raw})
    hexre = re.compile(r"#[0-9a-fA-F]{6}")
    s["style"] = _pick(s["style"], STYLES, DEFAULTS["style"])
    s["colors"] = _pick(s["colors"], SCHEME_NAMES, "neon")
    s["palette"] = _pick(s["palette"], PALETTES, "intensity")
    for k in ("color", "color2", "bg_color"):
        s[k] = s[k] if isinstance(s[k], str) and hexre.fullmatch(s[k]) else DEFAULTS[k]
    s["viz_size"] = _clamp_int(s["viz_size"], 15, 100, DEFAULTS["viz_size"])
    s["viz_pos"] = _pick(s["viz_pos"], ["top", "center", "bottom"], "bottom")
    s["sensitivity"] = _clamp_int(s["sensitivity"], 0, 100, 50)
    s["image"] = Path(str(s["image"])).name or "__auto__"
    s["layout"] = _pick(s["layout"], ["auto", "cover", "round", "fill"], "auto")
    s["effect"] = _pick(s["effect"], ["none", "blur", "dark", "both"], "both")
    s["cover_default"] = Path(str(s["cover_default"])).name or "__none__"
    s["pulse"] = _clamp_int(s["pulse"], 0, 100, DEFAULTS["pulse"])
    s["title_src"] = _pick(s["title_src"], ["auto", "file"], "auto")
    s["subtitle"] = re.sub(r"\s+", " ", str(s["subtitle"] or ""))[:80]
    for k in ("glow", "pulse_bg", "title", "progress", "fade"):
        s[k] = bool(s[k])
    s["aspect"] = _pick(s["aspect"], list(ASPECTS), "16:9")
    s["resolution"] = _pick(s["resolution"], list(QUALITY), "1080p")
    s["fps"] = _pick(s["fps"], [24, 25, 30, 50, 60], 30)
    s["crf"] = _pick(s["crf"], [14, 17, 20, 23], 20)
    s["preset"] = _pick(s["preset"], ["veryfast", "medium", "slow"], "veryfast")
    s["compression"] = _pick(s["compression"], ["fast", "compact"], "fast")
    s["audio_kbps"] = _pick(s["audio_kbps"], [192, 256, 320], 320)
    s["rotate"] = bool(s["rotate"])
    s["same_for_all"] = bool(s["same_for_all"])
    rs = s["rotate_styles"] if isinstance(s["rotate_styles"], list) else []
    s["rotate_styles"] = list(dict.fromkeys(st for st in rs if st in STYLES))
    s["rotate_minutes"] = _pick(s["rotate_minutes"], ROTATE_MINUTES, 10)
    s["rotate_order"] = _pick(s["rotate_order"], ["random", "order"], "random")
    return s


def load_settings() -> dict:
    try:
        return clean_settings(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return dict(DEFAULTS)


def load_track_settings() -> dict:
    try:
        raw = json.loads(TRACKS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {Path(str(k)).name: clean_settings(v) for k, v in raw.items() if isinstance(v, dict)}


def save_track_settings(t: dict) -> None:
    try:
        TRACKS_FILE.write_text(json.dumps(t, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def save_settings(s: dict) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Analyse des fichiers et jaquettes
# ──────────────────────────────────────────────────────────────────────────────

_probe_cache: dict = {}


def probe(path: Path) -> dict:
    """Durée, pochette intégrée, dimensions et tags (via ffmpeg -i)."""
    empty = {"duration": 0.0, "cover": False, "w": 0, "h": 0, "title": "", "artist": ""}
    if not TOOLS["ffmpeg"]:
        return dict(empty)
    try:
        st = path.stat()
    except OSError:
        return dict(empty)
    key = (str(path), st.st_mtime, st.st_size)
    if key in _probe_cache:
        return _probe_cache[key]
    err = run_text([TOOLS["ffmpeg"], "-hide_banner", "-nostdin", "-i", str(path)]).stderr
    info = dict(empty)
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        info["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    info["cover"] = bool(re.search(r"Video:.*\(attached pic\)", err))
    m = re.search(r"Video: .*?[ ,](\d{2,5})x(\d{2,5})[ ,\[]", err)
    if m:
        info["w"], info["h"] = int(m[1]), int(m[2])
    head = err.split("Duration:", 1)[0]
    for k in ("title", "artist"):
        m = re.search(r"^ {4}%s\s*: (.*)$" % k, head, re.M | re.I)
        if m:
            info[k] = m[1].strip()
    _probe_cache[key] = info
    return info


def list_mp3() -> list[Path]:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    return sorted((f for f in INPUT_DIR.iterdir()
                   if f.is_file() and f.suffix.lower() in AUDIO_EXT and not f.name.startswith(".")),
                  key=lambda p: p.name.lower())


def list_images() -> list[str]:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    return sorted((f.name for f in INPUT_DIR.iterdir()
                   if f.is_file() and f.suffix.lower() in IMAGE_EXT and not f.name.startswith(".")),
                  key=str.lower)


def _stem_image(folder: Path, stem: str) -> Path | None:
    if not folder.is_dir():
        return None
    for f in folder.iterdir():
        if (f.is_file() and f.stem == stem and f.suffix.lower() in IMAGE_EXT
                and not f.name.startswith(".")):
            return f
    return None


def managed_cover(mp3: Path) -> Path | None:
    """Jaquette ajoutée depuis l'interface (input/jaquettes/<nom>.jpg)."""
    return _stem_image(COVER_DIR, mp3.stem)


def same_name_image(mp3: Path) -> Path | None:
    return _stem_image(INPUT_DIR, mp3.stem)


def default_cover(s: dict) -> Path | None:
    name = s.get("cover_default", "__none__")
    if name == "__none__":
        return None
    p = INPUT_DIR / name
    return p if p.is_file() and p.suffix.lower() in IMAGE_EXT else None


def extract_cover(mp3: Path) -> Path | None:
    out = TMP / f"cover_{short_hash(file_key(mp3))}.png"
    try:
        return make_asset(out, "-i", mp3, "-map", "0:v:0", "-frames:v", "1")
    except RuntimeError:
        return None


def cover_source(mp3: Path, s: dict) -> tuple[Path | None, str]:
    """D'où vient la jaquette (sans rien extraire) : added / image / mp3 / default / ''."""
    p = managed_cover(mp3)
    if p:
        return p, "added"
    p = same_name_image(mp3)
    if p:
        return p, "image"
    if probe(mp3)["cover"]:
        return mp3, "mp3"
    p = default_cover(s)
    return (p, "default") if p else (None, "")


def track_cover(mp3: Path, s: dict) -> tuple[Path | None, str]:
    """Image de la jaquette du morceau (la pochette intégrée est extraite si besoin)."""
    p, src = cover_source(mp3, s)
    if src == "mp3":
        p = extract_cover(mp3)
        if not p:
            d = default_cover(s)
            return (d, "default") if d else (None, "")
    return p, src


def set_cover(mp3: Path, data: bytes, ext: str) -> None:
    """Enregistre une jaquette ajoutée pour ce morceau (remplace la précédente)."""
    ext = ext.lower() if ext.lower() in IMAGE_EXT else ".jpg"
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = COVER_DIR / f".{secrets.token_hex(4)}{ext}"
    tmp.write_bytes(data)
    info = probe(tmp)
    if not (info["w"] and info["h"]):
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Ce fichier n'est pas une image lisible")
    old = managed_cover(mp3)
    if old:
        old.unlink(missing_ok=True)
    os.replace(tmp, COVER_DIR / (mp3.stem + ext))


def remove_cover(mp3: Path) -> None:
    p = managed_cover(mp3)
    if p:
        p.unlink(missing_ok=True)


def embed_cover(mp3: Path, s: dict) -> None:
    """Écrit la jaquette dans le fichier MP3 (le son est copié tel quel)."""
    if mp3.suffix.lower() != ".mp3":
        raise RuntimeError("Seuls les MP3 peuvent recevoir une jaquette intégrée")
    img, src = track_cover(mp3, s)
    if not img:
        raise RuntimeError("Ce morceau n'a pas de jaquette à intégrer")
    if src == "mp3":
        raise RuntimeError("La jaquette est déjà dans le MP3")
    part = mp3.with_name("." + mp3.stem + ".jaquette.mp3")
    try:
        ffmpeg("-i", mp3, "-i", img, "-map", "0:a", "-map", "1:v:0", "-c:a", "copy",
               "-c:v", "mjpeg", "-q:v", "2",
               "-vf", "scale='min(1400,iw)':'min(1400,ih)':force_original_aspect_ratio=decrease"
                      ":force_divisible_by=2",
               "-map_metadata", "0", "-id3v2_version", "3",
               "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)",
               "-disposition:v", "attached_pic", part, what="Intégration de la jaquette")
    except RuntimeError:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, mp3)
    if src == "added":
        remove_cover(mp3)


def thumb(path: Path, size: int = 160) -> Path:
    out = TMP / f"th_{short_hash(file_key(path), size)}.jpg"
    return make_asset(out, "-i", path, "-vf",
                      f"scale={size}:{size}:force_original_aspect_ratio=increase,crop={size}:{size}",
                      "-frames:v", "1", "-q:v", "4", what="Miniature")


def cover_colors(img: Path) -> list[str]:
    """Deux couleurs vives tirées de la jaquette (schéma « couleurs de la jaquette »)."""
    out = TMP / f"pal_{short_hash(file_key(img))}.rgb"
    try:
        make_asset(out, "-i", img, "-vf", "scale=24:24:flags=area,format=rgb24",
                   "-frames:v", "1", "-f", "rawvideo")
        data = out.read_bytes()
    except (RuntimeError, OSError):
        return SCHEMES["neon"]
    cand = []
    for i in range(0, len(data) - 2, 3):
        h, sat, v = colorsys.rgb_to_hsv(data[i] / 255, data[i + 1] / 255, data[i + 2] / 255)
        cand.append((sat * (0.35 + v), h, sat, v))
    cand.sort(reverse=True)
    if not cand or cand[0][2] < 0.18:
        return ["#ffffff", "#9aa3b5"]
    best = cand[0]
    second = next((c for c in cand[1:] if min(abs(c[1] - best[1]), 1 - abs(c[1] - best[1])) > 0.1),
                  best)

    def vivid(c):
        r, g, b = colorsys.hsv_to_rgb(c[1], max(0.55, c[2]), max(0.9, c[3]))
        return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
    return [vivid(best), vivid(second)]


def title_text(mp3: Path, s: dict) -> str:
    if s.get("title_src") == "auto":
        info = probe(mp3)
        if info["title"]:
            return f"{info['artist']} – {info['title']}" if info["artist"] else info["title"]
    return re.sub(r"\s+", " ", mp3.stem.replace("_", " ")).strip()


# ──────────────────────────────────────────────────────────────────────────────
# Mise en page
# ──────────────────────────────────────────────────────────────────────────────

def frame_size(s: dict, short: int | None = None) -> tuple[int, int]:
    short = short or QUALITY[s["resolution"]]
    a, b = ASPECTS[s["aspect"]]
    return (even(short * a / b), short) if a >= b else (short, even(short * b / a))


def viz_geometry(s: dict, H: int, U: int) -> tuple[int, int]:
    """Hauteur et position verticale de la bande du visualiseur."""
    if s["viz_size"] >= 100:
        return H, 0
    vh = even(H * s["viz_size"] / 100)
    margin = int(U * 0.04)
    vy = {"top": margin, "center": (H - vh) // 2, "bottom": H - vh - margin}[s["viz_pos"]]
    return vh, even(vy)


def text_items(title: str, sub: str, W: int, H: int, U: int, top: bool):
    """Lignes de texte (texte, taille, y, gras) et hauteur de la bande occupée."""
    if not title and not sub:
        return [], 0
    pad = int(U * 0.05)
    fs = max(int(U / 36), int(min(U / 14, W * 0.9 / max(1, len(title) * 0.56)))) if title else 0
    fs2 = max(int(U / 48), int(min(U / 28, W * 0.9 / max(1, len(sub) * 0.5)))) if sub else 0
    gap = int(fs2 * 0.45) if (title and sub) else 0
    block = (int(fs * 1.2) if title else 0) + gap + (int(fs2 * 1.25) if sub else 0)
    y = pad if top else H - pad - block
    items = []
    if title:
        items.append((title, fs, y, True))
        y += int(fs * 1.2) + gap
    if sub:
        items.append((sub, fs2, y, False))
    return items, even(pad + block + U * 0.02)


def compute_layout(mp3: Path, s: dict, W: int, H: int) -> dict:
    U = min(W, H)
    st = s["style"]
    rnd = st in ROUND_STYLES
    cover, csrc = track_cover(mp3, s)
    if s["image"] == "__none__":
        bg_img = None
    elif s["image"] == "__auto__":
        bg_img = cover
    else:
        p = INPUT_DIR / s["image"]
        bg_img = p if p.is_file() and p.suffix.lower() in IMAGE_EXT else cover

    lay, front = s["layout"], None
    if rnd:
        if lay != "fill":
            front = "round" if cover else "disc"
    elif cover and lay != "fill":
        if lay == "cover":
            front = "square"
        elif lay == "round":
            front = "round"
        else:
            i = probe(cover)
            front = "square" if (i["w"] and i["h"] and i["w"] / i["h"] < 1.45) else None

    title = title_text(mp3, s) if (s["title"] and title_ok()) else ""
    sub = s["subtitle"].strip() if title_ok() else ""
    text_top = (not rnd) and s["viz_pos"] != "top"
    texts, band = text_items(title, sub, W, H, U, text_top)
    vh, vy = viz_geometry(s, H, U)
    L = dict(W=W, H=H, U=U, s=s, style=st, cover=cover, csrc=csrc, bg_img=bg_img, front=front,
             texts=texts, band=band, text_top=text_top, vh=vh, vy=vy)

    top, bottom = 0, H
    if not rnd and vh < H:
        if s["viz_pos"] == "bottom":
            bottom = vy
        elif s["viz_pos"] == "top":
            top = vy + vh
    if band:
        if text_top:
            top = max(top, band)
        else:
            bottom = min(bottom, H - band)
    if s["progress"]:
        bottom = min(bottom, H - int(U * 0.03))
    L["fx"], L["fy"] = W // 2, (top + bottom) // 2

    if rnd:
        room = max(U * 0.12, min(W, bottom - top) / 2 - U * 0.035)
        t = (s["viz_size"] - 15) / 85
        if st == "circle":
            rc, gap, depth = U * (0.15 + 0.2 * t), U * 0.012, U * (0.13 + 0.06 * t)
            if rc + gap + depth > room:
                k = room / (rc + gap + depth)
                rc, gap, depth = rc * k, gap * k, depth * k
            L.update(rc=int(rc), r_in=int(rc + gap), r_out=int(rc + gap + depth))
        else:
            L["rc"] = int(min(room * 0.6, U * (0.1 + 0.14 * t)))
    else:
        bh = even(max(U * 0.2, min(H * 0.72, bottom - top - U * 0.06)))
        L["fbox"] = (even(W * 0.9), bh)
        L["rc"] = min(L["fbox"]) // 2
    return L


# ──────────────────────────────────────────────────────────────────────────────
# Images préparées : jaquette, fond, textes, dégradés
# ──────────────────────────────────────────────────────────────────────────────

def front_spec(L: dict, scale: float = 1.0):
    """Taille et commande ffmpeg de la jaquette au premier plan (RGBA)."""
    front, cover, U = L["front"], L["cover"], L["U"]
    if front in ("round", "disc"):
        D = even(2 * L["rc"] * scale)
        R = D / 2
        b = max(2.0, U * 0.007 * scale)
        dist = f"hypot(X-{R}+0.5,Y-{R}+0.5)"
        ring = f"gt({dist},{R - b:.2f})"
        geq = (f"geq=r='if({ring},255,r(X,Y))':g='if({ring},255,g(X,Y))':"
               f"b='if({ring},255,b(X,Y))':a='255*clip({R}-{dist},0,1)'")
        if front == "round":
            args = ["-i", cover, "-vf",
                    f"scale={D}:{D}:force_original_aspect_ratio=increase,crop={D}:{D},format=rgba,{geq}"]
        else:
            args = ["-f", "lavfi", "-i", f"color=c=0x14141c:s={D}x{D}:d=1", "-vf", f"format=rgba,{geq}"]
        return D, D, args, ("round", front, file_key(cover), D, b)
    iw, ih = probe(cover)["w"], probe(cover)["h"]
    bw, bh = L["fbox"]
    k = min(bw / iw, bh / ih) if iw and ih else 1.0
    dw, dh = even(iw * k * scale), even(ih * k * scale)
    return dw, dh, ["-i", cover, "-vf", f"scale={dw}:{dh},format=rgba"], ("sq", file_key(cover), dw, dh)


def front_png(L: dict, scale: float = 1.0) -> tuple[Path, int, int]:
    w, h, args, key = front_spec(L, scale)
    out = TMP / f"front_{short_hash(key)}.png"
    make_asset(out, *args, "-frames:v", "1", what="Jaquette")
    return out, w, h


def front_sprite(L: dict, maxscale: float, n: int = 16) -> tuple[Path, int, int, int]:
    """Planche de la jaquette à n tailles (pulsation sans recalcul à chaque image)."""
    w0, h0 = front_spec(L, 1.0)[:2]
    big, cw, ch = front_png(L, maxscale)
    out = TMP / f"fspr_{short_hash(str(big), n, w0, h0)}.png"
    if out.exists():
        return out, cw, ch, n
    parts = []
    for k in range(n):
        f = k / (n - 1)
        parts.append(f"[a{k}]scale={even(w0 + (cw - w0) * f)}:{even(h0 + (ch - h0) * f)}:flags=bicubic,"
                     f"pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:color=black@0[p{k}]")
    graph = (f"[0:v]format=rgba,split={n}" + "".join(f"[a{k}]" for k in range(n)) + ";"
             + ";".join(parts) + ";" + "".join(f"[p{k}]" for k in range(n)) + f"vstack=inputs={n}")
    make_asset(out, "-i", big, "-filter_complex", graph, "-frames:v", "1", what="Pulsation")
    return out, cw, ch, n


def drawtext(text: str, fs: int, y: int, bold: bool) -> str:
    tf = TMP / f"txt_{short_hash(text)}.txt"
    tf.write_text(text, encoding="utf-8")
    font = TOOLS["font"] if bold else (TOOLS["font2"] or TOOLS["font"])
    sh = max(1, fs // 22)
    color = "white" if bold else "white@0.85"
    return (f"drawtext=fontfile='{ffpath(font)}':textfile='{ffpath(tf)}':expansion=none:"
            f"fontsize={fs}:fontcolor={color}:shadowcolor=black@0.6:shadowx={sh}:shadowy={sh}:"
            f"x=(w-text_w)/2:y={y}")


def progress_height(U: int) -> int:
    return max(4, even(U / 160))


def render_background(L: dict, s: dict, with_front: bool, with_text: bool) -> Path:
    """Image fixe du fond (image ou couleur, effet, jaquette fixe, textes) en un PNG."""
    W, H, U = L["W"], L["H"], L["U"]
    img = L["bg_img"]
    front = L["front"] if with_front else None
    fpng = front_png(L) if front else None
    texts = L["texts"] if with_text else []
    track = with_text and s["progress"]
    strong = bool(front and img and img == L["cover"])
    out = TMP / ("bg_" + short_hash(file_key(img), W, H, s["bg_color"], s["effect"], strong,
                                    fpng and str(fpng[0]), L["fx"], L["fy"], texts, track) + ".png")
    if out.exists():
        return out
    inputs: list = []
    if img:
        inputs = ["-i", img]
        eff = ""
        if s["effect"] in ("blur", "both"):
            eff += f",gblur=sigma={max(8, U // 18) if strong else max(4, U // 40)}"
        if s["effect"] in ("dark", "both"):
            eff += f",eq=brightness={-0.25 if strong else -0.18}"
        graph = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                 f"setsar=1{eff},format=rgb24[b0]")
    else:
        graph = f"color=c={ffcolor(s['bg_color'])}:s={W}x{H}:d=1,format=rgb24[b0]"
    cur = "b0"
    if fpng:
        path, fw, fh = fpng
        idx = len(inputs) // 2
        inputs += ["-i", path]
        graph += f";[b0][{idx}:v]overlay={L['fx'] - fw // 2}:{L['fy'] - fh // 2}[b1]"
        cur = "b1"
    tail = [drawtext(t, fs, y, b) for t, fs, y, b in texts]
    if track:
        ph = progress_height(U)
        tail.append(f"drawbox=x=0:y={H - ph}:w={W}:h={ph}:color=white@0.22:t=fill")
    graph += f";[{cur}]{','.join(tail) + ',' if tail else ''}format=rgb24[b]"
    return make_asset(out, *inputs, "-filter_complex", graph, "-map", "[b]", "-frames:v", "1",
                      what="Fond")


def text_layer(L: dict) -> tuple[Path, int]:
    """Textes seuls sur fond transparent (quand le fond « pompe », le texte reste fixe)."""
    W, H, band = L["W"], L["H"], L["band"]
    ty = 0 if L["text_top"] else H - band
    out = TMP / f"txtl_{short_hash(L['texts'], W, H, band, ty)}.png"
    dt = ",".join(drawtext(t, fs, y - ty, b) for t, fs, y, b in L["texts"])
    make_asset(out, "-f", "lavfi", "-i", f"color=c=black@0:s={W}x{band}:d=1,format=rgba,{dt}",
               "-frames:v", "1", what="Texte")
    return out, ty


def bg_sprite(bg: Path, W: int, H: int, n: int, zmax: float) -> Path:
    """Le fond à n niveaux de zoom, empilés (zoom sur les basses sans recalcul)."""
    out = TMP / f"bgz_{short_hash(str(bg), W, H, n, zmax)}.bmp"
    parts = []
    for k in range(n):
        z = 1 + (zmax - 1) * k / (n - 1)
        parts.append(f"[b{k}]scale={even(W * z)}:{even(H * z)}:flags=bicubic,crop={W}:{H}[q{k}]")
    graph = (f"[0:v]split={n}" + "".join(f"[b{k}]" for k in range(n)) + ";" + ";".join(parts)
             + ";" + "".join(f"[q{k}]" for k in range(n)) + f"vstack=inputs={n}")
    return make_asset(out, "-i", bg, "-filter_complex", graph, "-frames:v", "1", what="Zoom du fond")


def scheme_stops(s: dict, cover: Path | None) -> tuple[list[str], bool]:
    """Couleurs du dégradé et axe (True = selon la hauteur, False = selon la fréquence)."""
    sc = s["colors"]
    if sc == "solid":
        return [s["color"], s["color"]], False
    if sc == "duo":
        return [s["color"], s["color2"]], False
    if sc == "cover":
        return (cover_colors(cover) if cover else SCHEMES["neon"]), False
    return SCHEMES[sc], sc in AMP_SCHEMES


def grad_image(stops: list[str], w: int, h: int, vertical: bool) -> Path:
    stops = (stops * 2)[:max(2, min(8, len(stops)))]
    out = TMP / f"grad_{short_hash(stops, w, h, vertical)}.png"
    cs = ":".join(f"c{i}={ffcolor(c)}" for i, c in enumerate(stops))
    x0, y0, x1, y1 = (0, h - 1, 0, 0) if vertical else (0, 0, max(1, w - 1), 0)
    return make_asset(out, "-f", "lavfi", "-i",
                      f"gradients=s={w}x{h}:{cs}:n={len(stops)}:x0={x0}:y0={y0}:x1={x1}:y1={y1}"
                      f":speed=0:d=1", "-frames:v", "1", what="Couleurs")


def map_color_image(stops, vertical, sw, sh, xc: Path, yc: Path) -> Path:
    """Image des couleurs à l'écran : le dégradé « source » passé par la même déformation."""
    grad = grad_image(stops, sw, sh, vertical)
    out = TMP / f"col_{short_hash(str(grad), str(xc))}.png"
    return make_asset(out, "-i", grad, "-i", xc, "-i", yc, "-filter_complex",
                      "[0:v]format=rgb24[s];[s][1:v][2:v]remap=format=color", "-frames:v", "1",
                      what="Couleurs")


# ──────────────────────────────────────────────────────────────────────────────
# Cartes de déformation (filtre remap) — calculées une fois puis réutilisées
# ──────────────────────────────────────────────────────────────────────────────

BAD = 65535  # « pas de pixel ici »


def write_pgm16(path: Path, w: int, h: int, data: array) -> None:
    a = array("H", data)
    if sys.byteorder == "little":
        a.byteswap()
    part = path.with_name(path.stem + ".part" + path.suffix)
    with open(part, "wb") as fh:
        fh.write(b"P5\n%d %d\n65535\n" % (w, h))
        fh.write(a.tobytes())
    os.replace(part, path)


def cached_maps(name: str, params, w: int, h: int, build) -> list[Path]:
    key = short_hash(name, params, w, h)
    meta = TMP / f"map_{key}.n"
    if meta.exists():
        return [TMP / f"map_{key}_{i}.pgm" for i in range(int(meta.read_text()))]
    arrays = build()
    paths = []
    for i, a in enumerate(arrays):
        p = TMP / f"map_{key}_{i}.pgm"
        write_pgm16(p, w, h, a)
        paths.append(p)
    meta.write_text(str(len(arrays)))
    return paths


def ring_maps(S: int, r_in: int, r_out: int, nh: int, SH: int, fill: float = 0.62):
    """Spectre en couronne (miroir gauche/droite, basses en haut)."""
    def build():
        n = S * S
        xm, ym = array("H", [BAD]) * n, array("H", [BAD]) * n
        xc, yc = array("H", [0]) * n, array("H", [0]) * n
        c, depth, top, half = (S - 1) / 2, float(r_out - r_in), SH - 1, fill / 2
        hyp, at2, pi = math.hypot, math.atan2, math.pi
        i = 0
        for v in range(S):
            dy = v - c
            for u in range(S):
                dx = u - c
                pos = abs(at2(dx, -dy)) / pi * nh
                k = int(pos)
                if k >= nh:
                    k = nh - 1
                f = (hyp(dx, dy) - r_in) / depth
                sy = int((1.0 - f) * top + 0.5)
                sy = 0 if sy < 0 else (top if sy > top else sy)
                xc[i], yc[i] = k, sy
                if 0.0 <= f < 1.0 and abs(pos - k - 0.5) <= half:
                    xm[i], ym[i] = k, sy
                i += 1
        return [xm, ym, xc, yc]
    return cached_maps("ring", (r_in, r_out, nh, SH, fill), S, S, build)


def retro_maps(BW: int, BH: int, nb: int, SH: int, U: int):
    """Barres découpées en LED."""
    nseg = max(6, min(40, round(BH / (U * 0.026))))

    def build():
        pitch, segp, top = BW / nb, BH / nseg, SH - 1
        ks = [min(nb - 1, int(u / pitch)) for u in range(BW)]
        on = [(u / pitch - int(u / pitch)) <= 0.78 for u in range(BW)]
        xon = array("H", [k if o else BAD for k, o in zip(ks, on)])
        off, xcol = array("H", [BAD]) * BW, array("H", ks)
        rows: dict = {}
        xm, ym, xc, yc = array("H"), array("H"), array("H"), array("H")
        for v in range(BH):
            hv = (BH - 1 - v) / segp
            j = min(nseg - 1, int(hv))
            sy = max(0, min(top, top - int((j + 0.5) * SH / nseg)))
            if sy not in rows:
                rows[sy] = array("H", [sy if o else BAD for o in on])
            lit = (hv - j) <= 0.72
            xm.extend(xon if lit else off)
            ym.extend(rows[sy] if lit else off)
            xc.extend(xcol)
            yc.extend(array("H", [sy]) * BW)
        return [xm, ym, xc, yc]
    return cached_maps("retro", (nb, SH, nseg), BW, BH, build)


def mirror_maps(BW: int, BH: int, nb: int, SH: int, fill=0.8, split=0.64, refl=0.55):
    """Spectre symétrique (basses au centre) avec un reflet plus court en dessous."""
    def build():
        top, line, half = SH - 1, BH * split, BW / 2
        ks, on = [], []
        for u in range(BW):
            pos = abs(u + 0.5 - half) / half * nb
            k = min(nb - 1, int(pos))
            ks.append(k)
            on.append(abs(pos - k - 0.5) <= fill / 2)
        xrow, xcol = array("H", [k if o else BAD for k, o in zip(ks, on)]), array("H", ks)
        off = array("H", [BAD]) * BW
        xm, ym, xc, yc = array("H"), array("H"), array("H"), array("H")
        for v in range(BH):
            if v + 0.5 < line:
                f, dim = (line - v - 0.5) / line, 0
            else:
                f, dim = (v + 0.5 - line) / (line * refl), SH
            sy = int((1 - min(f, 1.0)) * top + 0.5)
            xc.extend(xcol)
            yc.extend(array("H", [sy]) * BW)
            if f < 1.0:
                xm.extend(xrow)
                ym.extend(array("H", [sy + dim if o else BAD for o in on]))
            else:
                xm.extend(off)
                ym.extend(off)
        return [xm, ym, xc, yc]
    return cached_maps("mirror", (nb, SH, fill, split, refl), BW, BH, build)


def cubes_maps(BW: int, BH: int, cols: int, rows: int, K: int):
    """Grille de carrés ; chaque carré suit une bande de fréquences (ordre mélangé)."""
    def build():
        rng = random.Random(7)
        order = list(range(K)) * (cols * rows // K + 1)
        rng.shuffle(order)
        perm, m = order[:cols * rows], 0.07
        cu = [(min(cols - 1, int(u * cols / BW)), u * cols / BW % 1) for u in range(BW)]
        cv = [(min(rows - 1, int(v * rows / BH)), v * rows / BH % 1) for v in range(BH)]
        xm, ym, xc, yc = array("H"), array("H"), array("H"), array("H")
        for v in range(BH):
            j, fv = cv[v]
            vin, vcore = m <= fv <= 1 - m, 0.32 <= fv <= 0.68
            for u in range(BW):
                i, fu = cu[u]
                b = perm[j * cols + i]
                xc.append(b)
                yc.append(0)
                if vin and m <= fu <= 1 - m:
                    xm.append(b)
                    ym.append(1 if (vcore and 0.32 <= fu <= 0.68) else 0)
                else:
                    xm.append(BAD)
                    ym.append(BAD)
        return [xm, ym, xc, yc]
    return cached_maps("cubes", (cols, rows, K), BW, BH, build)


def tunnel_maps(TW: int, TH: int, T: int, F: int, r0: float, cx: float, cy: float, twist=1.4):
    """Historique du spectre enroulé en tunnel : le présent au centre, le passé vers les bords."""
    def build():
        rmax = max(math.hypot(cx, cy), math.hypot(TW - cx, cy), math.hypot(cx, TH - cy),
                   math.hypot(TW - cx, TH - cy)) + 2
        lnr = math.log(rmax / r0)
        hyp, at2, log, pi, tau = math.hypot, math.atan2, math.log, math.pi, 2 * math.pi
        xm, ym = array("H"), array("H")
        for v in range(TH):
            dy = v + 0.5 - cy
            for u in range(TW):
                dx = u + 0.5 - cx
                r = hyp(dx, dy)
                if r < r0:
                    xm.append(BAD)
                    ym.append(BAD)
                    continue
                age = log(r / r0) / lnr
                th = (at2(dx, -dy) + twist * age + pi) % tau - pi
                xm.append(T - 1 - int(age * (T - 1)))
                ym.append(F - 1 - int(abs(th) / pi * (F - 1)))
        return [xm, ym]
    return cached_maps("tunnel", (T, F, round(r0, 1), round(cx, 1), round(cy, 1), twist), TW, TH, build)


# ──────────────────────────────────────────────────────────────────────────────
# Pulsation sur les basses
# ──────────────────────────────────────────────────────────────────────────────

def bass_envelope(mp3: Path, fps: int, start: float, dur: float | None) -> list[float]:
    """Niveau des basses (0 → 1) pour chaque image de la vidéo."""
    sr = 1200
    cmd = [TOOLS["ffmpeg"], "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-i", str(mp3), "-vn", "-ac", "1", "-af",
            f"aresample=2400,lowpass=f=140,lowpass=f=140,aresample={sr}", "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, **NO_WINDOW).stdout
    a = array("h")
    a.frombytes(raw[:len(raw) // 2 * 2])
    if sys.byteorder == "big":
        a.byteswap()
    spf = sr / fps
    rms = []
    for i in range(int(len(a) / spf)):
        seg = a[int(i * spf):int((i + 1) * spf)]
        rms.append((sum(x * x for x in seg) / max(1, len(seg))) ** 0.5)
    if not rms:
        return []
    ref = sorted(rms)[int(len(rms) * 0.97)] or 1.0
    out, y, k = [], 0.0, 0.5 ** (1.0 / (0.12 * fps))   # retombée : moitié en 0,12 s
    for v in rms:
        x = max(0.0, (min(1.0, v / ref) - 0.5) / 0.5) ** 1.4
        y = x if x > y else y * k
        out.append(y)
    return out


def write_cmds(env: list[float], fps: int, nc: int, ch: int, nb: int, H: int) -> Path:
    """Commandes sendcmd : choix de la taille de jaquette / du zoom du fond à chaque image."""
    lines, last = [], None
    for i, e in enumerate(env or [0.0]):
        kc, kb = round(e * (nc - 1)) if nc else 0, round(e * (nb - 1)) if nb else 0
        if (kc, kb) != last:
            parts = ([f"crop@cz y {kc * ch}"] if nc else []) + ([f"crop@bz y {kb * H}"] if nb else [])
            lines.append(f"{i / fps:.4f} " + ", ".join(parts) + ";")
            last = (kc, kb)
    path = TMP / f"cmd_{secrets.token_hex(6)}.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ──────────────────────────────────────────────────────────────────────────────
# Construction du graphe FFmpeg
# ──────────────────────────────────────────────────────────────────────────────

LOOP = "loop=loop=-1:size=1:start=0,setpts=N/({fps}*TB)"
UNFILL = "lut=c0='if(lt(val,20),0,val)'"     # le « vide » de remap devient vraiment noir


class Graph:
    def __init__(self, fps: int):
        self.fps, self.inputs, self.chains, self.k = fps, [], [], 0

    def label(self) -> str:
        self.k += 1
        return f"x{self.k}"

    def still(self, path, fmt: str = "") -> str:
        """Image fixe répétée à chaque image de la vidéo."""
        self.inputs.append(str(path))
        lab = self.label()
        pre = f"format={fmt}," if fmt else ""
        self.chains.append(f"[{len(self.inputs)}:v]{pre}{LOOP.format(fps=self.fps)}[{lab}]")
        return lab

    def add(self, chain: str) -> None:
        self.chains.append(chain)

    def text(self) -> str:
        return ";".join(self.chains)


def cqt_src(n: int, rows: int, s: dict, fps: int, decay: float | None = 0.8) -> str:
    """Spectre vrai-logarithmique 30 Hz → 12 kHz, n bandes, barres blanches nettes."""
    vol = 4.0 * 2 ** (s["sensitivity"] / 33.0)
    lag = f",lagfun=decay={decay ** (30.0 / fps):.3f}" if decay else ""
    return (f"showcqt=s={n}x{rows}:fps={fps}:bar_h={rows}:axis_h=0:sono_h=0:bar_g=3:bar_v={vol:.2f}:"
            f"cscheme=1|1|1|1|1|1:basefreq=30:endfreq=12000,format=gray,"
            f"gblur=sigma=0.8:sigmaV=0.01,lut=c0='if(gt(val,40),255,0)'{lag}")


def colorize(g: Graph, L: dict, mask: str, w: int, h: int, col_png: Path, scroll: bool = False) -> str:
    """Masque gris → calque coloré (avec lueur néon si demandée)."""
    if L["s"]["glow"]:
        a, b, q, m2 = g.label(), g.label(), g.label(), g.label()
        sig = max(1.0, L["U"] * 0.012 / 4)
        g.add(f"[{mask}]split[{a}][{b}];[{b}]scale={even(w / 4)}:{even(h / 4)}:flags=bilinear,"
              f"gblur=sigma={sig:.2f},lut=c0='min(255,val*2.4)',scale={w}:{h}:flags=bicubic[{q}];"
              f"[{a}][{q}]blend=all_mode=lighten[{m2}]")
        mask = m2
    col = g.still(col_png, "yuva420p")
    if scroll:
        c2 = g.label()
        g.add(f"[{col}]scroll=h=0.0015[{c2}]")
        col = c2
    out = g.label()
    g.add(f"[{col}][{mask}]alphamerge=shortest=1[{out}]")
    return out


def remap_mask(g: Graph, src: str, xm: Path, ym: Path) -> str:
    mx, my = g.still(xm), g.still(ym)
    m0, m1 = g.label(), g.label()
    g.add(f"[{src}][{mx}][{my}]remap=format=gray[{m0}];[{m0}]{UNFILL}[{m1}]")
    return m1


def layer_circle(g: Graph, L: dict, s: dict, fps: int):
    U, r_in, r_out = L["U"], L["r_in"], L["r_out"]
    nh = max(24, min(96, int(math.pi * r_in / (U * 0.0215)) // 2 * 2))
    SH = 200
    S = even(2 * (r_out + U * 0.045))
    xm, ym, xc, yc = ring_maps(S, r_in, r_out, nh, SH)
    stops, vert = scheme_stops(s, L["cover"])
    col = map_color_image(stops, vert, nh, SH, xc, yc)
    src = g.label()
    g.add(f"[0:a]{cqt_src(nh, SH, s, fps)}[{src}]")
    return colorize(g, L, remap_mask(g, src, xm, ym), S, S, col), L["fx"] - S // 2, L["fy"] - S // 2


def layer_retro(g: Graph, L: dict, s: dict, fps: int):
    U, W, BH = L["U"], L["W"], L["vh"]
    BW = even(W * 0.92)
    nb = max(12, min(64, int(BW / (U * 0.034)))) // 2 * 2   # showcqt veut une largeur paire
    SH = 120
    xm, ym, xc, yc = retro_maps(BW, BH, nb, SH, U)
    stops, vert = scheme_stops(s, L["cover"])
    col = map_color_image(stops, vert, nb, SH, xc, yc)
    src = g.label()
    g.add(f"[0:a]{cqt_src(nb, SH, s, fps, 0.86)}[{src}]")
    return colorize(g, L, remap_mask(g, src, xm, ym), BW, BH, col), (W - BW) // 2, L["vy"]


def layer_mirror(g: Graph, L: dict, s: dict, fps: int):
    U, W, BH = L["U"], L["W"], L["vh"]
    nb = max(24, min(120, int(W / 2 / (U * 0.0105)))) // 2 * 2
    SH = 160
    xm, ym, xc, yc = mirror_maps(W, BH, nb, SH)
    stops, vert = scheme_stops(s, L["cover"])
    col = map_color_image(stops, vert, nb, SH, xc, yc)
    a, b, d, src = g.label(), g.label(), g.label(), g.label()
    g.add(f"[0:a]{cqt_src(nb, SH, s, fps, 0.86)},split[{a}][{b}];[{b}]lut=c0='val*0.42'[{d}];"
          f"[{a}][{d}]vstack[{src}]")
    return colorize(g, L, remap_mask(g, src, xm, ym), W, BH, col), 0, L["vy"]


def layer_cubes(g: Graph, L: dict, s: dict, fps: int):
    U, W, BH = L["U"], L["W"], L["vh"]
    cell = U * 0.11
    cols, rows = max(4, round(W / cell)), max(2, round(BH / cell))
    K = max(8, min(48, cols * rows // 2 * 2))
    xm, ym, xc, yc = cubes_maps(W, BH, cols, rows, K)
    stops, _ = scheme_stops(s, L["cover"])
    col = map_color_image(stops, False, K, 2, xc, yc)
    a, b, d, src = g.label(), g.label(), g.label(), g.label()
    g.add(f"[0:a]{cqt_src(K, 48, s, fps, None)},scale={K}:1:flags=area,"
          f"lut=c0='clip((val-50)*1.9,0,255)',lagfun=decay={0.85 ** (30 / fps):.3f},split[{a}][{b}];"
          f"[{b}]lut=c0='val*0.45'[{d}];[{a}][{d}]vstack[{src}]")
    return colorize(g, L, remap_mask(g, src, xm, ym), W, BH, col), 0, L["vy"]


def layer_aurora(g: Graph, L: dict, s: dict, fps: int):
    U, W, BH = L["U"], L["W"], L["vh"]
    stops, _ = scheme_stops(s, L["cover"])
    grad = grad_image(stops + [stops[0]], W, BH, False)
    m = g.label()
    g.add(f"[0:a]showwaves=s={even(W / 2)}x{even(BH / 2)}:mode=p2p:rate={fps}:colors=white|white:"
          f"draw=full,format=gray,lagfun=decay={0.93 ** (30 / fps):.3f},scale={W}:{BH}:flags=bicubic,"
          f"gblur=sigma={max(0.6, U * 0.0015):.2f}[{m}]")
    return colorize(g, L, m, W, BH, grad, scroll=True), 0, L["vy"]


def layer_tunnel(g: Graph, L: dict, s: dict, fps: int, keyed: bool):
    W, H = L["W"], L["H"]
    TW = even(min(W, 1280))
    TH = even(TW * H / W)
    sc = TW / W
    T, F = 160, 256
    xm, ym = tunnel_maps(TW, TH, T, F, max(4.0, L["rc"] * sc * 1.02), L["fx"] * sc, L["fy"] * sc)
    sp, out = g.label(), g.label()
    g.add(f"[0:a]showspectrum=s={T}x{F}:slide=scroll:mode=combined:color={s['palette']}:"
          f"scale=log:fscale=log:fps={fps}[{sp}]")
    mx, my = g.still(xm), g.still(ym)
    up = f",scale={W}:{H}:flags=bicubic" if (TW, TH) != (W, H) else ""
    key = ",colorkey=black:0.10:0.12" if keyed else ""
    g.add(f"[{sp}][{mx}][{my}]remap=format=color:fill=black{up},format=rgba{key}[{out}]")
    return out, 0, 0


def visualizer(s: dict, W: int, vh: int, fps: int, keyed: bool) -> str:
    """Visualiseurs « classiques » (filtres ffmpeg directs)."""
    st, c = s["style"], ffcolor(s["color"])
    if st == "cqt":
        sono = ":sono_h=0" if keyed else ""
        return f"showcqt=s={W}x{vh}:fps={fps}:bar_g=2:sono_g=4:axis=0{sono}"
    if st == "waves":
        return f"showwaves=s={W}x{vh}:rate={fps}:mode=cline:colors={c}"
    if st == "bars":
        return (f"showfreqs=s={W}x{vh}:rate={fps}:mode=bar:ascale=log:fscale=log:"
                f"win_size=2048:colors={c}|{c}")
    if st == "spectrum":
        return (f"showspectrum=s={W}x{vh}:mode=combined:color={s['palette']}:"
                f"slide=scroll:scale=log:overlap=0.75,fps={fps}")
    if st == "scope":
        side = even(min(W, vh))
        h = s["color"].lstrip("#")
        r, gg, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        tint = ":".join(f"{ch}{src}={coef * k:.3f}"
                        for ch, k in (("r", r), ("g", gg), ("b", b))
                        for src, coef in (("r", 0.3), ("g", 0.59), ("b", 0.11)))
        return (f"avectorscope=s={side}x{side}:rate={fps}:zoom=1.5:draw=line:"
                f"rc=200:gc=200:bc=200:rf=12:gf=12:bf=12,format=rgba,"
                f"colorchannelmixer={tint},"
                f"pad={W}:{vh}:(ow-iw)/2:(oh-ih)/2:color=black@0")
    raise ValueError(st)


def style_layer(g: Graph, L: dict, s: dict, fps: int, keyed: bool):
    st = s["style"]
    if st == "circle":
        return layer_circle(g, L, s, fps)
    if st == "retro":
        return layer_retro(g, L, s, fps)
    if st == "mirror":
        return layer_mirror(g, L, s, fps)
    if st == "cubes":
        return layer_cubes(g, L, s, fps)
    if st == "aurora":
        return layer_aurora(g, L, s, fps)
    if st == "tunnel":
        return layer_tunnel(g, L, s, fps, keyed)
    out = g.label()
    key = ",colorkey=black:0.12:0.08" if keyed else ""
    g.add(f"[0:a]{visualizer(s, L['W'], L['vh'], fps, keyed)},format=rgba{key}[{out}]")
    return out, 0, L["vy"]


def prepare(mp3: Path, s: dict, W: int, H: int, start: float, dur: float,
            preroll: float = 0.0, final: bool = False, env_all: list[float] | None = None,
            fade_in: bool = True, fade_out: bool = True,
            trans_in: bool = False, trans_out: bool = False) -> Graph:
    """Prépare toutes les images et renvoie le graphe de filtres complet.
    Les temps du graphe commencent à 0 au début du passage lu (start - preroll).
    env_all : pulsation déjà calculée sur tout le morceau (conversion en plusieurs parties)."""
    fps = s["fps"]
    with ASSET_LOCK:
        L = compute_layout(mp3, s, W, H)
        U = L["U"]
        total = probe(mp3)["duration"] or (start + dur)
        pulse = s["pulse"] / 100.0
        fpulse = pulse > 0 and L["front"] is not None
        nbz = max(2, min(9, int(45e6 // (W * H))))
        zoom = pulse > 0 and s["pulse_bg"] and L["bg_img"] is not None and nbz >= 3
        keyed = bool(L["bg_img"] or L["texts"] or s["bg_color"].lower() != "#000000")
        bg = render_background(L, s, with_front=bool(L["front"]) and not fpulse, with_text=not zoom)
        g = Graph(fps)
        spr = None
        if fpulse:
            spr, cw, ch, nc = front_sprite(L, 1 + 0.12 * pulse)
        cmds = None
        if fpulse or zoom:
            if env_all is not None:            # même calibrage pour toutes les parties
                i0 = max(0, round((start - preroll) * fps))
                env = env_all[i0:i0 + round((dur + preroll) * fps) + fps]
            else:
                env = bass_envelope(mp3, fps, max(0.0, start - preroll), dur + preroll)
            cmds = write_cmds(env, fps, nc if fpulse else 0, ch if fpulse else 0, nbz if zoom else 0, H)

        if zoom:
            base = g.still(bg_sprite(bg, W, H, nbz, 1 + 0.05 * pulse), "yuv420p")
        else:
            base = g.still(bg, "yuv420p")
        cur = g.label()
        send = f"sendcmd=f='{ffpath(cmds)}'," if cmds else ""
        crop = f"crop@bz=w={W}:h={H}:x=0:y=0" if zoom else "null"
        g.add(f"[{base}]{send}{crop}[{cur}]")

        def over(lab: str, x: int, y: int) -> None:
            nonlocal cur
            nxt = g.label()
            g.add(f"[{cur}][{lab}]overlay={x}:{y}:shortest=1[{nxt}]")
            cur = nxt

        def cover_layer() -> None:
            lab = g.still(spr, "yuva420p")
            c2 = g.label()
            g.add(f"[{lab}]crop@cz=w={cw}:h={ch}:x=0:y=0[{c2}]")
            over(c2, L["fx"] - cw // 2, L["fy"] - ch // 2)

        rnd = s["style"] in ROUND_STYLES
        if spr and not rnd:
            cover_layer()
        lay, x, y = style_layer(g, L, s, fps, keyed)
        over(lay, x, y)
        if spr and rnd:
            cover_layer()
        if zoom and L["texts"]:
            png, ty = text_layer(L)
            over(g.still(png, "yuva420p"), 0, ty)
        tail = []
        if s["progress"]:
            ph = progress_height(U)
            t0 = start - preroll
            if zoom:
                tail.append(f"drawbox=x=0:y={H - ph}:w={W}:h={ph}:color=white@0.22:t=fill")
            bar = g.label()
            g.add(f"color=c=white@0.9:s={W}x{ph}:r={fps}[{bar}]")
            nxt = g.label()
            g.add(f"[{cur}]{','.join(tail) + ',' if tail else ''}null[{nxt}]")
            cur = nxt
            tail = []
            nxt = g.label()
            g.add(f"[{cur}][{bar}]overlay=x='(t+{t0:.3f})/{total:.3f}*W-W':y={H - ph}:shortest=1[{nxt}]")
            cur = nxt
        if preroll > 0:
            tail.append(f"trim=start={preroll:.3f},setpts=PTS-STARTPTS")
        if final and s["fade"] and total > 4:
            if fade_in:
                tail.append("fade=t=in:st=0:d=1")
            if fade_out and dur > 1.5:
                tail.append(f"fade=t=out:st={dur - 1.5:.3f}:d=1.5")
        if trans_in:                           # changement de visualiseur : court fondu
            tail.append(f"fade=t=in:st=0:d={TRANS_D}")
        if trans_out and dur > TRANS_D:
            tail.append(f"fade=t=out:st={dur - TRANS_D:.3f}:d={TRANS_D}")
        tail.append("format=yuv420p")
        g.add(f"[{cur}]{','.join(tail)}[v]")
        return g


# ──────────────────────────────────────────────────────────────────────────────
# Conversion et aperçu
# ──────────────────────────────────────────────────────────────────────────────

def _inputs(g: Graph) -> list[str]:
    out: list[str] = []
    for p in g.inputs:
        out += ["-i", p]
    return out


_HW: dict = {}
_HW_LOCK = threading.Lock()


def hw_encoder() -> str | None:
    """Encodeur H.264 de la puce graphique s'il fonctionne vraiment (ONDE2VID_HWENC=0 pour l'ignorer)."""
    if os.environ.get("ONDE2VID_HWENC", "").strip() == "0":
        return None
    ff = TOOLS["ffmpeg"]
    if not ff:
        return None
    with _HW_LOCK:                         # un seul test, même si plusieurs requêtes arrivent
        if "enc" in _HW:
            return _HW["enc"]
        enc_found = None
        cands = ["h264_videotoolbox"] if sys.platform == "darwin" else []
        try:
            listed = run_text([ff, "-hide_banner", "-encoders"]).stdout
            for enc in cands:
                if enc in listed and run_text(
                        [ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                         "color=s=640x360:r=30:d=0.5", "-c:v", enc, "-b:v", "1M", "-f", "null", "-"]
                        ).returncode == 0:
                    enc_found = enc
                    break
        except (OSError, subprocess.SubprocessError):
            pass
        _HW["enc"] = enc_found
        return enc_found


def video_args(s: dict, W: int, H: int) -> list[str]:
    """Réglages de compression vidéo : puce graphique (mode Rapide) si possible, sinon libx264."""
    enc = hw_encoder() if s["compression"] == "fast" else None
    if enc == "h264_videotoolbox":
        # débit adapté à la taille de l'image (≈ 1,5 Mb/s en 1080p à 30 i/s), CRF 18 → +25 %
        kbps = int(W * H * s["fps"] * 0.025 / 1000 * (1.25 ** ((20 - s["crf"]) / 2)))
        return ["-c:v", enc, "-b:v", f"{kbps}k", "-prio_speed", "1", "-profile:v", "high",
                "-r", str(s["fps"])]
    return ["-c:v", "libx264", "-preset", s["preset"], "-crf", str(s["crf"]), "-r", str(s["fps"])]


TRANS_D = 0.4             # durée du fondu quand le visualiseur change (secondes)


def style_plan(s: dict, dur: float, name: str) -> list[tuple[float, float, str]]:
    """Visualiseur de chaque passage : [(début, fin, style)].
    Un seul passage sans alternance ; le tirage au hasard est fixe pour un morceau donné."""
    styles = s["rotate_styles"]
    if not s["rotate"] or len(styles) < 2 or dur <= 0:
        return [(0.0, dur, s["style"])]
    step = s["rotate_minutes"] * 60.0
    n = math.ceil(dur / step)
    if n > 1 and dur - (n - 1) * step < min(30.0, step / 2):   # fin trop courte : rattachée
        n -= 1
    if s["rotate_order"] == "order":
        seq = [styles[i % len(styles)] for i in range(n)]
    else:
        rng = random.Random(int(short_hash(name, styles), 16))
        seq, bag = [], []
        while len(seq) < n:
            if not bag:
                bag = styles[:]
                rng.shuffle(bag)
                if seq and bag[0] == seq[-1]:
                    bag.append(bag.pop(0))
            seq.append(bag.pop(0))
    return [(i * step, dur if i == n - 1 else (i + 1) * step, seq[i]) for i in range(n)]


def style_at(plan: list[tuple[float, float, str]], t: float) -> str:
    for a, b, st in plan:
        if a <= t < b:
            return st
    return plan[-1][2]


PARALLEL_MIN = 120.0      # morceaux plus courts : conversion d'un seul tenant
SEGMENT_TARGET = 240.0    # durée visée de chaque partie, en secondes


def parallel_workers(s: dict, W: int, H: int) -> int:
    """Nombre de parties calculées en même temps (ONDE2VID_PARALLEL=n pour forcer)."""
    forced = os.environ.get("ONDE2VID_PARALLEL", "").strip()
    if forced.isdigit():
        return max(1, int(forced))
    n = max(1, (os.cpu_count() or 2) // 2)
    if s["compression"] == "fast" and hw_encoder():   # la puce graphique devient la limite : 2 parties suffisent
        n = min(n, 2)
    if W * H > 4_000_000:                  # 4K : chaque partie demande beaucoup de mémoire
        n = min(n, 3)
    return min(n, 8)


class _ProcGroup:
    """Plusieurs ffmpeg lancés en même temps, arrêtés d'un coup (bouton Annuler)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.procs: set = set()
        self.stopped = False

    def add(self, p) -> bool:
        with self.lock:
            if not self.stopped:
                self.procs.add(p)
                return True
        p.terminate()
        return False

    def remove(self, p) -> None:
        with self.lock:
            self.procs.discard(p)

    def terminate(self) -> None:
        with self.lock:
            self.stopped = True
            procs = list(self.procs)
        for p in procs:
            try:
                p.terminate()
            except OSError:
                pass


def _run_ff(cmd: list[str], group: _ProcGroup, on_time=None) -> None:
    """Lance un ffmpeg du groupe ; on_time(secondes déjà produites)."""
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errlog:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errlog, stdin=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace", bufsize=1, **NO_WINDOW)
        group.add(proc)
        try:
            for line in proc.stdout:
                k, _, v = line.strip().partition("=")
                if k in ("out_time_us", "out_time_ms") and v.isdigit() and on_time:
                    on_time(int(v) / 1e6)
        finally:
            rc = proc.wait()
            group.remove(proc)
        if rc != 0:
            errlog.seek(0)
            raise RuntimeError(last_line(errlog.read(), f"ffmpeg a échoué (code {rc})"))


def convert_parallel(mp3: Path, s: dict, out: Path, dur: float, workers: int,
                     plan: list[tuple[float, float, str]], on_progress=None, set_proc=None) -> None:
    """Long morceau : découpé en parties calculées en même temps, puis recollées sans
    recompression ; le son est encodé une seule fois pour éviter tout raccord audible."""
    ff, fps = TOOLS["ffmpeg"], s["fps"]
    W, H = frame_size(s)
    frames = math.ceil(dur * fps)
    want = max(workers, math.ceil(dur / SEGMENT_TARGET))
    parts = []        # (1re image, image de fin, visualiseur, fondu d'entrée, fondu de sortie)
    for bi, (t0, t1, st) in enumerate(plan):
        a0 = round(t0 * fps) if bi else 0
        b0 = frames if bi == len(plan) - 1 else round(t1 * fps)
        n = max(1, round(want * (b0 - a0) / frames), math.ceil((b0 - a0) / fps / SEGMENT_TARGET))
        cuts = [a0 + round(k * (b0 - a0) / n) for k in range(n + 1)]
        for k in range(n):
            parts.append((cuts[k], cuts[k + 1], st, k == 0 and bi > 0, k == n - 1 and bi < len(plan) - 1))
    nseg = len(parts)
    env_all = bass_envelope(mp3, fps, 0.0, None) if s["pulse"] > 0 else None
    threads = str(max(1, (os.cpu_count() or 2) // workers))
    work = Path(tempfile.mkdtemp(prefix="parties_", dir=TMP))
    group = _ProcGroup()
    done = [0.0] * nseg
    plock, t0 = threading.Lock(), time.monotonic()
    base = [ff, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-progress", "pipe:1", "-nostats"]

    def progress(k: int, sec: float) -> None:
        if not on_progress:
            return
        with plock:
            done[k] = sec
            made, el = sum(done), time.monotonic() - t0
        on_progress(min(98.0, made / dur * 98), f"{made / el:.2f}x" if el > 2 else "")

    def audio_task() -> None:
        _run_ff(base + ["-i", str(mp3), "-vn", "-c:a", "aac", "-b:a", f"{s['audio_kbps']}k",
                        "-t", f"{dur:.3f}", str(work / "son.m4a")], group)

    def part_task(k: int) -> None:
        if group.stopped:
            raise RuntimeError("Conversion arrêtée")
        a, b, st, tin, tout = parts[k]
        sp = dict(s, style=st)
        start, length = a / fps, (b - a) / fps
        pre_s = {"spectrum": 12.0, "tunnel": 2.5}.get(st, 2.0)          # mise en route des effets
        pre = min(round(pre_s * fps), a) / fps
        g = prepare(mp3, sp, W, H, start, length, preroll=pre, final=True, env_all=env_all,
                    fade_in=k == 0, fade_out=k == nseg - 1, trans_in=tin, trans_out=tout)
        cmd = list(base)
        if start - pre > 0:
            cmd += ["-ss", f"{start - pre:.6f}"]
        cmd += ["-t", f"{length + pre + 1:.6f}", "-i", str(mp3), *_inputs(g),
                "-filter_complex", g.text(), "-map", "[v]", "-an",
                *video_args(s, W, H), "-threads", threads,
                "-frames:v", str(b - a), str(work / f"partie{k:03d}.mp4")]
        _run_ff(cmd, group, lambda sec: progress(k, min(length, sec)))
        progress(k, length)

    if set_proc:
        set_proc(group)
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(audio_task)] + [ex.submit(part_task, k) for k in range(nseg)]
            for f in as_completed(futs):
                if f.exception():
                    group.terminate()
                    ex.shutdown(cancel_futures=True)
                    raise f.exception()
        if on_progress:
            on_progress(99.0, "assemblage…")
        lst = work / "liste.txt"
        lst.write_text("".join(f"file 'partie{k:03d}.mp4'\n" for k in range(nseg)), encoding="utf-8")
        out.parent.mkdir(parents=True, exist_ok=True)
        part = out.with_name("." + out.stem + ".part.mp4")
        try:
            _run_ff(base + ["-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(work / "son.m4a"),
                            "-map", "0:v", "-map", "1:a", "-c", "copy", "-movflags", "+faststart",
                            str(part)], group)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        os.replace(part, out)
    finally:
        group.terminate()
        if set_proc:
            set_proc(None)
        shutil.rmtree(work, ignore_errors=True)


def convert_one(mp3: Path, s: dict, out: Path, on_progress=None, set_proc=None) -> None:
    ensure_tools()
    ff = TOOLS["ffmpeg"]
    if not ff:
        raise RuntimeError("FFmpeg introuvable")
    if not TOOLS["x264"]:
        raise RuntimeError("Ce ffmpeg n'inclut pas l'encodeur libx264")
    dur = probe(mp3)["duration"]
    if on_progress:
        on_progress(0, "préparation…")
    W, H = frame_size(s)
    plan = style_plan(s, dur, mp3.name)
    workers = parallel_workers(s, W, H)
    if len(plan) > 1 or (dur >= PARALLEL_MIN and workers > 1):
        return convert_parallel(mp3, s, out, dur, workers, plan, on_progress, set_proc)
    s = dict(s, style=plan[0][2])
    g = prepare(mp3, s, W, H, 0.0, dur, final=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name("." + out.stem + ".part.mp4")
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
           "-progress", "pipe:1", "-nostats",
           "-i", str(mp3), *_inputs(g),
           "-filter_complex", g.text(),
           "-map", "[v]", "-map", "0:a",
           *video_args(s, W, H), "-c:a", "aac", "-b:a", f"{s['audio_kbps']}k"]
    if dur:
        cmd += ["-t", f"{dur + 1:.3f}"]
    cmd += ["-shortest", "-movflags", "+faststart", str(part)]
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errlog:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errlog, stdin=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace", bufsize=1, **NO_WINDOW)
        if set_proc:
            set_proc(proc)
        speed = ""
        try:
            for line in proc.stdout:
                k, _, v = line.strip().partition("=")
                if k in ("out_time_us", "out_time_ms") and v.isdigit() and dur and on_progress:
                    on_progress(min(99.5, int(v) / 1e6 / dur * 100), speed)
                elif k == "speed":
                    speed = v.strip()
        finally:
            rc = proc.wait()
            if set_proc:
                set_proc(None)
        if rc != 0:
            part.unlink(missing_ok=True)
            errlog.seek(0)
            raise RuntimeError(last_line(errlog.read(), f"ffmpeg a échoué (code {rc})"))
    os.replace(part, out)


def render_preview(mp3: Path, s: dict) -> tuple[float, float, str]:
    """Petit extrait vidéo (quelques secondes, en basse définition) avec le son."""
    ensure_tools()
    ff = TOOLS["ffmpeg"]
    if not ff:
        raise RuntimeError("FFmpeg introuvable")
    total = probe(mp3)["duration"] or 10
    seg = min(PREVIEW_SECONDS, total)
    start = max(0.0, min(total * 0.35, total - seg))
    s = dict(s, style=style_at(style_plan(s, total, mp3.name), start))
    pre = {"spectrum": 12.0, "tunnel": 2.5}.get(s["style"], 0.0)
    pre = min(pre, start)
    W, H = frame_size(s, PREVIEW_SHORT)
    g = prepare(mp3, s, W, H, start, seg, preroll=pre)
    out = TMP / "preview.mp4"
    part = TMP / "preview.part.mp4"
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
           "-ss", f"{start - pre:.3f}", "-t", f"{seg + pre:.3f}", "-i", str(mp3), *_inputs(g),
           "-filter_complex", g.text(), "-map", "[v]", "-map", "0:a"]
    if pre:
        cmd += ["-af", f"atrim=start={pre:.3f},asetpts=PTS-STARTPTS"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "26", "-r", str(s["fps"]),
            "-c:a", "aac", "-b:a", "128k", "-t", f"{seg:.3f}", "-shortest",
            "-movflags", "+faststart", str(part)]
    r = run_text(cmd)
    if r.returncode != 0 or not part.exists():
        raise RuntimeError(last_line(r.stderr, "Échec de l'aperçu"))
    os.replace(part, out)
    return start, seg, s["style"]


# ──────────────────────────────────────────────────────────────────────────────
# File d'attente des conversions (interface)
# ──────────────────────────────────────────────────────────────────────────────

class Queue:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs: list[dict] = []
        self.running = False
        self.cancelled = False
        self.proc = None

    def snapshot(self) -> list[dict]:
        with self.lock:
            return [dict(j) for j in self.jobs]

    def start(self, names: list[str], per: dict, force: bool) -> str | None:
        with self.lock:
            if self.running:
                return "Une conversion est déjà en cours"
            self.jobs = [{"name": n, "status": "wait", "progress": 0, "speed": "", "error": ""}
                         for n in names]
            self.running, self.cancelled = True, False
        threading.Thread(target=self._work, args=(per, force), daemon=True).start()
        return None

    def cancel(self) -> None:
        with self.lock:
            self.cancelled = True
            proc = self.proc
        if proc:
            proc.terminate()

    def _set_proc(self, p) -> None:
        with self.lock:
            self.proc = p

    def _work(self, per: dict, force: bool) -> None:
        for job in self.jobs:
            if self.cancelled:
                job["status"] = "cancel"
                continue
            mp3 = INPUT_DIR / job["name"]
            out = OUTPUT_DIR / (mp3.stem + ".mp4")
            if not mp3.is_file():
                job.update(status="err", error="Fichier introuvable")
                continue
            if out.exists() and not force:
                job.update(status="skip", progress=100)
                continue
            job["status"] = "run"
            try:
                convert_one(mp3, per[job["name"]], out,
                            on_progress=lambda p, sp, j=job: j.update(progress=p, speed=sp),
                            set_proc=self._set_proc)
                job.update(status="ok", progress=100)
            except Exception as e:  # noqa: BLE001
                job.update(status="cancel" if self.cancelled else "err", error=str(e)[:300])
        with self.lock:
            self.running = False


QUEUE = Queue()


def open_path(p: Path) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        elif sys.platform == "win32":
            os.startfile(str(p))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except OSError:
        pass


def app_state() -> dict:
    ensure_tools()
    files = []
    for f in list_mp3():
        info = probe(f)
        p, src = cover_source(f, settings_for(f.name))
        files.append({"name": f.name, "duration": info["duration"], "cover_src": src,
                      "cover_v": short_hash(src, file_key(p))[:8],
                      "tag": f"{info['artist']} – {info['title']}".strip(" –") if info["title"] else "",
                      "done": (OUTPUT_DIR / (f.stem + ".mp4")).exists()})
    return {"files": files, "images": list_images(), "jobs": QUEUE.snapshot(),
            "running": QUEUE.running, "ffmpeg": TOOLS["ffmpeg"], "x264": TOOLS["x264"], "hw": bool(hw_encoder()),
            "title_ok": title_ok(), "settings": SETTINGS, "tracks": TRACK_SETTINGS,
            "input": str(INPUT_DIR), "output": str(OUTPUT_DIR)}


# ──────────────────────────────────────────────────────────────────────────────
# Serveur web local
# ──────────────────────────────────────────────────────────────────────────────

TOKEN = secrets.token_hex(16)
SETTINGS = load_settings()
TRACK_SETTINGS = load_track_settings()   # nom du fichier → réglages propres


def settings_for(name: str) -> dict:
    """Réglages utilisés pour un morceau (les siens si la playlist n'a pas des réglages communs)."""
    if not SETTINGS["same_for_all"] and name in TRACK_SETTINGS:
        return TRACK_SETTINGS[name]
    return SETTINGS
SERVER: ThreadingHTTPServer | None = None
ALLOWED_HOSTS: set[str] = set()
ACTIVITY = {"seen": time.monotonic(), "bye": 0.0}   # dernière visite de la page / onglet fermé
IDLE_QUIT = 600    # mode application : arrêt après 10 min sans aucun onglet ouvert…
BYE_GRACE = 20     # … ou 20 s après la fermeture de l'onglet (le temps d'un rechargement)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # pas de log dans le terminal
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in ALLOWED_HOSTS

    def _send_file(self, p: Path, ctype: str) -> None:
        """Envoi avec prise en charge des « Range » (nécessaire à la vidéo dans Safari)."""
        data = p.read_bytes()
        size = len(data)
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m and (m[1] or m[2]):
            if m[1]:
                a, b = int(m[1]), int(m[2]) if m[2] else size - 1
            else:
                a, b = max(0, size - int(m[2])), size - 1
            b = min(b, size - 1)
            if a > b:
                return self._send(416, b"", ctype, {"Content-Range": f"bytes */{size}"})
            return self._send(206, data[a:b + 1], ctype,
                              {"Content-Range": f"bytes {a}-{b}/{size}", "Accept-Ranges": "bytes"})
        self._send(200, data, ctype, {"Accept-Ranges": "bytes"})

    def _read_body(self, limit: int = 1 << 40) -> bytes | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            self.rfile.read(length)
            return None
        return self.rfile.read(length)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, b"Forbidden", "text/plain")
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path != "/api/ping":        # les vérifications d'un 2e lancement ne comptent pas
            ACTIVITY["seen"] = time.monotonic()
        if url.path == "/api/ping":
            self._json({"app": APP_NAME})
        elif url.path == "/":
            self._send(200, HTML.replace("__TOKEN__", TOKEN).encode(), "text/html; charset=utf-8")
        elif url.path == "/api/state":
            self._json(app_state())
        elif url.path == "/preview.mp4":
            p = TMP / "preview.mp4"
            if p.exists():
                self._send_file(p, "video/mp4")
            else:
                self._send(404, b"", "text/plain")
        elif url.path == "/api/thumb":
            mp3 = INPUT_DIR / Path(unquote(q.get("name", [""])[0])).name
            size = _clamp_int(q.get("s", ["160"])[0], 40, 600, 160)
            try:
                with ASSET_LOCK:
                    img, _ = track_cover(mp3, settings_for(mp3.name)) if mp3.is_file() else (None, "")
                    t = thumb(img, size) if img else None
            except RuntimeError:
                t = None
            if t:
                self._send(200, t.read_bytes(), "image/jpeg")
            else:
                self._send(404, b"", "text/plain")
        else:
            self._send(404, b"Not found", "text/plain")

    def do_POST(self):
        global SETTINGS
        url = urlparse(self.path)
        q = parse_qs(url.query)
        token = self.headers.get("X-Token") or q.get("t", [""])[0]
        if not self._host_ok() or token != TOKEN:
            return self._send(403, b"Forbidden", "text/plain")
        if url.path == "/api/bye":         # onglet fermé (navigator.sendBeacon)
            ACTIVITY["bye"] = time.monotonic()
            return self._send(204, b"", "text/plain")
        ACTIVITY["seen"] = time.monotonic()

        if url.path == "/api/upload":
            length = int(self.headers.get("Content-Length") or 0)
            name = Path(unquote(q.get("name", [""])[0])).name
            ext = Path(name).suffix.lower()
            if not name or name.startswith(".") or ext not in IMAGE_EXT | AUDIO_EXT:
                self.rfile.read(length)
                return self._json({"ok": False, "error": "Seuls les fichiers audio et les images sont acceptés"})
            INPUT_DIR.mkdir(parents=True, exist_ok=True)
            with open(INPUT_DIR / name, "wb") as fh:
                left = length
                while left > 0:
                    chunk = self.rfile.read(min(1 << 16, left))
                    if not chunk:
                        break
                    fh.write(chunk)
                    left -= len(chunk)
            return self._json({"ok": True, "name": name})

        if url.path == "/api/cover/upload":
            mp3 = INPUT_DIR / Path(unquote(q.get("name", [""])[0])).name
            ext = unquote(q.get("ext", [".jpg"])[0]).lower()
            data = self._read_body(40 << 20)
            if data is None:
                return self._json({"ok": False, "error": "Image trop lourde (40 Mo max)"})
            if not mp3.is_file() or ext not in IMAGE_EXT:
                return self._json({"ok": False, "error": "Choisis une image .jpg, .png ou .webp"})
            try:
                set_cover(mp3, data, ext)
                return self._json({"ok": True})
            except (RuntimeError, OSError) as e:
                return self._json({"ok": False, "error": str(e)[:300]})

        try:
            data = json.loads(self._read_body(10 << 20) or b"{}")
        except ValueError:
            data = {}

        if url.path == "/api/settings":
            track = Path(str(data.get("track") or "")).name
            if track:                          # réglages propres à un morceau
                TRACK_SETTINGS[track] = clean_settings(data.get("settings"))
                save_track_settings(TRACK_SETTINGS)
                return self._json({"ok": True, "settings": TRACK_SETTINGS[track]})
            SETTINGS = clean_settings(data.get("settings"))
            save_settings(SETTINGS)
            self._json({"ok": True, "settings": SETTINGS})
        elif url.path == "/api/track":
            name = Path(str(data.get("name") or "")).name
            if not name:
                return self._json({"ok": False, "error": "Morceau introuvable"})
            if data.get("action") == "make":
                TRACK_SETTINGS[name] = clean_settings(data.get("settings") or SETTINGS)
            else:
                TRACK_SETTINGS.pop(name, None)
            save_track_settings(TRACK_SETTINGS)
            self._json({"ok": True, "tracks": TRACK_SETTINGS})
        elif url.path == "/api/convert":
            ensure_tools()
            if not TOOLS["ffmpeg"]:
                return self._json({"ok": False, "error": "FFmpeg introuvable"})
            if data.get("settings"):
                SETTINGS = clean_settings(data.get("settings"))
                save_settings(SETTINGS)
            names = [Path(str(n)).name for n in data.get("files", []) if Path(str(n)).suffix.lower() in AUDIO_EXT]
            if not names:
                return self._json({"ok": False, "error": "Aucun morceau sélectionné"})
            per = {n: dict(settings_for(n)) for n in names}   # réglages de chaque morceau
            err = QUEUE.start(names, per, bool(data.get("force")))
            self._json({"ok": err is None, "error": err})
        elif url.path == "/api/cancel":
            QUEUE.cancel()
            self._json({"ok": True})
        elif url.path == "/api/preview":
            ensure_tools()
            s = clean_settings(data.get("settings"))
            mp3 = INPUT_DIR / Path(str(data.get("file", ""))).name
            if not mp3.is_file():
                return self._json({"ok": False, "error": "Choisis un morceau"})
            try:
                with PREVIEW_LOCK:
                    at, seg, st = render_preview(mp3, s)
                self._json({"ok": True, "at": at, "dur": seg, "style": st})
            except Exception as e:  # noqa: BLE001
                self._json({"ok": False, "error": str(e)[:300]})
        elif url.path == "/api/cover":
            mp3 = INPUT_DIR / Path(str(data.get("name", ""))).name
            if not mp3.is_file():
                return self._json({"ok": False, "error": "Morceau introuvable"})
            try:
                with ASSET_LOCK:
                    act = data.get("action")
                    if act == "remove":
                        remove_cover(mp3)
                    elif act == "embed":
                        if QUEUE.running:
                            raise RuntimeError("Attends la fin de la conversion en cours")
                        embed_cover(mp3, settings_for(mp3.name))
                    elif act == "use":
                        img = INPUT_DIR / Path(str(data.get("image", ""))).name
                        if not (img.is_file() and img.suffix.lower() in IMAGE_EXT):
                            raise RuntimeError("Image introuvable")
                        set_cover(mp3, img.read_bytes(), img.suffix.lower())
                    else:
                        raise RuntimeError("Action inconnue")
                self._json({"ok": True})
            except (RuntimeError, OSError) as e:
                self._json({"ok": False, "error": str(e)[:300]})
        elif url.path == "/api/open":
            what = data.get("what")
            if what == "input":
                open_path(INPUT_DIR)
            elif what == "output":
                open_path(OUTPUT_DIR)
            elif what == "video":
                v = OUTPUT_DIR / (Path(Path(str(data.get("name", ""))).name).stem + ".mp4")
                if v.is_file():
                    open_path(v)
            self._json({"ok": True})
        elif url.path == "/api/quit":
            self._json({"ok": True})
            QUEUE.cancel()
            threading.Thread(target=SERVER.shutdown, daemon=True).start()
        else:
            self._json({"ok": False, "error": "Inconnu"}, 404)


MAC_LAUNCHER = r'''#!/bin/bash
# Lanceur d'Onde2Vid (créé automatiquement par Onde2Vid.py)
APP="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="__SCRIPT__"
[ -f "$SCRIPT" ] || SCRIPT="$(dirname "$APP")/Onde2Vid.py"
PY=""
for P in "__PYTHON__" /opt/homebrew/bin/python3 /usr/local/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /usr/bin/python3; do
  if [ -x "$P" ]; then PY="$P"; break; fi
done
if [ -z "$PY" ] || [ ! -f "$SCRIPT" ]; then
  osascript -e 'display alert "Onde2Vid" message "Python 3 ou le fichier Onde2Vid.py est introuvable. Installe Python depuis python.org et garde Onde2Vid.app dans le dossier Onde2Vid." as critical' >/dev/null 2>&1
  exit 1
fi
cd "$(dirname "$SCRIPT")" || exit 1
nohup "$PY" "$SCRIPT" --app >/dev/null 2>&1 &
exit 0
'''

MAC_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Onde2Vid</string>
  <key>CFBundleDisplayName</key><string>Onde2Vid</string>
  <key>CFBundleIdentifier</key><string>io.github.ulrikadam.onde2vid</string>
  <key>CFBundleExecutable</key><string>Onde2Vid</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
"""


def _write_if_changed(p: Path, text: str, mode: int | None = None) -> bool:
    try:
        if p.read_text(encoding="utf-8", errors="replace") == text:
            return False
    except OSError:
        pass
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    if mode is not None:
        p.chmod(mode)
    return True


def _bash_inner(s: str) -> str:
    """Texte placé entre guillemets doubles dans un script bash."""
    return re.sub(r'([\\"$`])', r"\\\1", s)


def mac_app() -> bool:
    """Onde2Vid.app : une vraie application Mac (icône, pas de Terminal). True si elle vient d'être créée."""
    app = BUNDLE_DIR / f"{APP_NAME}.app"
    new = not app.exists()
    c = app / "Contents"
    launcher = (MAC_LAUNCHER.replace("__SCRIPT__", _bash_inner(str(Path(__file__).resolve())))
                .replace("__PYTHON__", _bash_inner(sys.executable or "")))
    changed = _write_if_changed(c / "MacOS" / APP_NAME, launcher, 0o755)
    changed |= _write_if_changed(c / "Info.plist", MAC_PLIST)
    icon, dst = BUNDLE_DIR / "assets" / "icon.icns", c / "Resources" / "icon.icns"
    if icon.is_file() and (not dst.is_file() or dst.stat().st_size != icon.stat().st_size):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(icon, dst)
        changed = True
    if changed:
        os.utime(app)                      # le Finder rafraîchit l'icône
    return new


def windows_shortcut() -> bool:
    """Raccourci « Onde2Vid » (avec l'icône) dans le menu Démarrer. True s'il vient d'être créé."""
    progs = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    lnk = progs / f"{APP_NAME}.lnk"
    if not progs.is_dir() or lnk.exists():
        return False
    if FROZEN:                             # Onde2Vid.exe contient déjà l'icône
        target, args, icon = Path(sys.executable), "", f"{sys.executable},0"
    else:
        exe = Path(sys.executable)
        target = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").is_file() else exe
        args = f'"{Path(__file__).resolve()}" --app'
        ico = BUNDLE_DIR / "assets" / "icon.ico"
        icon = f"{ico if ico.is_file() else target},0"
    env = dict(os.environ, O2V_LNK=str(lnk), O2V_TARGET=str(target), O2V_ARGS=args,
               O2V_DIR=str(target.parent if FROZEN else BUNDLE_DIR), O2V_ICON=icon)
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:O2V_LNK);"
          "$s.TargetPath=$env:O2V_TARGET;$s.Arguments=$env:O2V_ARGS;"
          "$s.WorkingDirectory=$env:O2V_DIR;$s.IconLocation=$env:O2V_ICON;"
          "$s.Description='Onde2Vid';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-Command", ps], env=env, capture_output=True, timeout=30, **NO_WINDOW)
    return lnk.exists()


def linux_desktop_entry(python: str, script: Path | None, icon: Path | None) -> str:
    def q(s) -> str:                       # règles de guillemets des fichiers .desktop
        s = str(s).replace("\\", "\\\\\\\\")
        return '"' + re.sub(r'(["`$])', r"\\\1", s) + '"'
    lines = ["[Desktop Entry]", "Type=Application", f"Name={APP_NAME}",
             "Comment=Transformer des MP3 en vidéos animées",
             f"Exec={q(python)} {q(script) + ' ' if script else ''}--app", "Terminal=false",
             "Categories=AudioVideo;Audio;Video;"]
    if icon:
        lines.append(f"Icon={icon}")
    return "\n".join(lines) + "\n"


def linux_desktop() -> bool:
    """Entrée « Onde2Vid » dans le menu des applications. True si elle vient d'être créée."""
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    p = base / "applications" / "onde2vid.desktop"
    new = not p.exists()
    icon = BUNDLE_DIR / "assets" / "icon.png"
    _write_if_changed(p, linux_desktop_entry(sys.executable, None if FROZEN else Path(__file__).resolve(),
                                             icon if icon.is_file() else None), 0o755)
    return new


def make_launcher() -> None:
    """Crée (ou met à jour) le raccourci qui lance Onde2Vid sans terminal."""
    try:
        if sys.platform == "darwin" and not FROZEN and mac_app():
            print(f"➜ {APP_NAME}.app a été créé dans le dossier : la prochaine fois, double-clique "
                  "dessus (tu peux aussi le glisser dans le Dock).")
        elif sys.platform == "win32" and not MS_STORE and windows_shortcut():
            print(f"➜ Raccourci « {APP_NAME} » ajouté au menu Démarrer.")
        elif sys.platform.startswith("linux") and linux_desktop():
            print(f"➜ « {APP_NAME} » a été ajouté au menu des applications.")
    except (OSError, subprocess.SubprocessError):
        pass


def find_running() -> str | None:
    """Adresse d'une interface Onde2Vid déjà ouverte sur cet ordinateur, sinon None."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for port in range(8765, 8785):
        url = f"http://127.0.0.1:{port}/"
        try:
            with opener.open(url + "api/ping", timeout=0.5) as r:
                if json.loads(r.read() or b"{}").get("app") == APP_NAME:
                    return url
        except (OSError, ValueError):
            continue
    return None


def watchdog() -> None:
    """Mode application : arrêt quand plus aucun onglet n'est ouvert (jamais pendant une conversion)."""
    while True:
        time.sleep(5)
        if QUEUE.running or PREVIEW_LOCK.locked():
            continue
        now, seen, bye = time.monotonic(), ACTIVITY["seen"], ACTIVITY["bye"]
        if (bye > seen and now - bye > BYE_GRACE) or now - seen > IDLE_QUIT:
            print("  Plus aucun onglet ouvert : arrêt automatique.")
            SERVER.shutdown()
            return


def start_log() -> None:
    """Mode application (sans terminal) : les messages vont dans onde2vid.log."""
    log = SCRIPT_DIR / "onde2vid.log"
    try:
        SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
        if log.exists() and log.stat().st_size > 1_000_000:
            log.unlink()
        fh = open(log, "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    sys.stdout = sys.stderr = fh
    print(f"\n── {time.strftime('%Y-%m-%d %H:%M:%S')} : démarrage d'{APP_NAME}")


def run_gui(open_browser: bool = True, app_mode: bool = False) -> None:
    global SERVER
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ensure_tools()
    make_launcher()
    running = find_running()
    if running:                            # déjà ouvert : on ramène simplement l'onglet
        print(f"\n  {APP_NAME} est déjà ouvert : {running}\n")
        if open_browser:
            webbrowser.open(running)
        shutil.rmtree(TMP, ignore_errors=True)
        return
    for port in list(range(8765, 8785)) + [0]:
        try:
            SERVER = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    port = SERVER.server_address[1]
    ALLOWED_HOSTS.update({f"127.0.0.1:{port}", f"localhost:{port}"})
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  {APP_NAME} — interface ouverte dans ton navigateur : {url}")
    if app_mode:
        print("  (mode application : arrêt automatique quand l'onglet est fermé)\n")
        threading.Thread(target=watchdog, daemon=True).start()
    else:
        print("  (laisse cette fenêtre ouverte ; Ctrl+C ou le bouton « Quitter » pour arrêter)\n")
    if not TOOLS["ffmpeg"]:
        print(f"  ⚠ FFmpeg introuvable : dépose le fichier 'ffmpeg' dans {SCRIPT_DIR}\n")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        SERVER.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        QUEUE.cancel()
        SERVER.server_close()
        shutil.rmtree(TMP, ignore_errors=True)
        print("  Interface fermée.")


# ──────────────────────────────────────────────────────────────────────────────
# Mode sans interface
# ──────────────────────────────────────────────────────────────────────────────

def run_batch(force: bool) -> None:
    ensure_tools()
    if not TOOLS["ffmpeg"]:
        sys.exit(f"FFmpeg introuvable : dépose le fichier 'ffmpeg' dans {SCRIPT_DIR}")
    s, tracks = load_settings(), load_track_settings()
    files = list_mp3()
    if not files:
        sys.exit(f"Aucun fichier audio dans {INPUT_DIR}")
    ok = 0
    for i, mp3 in enumerate(files, 1):
        out = OUTPUT_DIR / (mp3.stem + ".mp4")
        if out.exists() and not force:
            print(f"[{i}/{len(files)}] {mp3.name} — déjà converti")
            continue

        def show(p, sp, name=mp3.name):
            print(f"\r[{i}/{len(files)}] {name}  {p:5.1f} %  {sp}   ", end="", flush=True)

        try:
            own = None if s["same_for_all"] else tracks.get(mp3.name)
            convert_one(mp3, own or s, out, on_progress=show)
            print(f"\r[{i}/{len(files)}] {mp3.name}  ✓" + " " * 20)
            ok += 1
        except RuntimeError as e:
            print(f"\r[{i}/{len(files)}] {mp3.name}  ✗ {e}")
    print(f"\nTerminé : {ok} vidéo(s) créée(s) dans {OUTPUT_DIR}")
    shutil.rmtree(TMP, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────────────
# Page de l'interface
# ──────────────────────────────────────────────────────────────────────────────

HTML = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Onde2Vid</title>
<link rel="icon" href="data:image/svg+xml,__FAVICON__">
<style>
:root{--bg:#f2f2f5;--panel:#fff;--panel2:#f6f6f9;--line:#e3e3ea;--text:#17171c;--muted:#6d6d79;
--accent:#6b5cff;--accent2:#ff3df5;--ok:#13a06a;--warn:#c98200;--err:#d42f48;--sel:rgba(107,92,255,.09);
--shadow:0 1px 2px rgba(0,0,0,.04),0 6px 20px rgba(0,0,0,.04)}
@media (prefers-color-scheme:dark){:root{--bg:#0d0d11;--panel:#16161c;--panel2:#1c1c23;--line:#292932;
--text:#ececf2;--muted:#8f8f9c;--sel:rgba(107,92,255,.16);--shadow:none}}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}
button,select,input{font:inherit;color:inherit}
.credit{font-size:12.5px;color:var(--muted);text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}.credit:hover{color:var(--text);text-decoration:underline}
header{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:14px;padding:12px 22px;background:color-mix(in srgb,var(--panel) 88%,transparent);backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.logo{width:38px;height:38px;flex:none}
.logo svg{width:100%;height:100%;display:block}
header h1{font-size:15.5px;margin:0;letter-spacing:-.01em}
header .sub{font-size:12.5px;color:var(--muted)}
.grow{flex:1}
.pill{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:99px;font-size:12px;background:var(--panel2);border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.dot{width:7px;height:7px;border-radius:50%;background:var(--ok)}
.pill.bad .dot{background:var(--err)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;border:1px solid var(--line);background:var(--panel);border-radius:9px;padding:7px 12px;cursor:pointer;font-size:13px;white-space:nowrap}
.btn:hover{border-color:color-mix(in srgb,var(--text) 25%,var(--line))}
.btn:disabled{opacity:.45;cursor:default}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600;padding:11px 22px;font-size:14.5px;border-radius:11px}
.btn.primary:hover{filter:brightness(1.06)}
.btn.ghost{border-color:transparent;background:transparent;color:var(--muted)}
.btn.small{padding:4px 9px;font-size:12px;border-radius:7px}
main{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.25fr);gap:18px;padding:18px 22px 120px;max-width:1440px;margin:0 auto}
@media (max-width:1000px){main{grid-template-columns:1fr}}
.col{display:flex;flex-direction:column;gap:18px;min-width:0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);min-width:0}
.card-h{display:flex;align-items:center;gap:8px;padding:14px 16px 10px}
.card-h h2{margin:0;font-size:12px;font-weight:650;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
.card-b{padding:4px 16px 16px}
.drop{display:block;cursor:pointer;border:1.5px dashed var(--line);border-radius:11px;padding:14px;text-align:center;color:var(--muted);font-size:13px;margin-bottom:10px;transition:.15s}
.drop b{color:var(--text);font-weight:600}
.drop.hot,body.dragging .drop{border-color:var(--accent);background:var(--sel);color:var(--text)}
.toolbar{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.files{display:flex;flex-direction:column;gap:2px;max-height:56vh;overflow:auto;margin:0 -6px;padding:0 6px}
.file{display:flex;align-items:center;gap:10px;padding:7px 10px;border-radius:9px;cursor:pointer;border:1px solid transparent}
.file:hover{background:var(--panel2)}
.file.sel{background:var(--sel);border-color:color-mix(in srgb,var(--accent) 35%,transparent)}
.file.hot{outline:2px solid var(--accent)}
.file input{accent-color:var(--accent);width:16px;height:16px;flex:none;cursor:pointer}
.thumb{width:42px;height:42px;border-radius:8px;flex:none;border:1.5px dashed color-mix(in srgb,var(--muted) 55%,transparent);background:var(--panel2);display:grid;place-items:center;color:var(--muted);font-size:20px;cursor:pointer;overflow:hidden;padding:0;position:relative}
.thumb:hover{border-color:var(--accent);color:var(--accent)}
.thumb.has{border-style:solid;border-color:var(--line)}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.thumb.dflt img{opacity:.4}
.fname{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fname small{display:block;color:var(--muted);font-size:11.5px;overflow:hidden;text-overflow:ellipsis}
.fmeta{display:flex;gap:6px;align-items:center;color:var(--muted);font-size:12px;flex:none}
.tag{font-size:11px;padding:1px 7px;border-radius:99px;background:var(--panel2);border:1px solid var(--line);color:var(--muted)}
.tag.done{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 40%,transparent)}
.empty{color:var(--muted);text-align:center;padding:26px 10px;font-size:13px}
.styles{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin-bottom:14px}
@media (max-width:640px){.styles{grid-template-columns:repeat(4,minmax(0,1fr))}}
.style{border:1.5px solid var(--line);border-radius:11px;padding:9px 4px 7px;text-align:center;cursor:pointer;background:var(--panel);transition:.12s}
.style:hover{border-color:color-mix(in srgb,var(--text) 25%,var(--line))}
.style.on{border-color:var(--accent);background:var(--sel)}
.style svg{width:100%;height:32px;display:block;margin-bottom:4px}
.style span{font-size:11.5px;font-weight:550}
.style.new span::after{content:" ★";color:var(--accent2)}
.style{position:relative}.style .rk{position:absolute;top:4px;right:6px;font-size:10.5px;font-weight:700;color:var(--accent)}
.scope{display:flex;align-items:center;gap:10px;padding:8px 12px;margin-bottom:12px;border-radius:10px;background:var(--panel2);border:1px solid var(--line);font-size:13px}
.scope.own{border-color:var(--accent);background:var(--sel)}
.scope b{font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.rotbox{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin:-4px 0 14px}
.rotbox .hint{flex-basis:100%;font-size:12.5px;color:var(--muted)}
.samebar{display:flex;align-items:center;margin:2px 0 8px}
.mycv{display:flex;align-items:center;gap:10px;min-width:0}.mycv span{flex:1;min-width:0;font-size:12.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tag.own{color:var(--accent);border-color:color-mix(in srgb,var(--accent) 45%,transparent)}
.sect{border-top:1px solid var(--line);padding-top:12px;margin-top:6px}
.sect h3{font-size:12px;margin:0 0 8px;color:var(--muted);font-weight:600}
.row{display:grid;grid-template-columns:128px minmax(0,1fr);align-items:center;gap:10px;min-height:36px;margin-bottom:4px}
.row>label:first-child{color:var(--muted);font-size:13px}
.row.hide{display:none}
select,input[type=text]{width:100%;padding:7px 10px;border-radius:9px;border:1px solid var(--line);background:var(--panel2)}
input[type=color]{width:46px;height:30px;padding:0 2px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);cursor:pointer}
input[type=range]{width:100%;accent-color:var(--accent)}
.inline{display:flex;align-items:center;gap:10px}
.inline output{min-width:44px;text-align:right;font-variant-numeric:tabular-nums;color:var(--muted)}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden;background:var(--panel2)}
.seg label{padding:6px 12px;cursor:pointer;font-size:13px;border-right:1px solid var(--line)}
.seg label:last-child{border-right:0}
.seg input{display:none}
.seg input:checked+span{color:var(--accent);font-weight:600}
.check{display:flex;align-items:center;gap:8px;cursor:pointer}
.check input{accent-color:var(--accent);width:16px;height:16px}
.hint{font-size:12px;color:var(--muted);margin:4px 0 0}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:0 18px}
@media (max-width:700px){.grid2{grid-template-columns:1fr}.row{grid-template-columns:120px minmax(0,1fr)}}
.screen{position:relative;aspect-ratio:16/9;border-radius:10px;overflow:hidden;background:#000;display:grid;place-items:center}
.screen video{width:100%;height:100%;object-fit:contain;display:block;background:#000}
.screen .ph{color:#8a8a96;font-size:13px;text-align:center;padding:20px}
.screen .busy{position:absolute;inset:0;display:none;place-items:center;background:rgba(0,0,0,.55);color:#fff;font-size:13px}
.screen.loading .busy{display:grid}
.spin{width:26px;height:26px;border-radius:50%;border:3px solid rgba(255,255,255,.25);border-top-color:#fff;animation:sp 0.8s linear infinite;margin:0 auto 8px}
@keyframes sp{to{transform:rotate(360deg)}}
.pv-bar{display:flex;align-items:center;gap:10px;margin-top:10px}
.pv-bar .lbl{flex:1;color:var(--muted);font-size:12.5px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.err{color:var(--err)}
.job{padding:8px 0;border-bottom:1px solid var(--line)}
.job:last-child{border-bottom:0}
.job-top{display:flex;gap:10px;align-items:center;font-size:13px}
.job-top .fname{font-weight:500}
.job-st{font-size:12px;color:var(--muted);flex:none}
.job-st.ok{color:var(--ok)}.job-st.err{color:var(--err)}
.bar{height:5px;border-radius:9px;background:var(--panel2);overflow:hidden;margin-top:6px}
.bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--accent),var(--accent2));transition:width .4s}
.job.ok .bar i{background:var(--ok)}
.job-err{font-size:12px;color:var(--err);margin-top:4px;word-break:break-word}
.action{position:fixed;left:0;right:0;bottom:0;z-index:10;display:flex;align-items:center;gap:16px;padding:12px 22px;background:color-mix(in srgb,var(--panel) 92%,transparent);backdrop-filter:blur(12px);border-top:1px solid var(--line)}
.action .sum{color:var(--muted);font-size:13px}
@media (max-width:640px){.action{flex-wrap:wrap;gap:8px 12px;padding:10px 16px}.action .sum,.action .grow{display:none}.action .btn.primary{width:100%}header .sub{display:none}main{padding:14px 14px 150px}}
.warnbox{background:color-mix(in srgb,var(--warn) 12%,var(--panel));border:1px solid color-mix(in srgb,var(--warn) 40%,transparent);border-radius:11px;padding:12px 14px;font-size:13px}
.warnbox code{font-size:12px;background:var(--panel2);padding:1px 5px;border-radius:5px;word-break:break-all}
.overlay{position:fixed;inset:0;z-index:50;display:none;place-items:center;background:rgba(0,0,0,.55);padding:16px}
.overlay.on{display:grid}
.overlay>div{background:var(--panel);padding:22px 24px;border-radius:14px;max-width:440px;width:100%;text-align:center}
.overlay h3{margin:0 0 12px;font-size:15px;word-break:break-word}
.cv{width:220px;height:220px;margin:0 auto 10px;border-radius:12px;overflow:hidden;background:var(--panel2);display:grid;place-items:center;color:var(--muted);border:1px solid var(--line)}
.cv img{width:100%;height:100%;object-fit:cover;display:block}
.dlg-btns{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:14px}
.dlg-btns select{width:auto;max-width:100%}
</style>
</head>
<body>
<header>
  <div class="logo">__LOGO__</div>
  <div><h1>Onde2Vid</h1><div class="sub">Ta musique en vidéos animées pour YouTube</div></div>
  <div class="grow"></div>
  <a class="credit" href="https://nexadam.be" target="_blank" rel="noopener">Développé par Adam Ulrik · nexadam.be</a>
  <span class="pill" id="ffpill"><span class="dot"></span><span id="fftext">…</span></span>
  <button class="btn ghost" id="quit">Quitter</button>
</header>

<main>
  <div class="col">
    <div class="card" id="warnCard" style="display:none"><div class="card-b" style="padding-top:16px"><div class="warnbox" id="warnBox"></div></div></div>

    <div class="card">
      <div class="card-h"><h2>Morceaux</h2><div class="grow"></div><span class="pill" id="count">0</span></div>
      <div class="card-b">
        <label class="drop" id="drop">
          <b>Glisse tes morceaux ici</b> (MP3, WAV, FLAC, M4A, OGG… et des images si tu veux)<br>ou clique pour choisir des fichiers
          <input type="file" id="picker" multiple accept="audio/*,__AUDIO_ACCEPT__,image/*" hidden>
        </label>
        <div class="toolbar">
          <button class="btn small" id="all">Tout cocher</button>
          <button class="btn small" id="none">Tout décocher</button>
          <div class="grow"></div>
          <button class="btn small" id="openIn">Dossier input</button>
          <button class="btn small" id="openOut">Dossier output</button>
        </div>
        <div class="samebar"><label class="check"><input type="checkbox" id="same"><span>Mêmes réglages pour toute la playlist</span></label></div>
        <div class="files" id="files"></div>
        <p class="hint" id="filesHint"></p>
      </div>
    </div>

    <div class="card" id="jobsCard" style="display:none">
      <div class="card-h"><h2>Conversion</h2><div class="grow"></div><button class="btn small" id="cancel">Annuler</button></div>
      <div class="card-b" id="jobs"></div>
    </div>
  </div>

  <div class="col">
    <div class="card">
      <div class="card-h"><h2>Aperçu</h2></div>
      <div class="card-b">
        <div class="screen" id="screen">
          <div class="ph" id="ph">Choisis un morceau puis clique sur « Générer l'aperçu »<br>pour voir quelques secondes avec tes réglages.</div>
          <video id="pvvid" controls playsinline loop hidden></video>
          <div class="busy"><div><div class="spin"></div>Rendu en cours…</div></div>
        </div>
        <div class="pv-bar"><span class="lbl" id="pvlbl">—</span><button class="btn" id="preview">Générer l'aperçu</button></div>
      </div>
    </div>

    <div class="card">
      <div class="card-h"><h2>Réglages</h2><div class="grow"></div><button class="btn small ghost" id="reset">Valeurs par défaut</button></div>
      <div class="card-b">
        <div class="scope" id="scope"><span id="scopeTxt"></span><div class="grow"></div><button class="btn small" id="scopeBtn"></button></div>
        <div class="styles" id="styles"></div>
        <div class="rotbox">
          <label class="check"><input type="checkbox" data-k="rotate"><span>Changer de visualiseur pendant le morceau</span></label>
          <span class="inline" id="rotOpts"><span style="white-space:nowrap">toutes les</span>
            <select data-k="rotate_minutes"><option value="1">1 min</option><option value="2">2 min</option><option value="3">3 min</option><option value="5">5 min</option><option value="10">10 min</option><option value="15">15 min</option><option value="20">20 min</option><option value="30">30 min</option></select>
            <select data-k="rotate_order"><option value="random">au hasard</option><option value="order">dans l'ordre</option></select></span>
          <div class="hint" id="rotHint"></div>
        </div>

        <div class="grid2">
          <div>
            <div class="row" id="r-scheme"><label>Couleurs</label>
              <select data-k="colors">
                <option value="neon">Néon</option><option value="rainbow">Arc-en-ciel</option>
                <option value="fire">Feu</option><option value="ice">Glace</option>
                <option value="sunset">Coucher de soleil</option><option value="vu">Vumètre (vert → rouge)</option>
                <option value="cover">Couleurs de la jaquette</option>
                <option value="duo">Dégradé 2 couleurs</option><option value="solid">Couleur unie</option>
              </select></div>
            <div class="row" id="r-color"><label>Couleur</label><div class="inline"><input type="color" data-k="color"><input type="color" data-k="color2" id="color2"></div></div>
            <div class="row" id="r-palette"><label>Palette</label>
              <select data-k="palette">
                <option value="intensity">Intensité</option><option value="rainbow">Arc-en-ciel</option>
                <option value="fire">Feu</option><option value="cool">Froid</option><option value="magma">Magma</option>
                <option value="viridis">Viridis</option><option value="plasma">Plasma</option><option value="nebulae">Nébuleuse</option>
              </select></div>
            <div class="row" id="r-glow"><label>Lueur</label><label class="check"><input type="checkbox" data-k="glow"><span>Effet néon</span></label></div>
          </div>
          <div>
            <div class="row"><label id="l-size">Taille</label><div class="inline"><input type="range" min="15" max="100" step="5" data-k="viz_size"><output id="o-size"></output></div></div>
            <div class="row" id="r-sens"><label>Sensibilité</label><div class="inline"><input type="range" min="0" max="100" step="5" data-k="sensitivity"><output id="o-sens"></output></div></div>
            <div class="row" id="r-pos"><label>Position</label>
              <div class="seg">
                <label><input type="radio" name="pos" value="top" data-k="viz_pos"><span>Haut</span></label>
                <label><input type="radio" name="pos" value="center" data-k="viz_pos"><span>Centre</span></label>
                <label><input type="radio" name="pos" value="bottom" data-k="viz_pos"><span>Bas</span></label>
              </div></div>
          </div>
        </div>

        <div class="sect">
          <h3>Jaquette et fond</h3>
          <div class="grid2">
            <div>
              <div class="row"><label>Jaquette de ce morceau</label>
                <div class="mycv"><button class="thumb" id="myCv" title="Changer la jaquette de ce morceau"></button><span id="myCvTxt"></span><button class="btn small" id="myCvBtn">Changer…</button></div></div>
              <div class="row"><label>Jaquette au centre</label>
                <select data-k="layout">
                  <option value="auto">Automatique</option>
                  <option value="cover">Carrée</option>
                  <option value="round">Ronde</option>
                  <option value="fill">Aucune (image plein écran)</option>
                </select></div>
              <div class="row" title="Utilisée pour les morceaux qui n'ont pas de jaquette"><label>Jaquette par défaut (morceaux sans jaquette)</label>
                <div class="inline"><select data-k="cover_default" id="defSel"></select><label class="btn small" title="Importer une image">Importer…<input type="file" id="defPick" accept="image/*" hidden></label></div></div>
            </div>
            <div>
              <div class="row"><label>Fond</label><select data-k="image" id="imgSel"></select></div>
              <div class="row" id="r-effect"><label>Effet sur le fond</label>
                <select data-k="effect">
                  <option value="both">Flou + assombri</option><option value="blur">Flou</option>
                  <option value="dark">Assombri</option><option value="none">Aucun</option>
                </select></div>
              <div class="row" id="r-bg"><label>Couleur de fond</label><input type="color" data-k="bg_color"></div>
            </div>
          </div>
        </div>

        <div class="sect">
          <h3>Animation et texte</h3>
          <div class="grid2">
            <div>
              <div class="row"><label>Pulsation (basses)</label><div class="inline"><input type="range" min="0" max="100" step="10" data-k="pulse"><output id="o-pulse"></output></div></div>
              <div class="row" id="r-pulsebg"><label>Fond</label><label class="check"><input type="checkbox" data-k="pulse_bg"><span>Le fond pulse aussi</span></label></div>
              <div class="row"><label>Fondu</label><label class="check"><input type="checkbox" data-k="fade"><span>Fondu au noir début / fin</span></label></div>
            </div>
            <div>
              <div class="row"><label>Titre</label>
                <select id="titleSel"><option value="auto">Tags (artiste – titre)</option><option value="file">Nom du fichier</option><option value="none">Aucun</option></select></div>
              <div class="row"><label>2e ligne</label><input type="text" data-k="subtitle" maxlength="80" placeholder="ex. nom de ta chaîne"></div>
              <div class="row"><label>Progression</label><label class="check"><input type="checkbox" data-k="progress"><span>Barre en bas de l'image</span></label></div>
            </div>
          </div>
          <p class="hint" id="titleWarn" hidden>Titre indisponible avec ce ffmpeg (pas de filtre drawtext).</p>
        </div>

        <div class="sect">
          <h3>Vidéo</h3>
          <div class="grid2">
            <div>
              <div class="row"><label>Format</label>
                <select data-k="aspect"><option value="16:9">16:9 (YouTube)</option><option value="9:16">9:16 (Shorts, TikTok)</option><option value="1:1">1:1 (carré)</option></select></div>
              <div class="row"><label>Résolution</label>
                <select data-k="resolution"><option value="720p">720p</option><option value="1080p">1080p</option><option value="1440p">1440p</option><option value="4k">4K</option></select></div>
              <div class="row"><label>Images / seconde</label>
                <select data-k="fps"><option value="24">24</option><option value="25">25</option><option value="30">30</option><option value="50">50</option><option value="60">60 (très fluide)</option></select></div>
            </div>
            <div>
              <div class="row"><label>Qualité vidéo</label>
                <select data-k="crf"><option value="23">Standard</option><option value="20">Haute</option><option value="17">Très haute</option><option value="14">Maximale (gros fichiers)</option></select></div>
              <div class="row"><label>Compression</label>
                <select data-k="compression"><option value="fast" id="hwOpt">Rapide (puce graphique, fichiers plus gros)</option><option value="compact">Compacte (processeur, fichiers plus petits)</option></select></div>
              <div class="row" id="presetRow"><label>Vitesse (mode compact)</label>
                <select data-k="preset"><option value="veryfast">Normale</option><option value="medium">Équilibrée</option><option value="slow">Lente (fichier plus léger)</option></select></div>
              <div class="row"><label>Audio</label>
                <select data-k="audio_kbps"><option value="192">AAC 192 kb/s</option><option value="256">AAC 256 kb/s</option><option value="320">AAC 320 kb/s</option></select></div>
            </div>
          </div>
          <p class="hint">Astuce YouTube : en 1440p ou 4K, YouTube réencode avec un meilleur codec et le visualiseur reste plus net, mais la conversion est plus longue.</p>
        </div>
      </div>
    </div>
  </div>
</main>

<div class="action">
  <label class="check"><input type="checkbox" id="force"><span>Refaire les vidéos déjà converties</span></label>
  <div class="grow"></div>
  <span class="sum" id="sum"></span>
  <button class="btn primary" id="go">Convertir</button>
</div>

<div class="overlay" id="coverDlg"><div>
  <h3 id="cvTitle">Jaquette</h3>
  <div class="cv"><img id="cvImg" alt="" hidden><span id="cvNone">Pas de jaquette</span></div>
  <p class="hint" id="cvInfo"></p>
  <div class="dlg-btns">
    <label class="btn">Choisir une image…<input type="file" id="cvPick" accept="image/*" hidden></label>
    <select id="cvUse"></select>
  </div>
  <div class="dlg-btns">
    <button class="btn" id="cvEmbed" title="Écrit la jaquette dans le fichier MP3 (le son n'est pas modifié)">Intégrer dans le MP3</button>
    <button class="btn" id="cvRemove">Retirer</button>
    <button class="btn primary" id="cvClose" style="padding:7px 16px;font-size:13px">Fermer</button>
  </div>
  <p class="hint err" id="cvErr"></p>
</div></div>

<div class="overlay" id="offline"><div><h3>Interface arrêtée</h3><p id="offMsg">Onde2Vid ne répond plus (il s'arrête tout seul quand son onglet reste fermé). Relance-le pour continuer.</p></div></div>

<script>
const TOKEN = "__TOKEN__";
const ticks = (n, r, lens) => Array.from({length:n},(_,i)=>{const a=i/n*2*Math.PI, l=lens[i%lens.length];
  return `<line x1="${(30+Math.sin(a)*r).toFixed(1)}" y1="${(17-Math.cos(a)*r).toFixed(1)}" x2="${(30+Math.sin(a)*(r+l)).toFixed(1)}" y2="${(17-Math.cos(a)*(r+l)).toFixed(1)}"/>`;}).join("");
const STYLES = {
  circle:["Cercle",'<svg viewBox="0 0 60 34"><defs><linearGradient id="gc" x1="0" x2="1"><stop offset="0" stop-color="#00e5ff"/><stop offset="1" stop-color="#ff3df5"/></linearGradient></defs><g stroke="url(#gc)" stroke-width="2" stroke-linecap="round">'+ticks(18,8,[6,3,5,2,7,4])+'</g><circle cx="30" cy="17" r="6" fill="currentColor" opacity=".8"/></svg>',1],
  retro:["Rétro LED",'<svg viewBox="0 0 60 34">'+[5,8,6,9,4,7,3,6].map((n,i)=>Array.from({length:n},(_,j)=>`<rect x="${4+i*6.8}" y="${30-j*3.3}" width="5" height="2.4" fill="${j>6?"#ff3d3d":j>4?"#ffd23d":"#22e05a"}"/>`).join("")).join("")+'</svg>',1],
  mirror:["Miroir",'<svg viewBox="0 0 60 34"><defs><linearGradient id="gm" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#ff3d00"/><stop offset="1" stop-color="#ffe14d"/></linearGradient></defs>'+[3,5,7,10,13,10,7,5,3].map((h,i)=>`<rect x="${4+i*6}" y="${21-h}" width="4.4" height="${h}" fill="url(#gm)"/><rect x="${4+i*6}" y="22" width="4.4" height="${h*0.5}" fill="url(#gm)" opacity=".4"/>`).join("")+'</svg>',1],
  tunnel:["Tunnel",'<svg viewBox="0 0 60 34" fill="none" stroke="currentColor"><circle cx="30" cy="17" r="3" opacity=".9"/><circle cx="30" cy="17" r="7" opacity=".6"/><circle cx="30" cy="17" r="11.5" opacity=".4"/><circle cx="30" cy="17" r="16" opacity=".25"/><path d="M30 1 L30 33 M14 17 L46 17 M19 6 L41 28 M41 6 L19 28" opacity=".3"/></svg>',1],
  cubes:["Cubes",'<svg viewBox="0 0 60 34">'+[.9,.3,.6,.2,.8,.4,.5,1,.3,.7,.2,.6,.4,.8,.5,.3,.9,.2].map((o,i)=>`<rect x="${6+(i%6)*8.2}" y="${3+Math.floor(i/6)*10}" width="7" height="8.6" rx="1" fill="#ff3d5a" opacity="${o}"/>`).join("")+'</svg>',1],
  aurora:["Aurore",'<svg viewBox="0 0 60 34" fill="none" stroke-width="1.6" stroke-linecap="round"><path d="M2 20 C12 4 20 30 30 15 S48 6 58 18" stroke="#3dff7a"/><path d="M2 16 C14 26 22 6 32 19 S50 26 58 12" stroke="#00d5ff" opacity=".8"/><path d="M2 23 C10 12 24 26 34 10 S52 22 58 22" stroke="#b33dff" opacity=".7"/></svg>',1],
  cqt:["Barres piano",'<svg viewBox="0 0 60 34"><defs><linearGradient id="g1" x1="0" x2="1"><stop offset="0" stop-color="#ff3d6e"/><stop offset=".5" stop-color="#ffd23d"/><stop offset="1" stop-color="#3dd5ff"/></linearGradient></defs>'+[6,14,22,11,27,18,9,24,15,7,20,12].map((h,i)=>`<rect x="${2+i*4.8}" y="${32-h}" width="3.4" height="${h}" rx="1" fill="url(#g1)"/>`).join("")+'</svg>'],
  bars:["Égaliseur",'<svg viewBox="0 0 60 34">'+[10,20,28,22,16,24,12,18,8,14].map((h,i)=>`<rect x="${3+i*5.6}" y="${32-h}" width="4" height="${h}" rx="1" fill="currentColor" opacity=".85"/>`).join("")+'</svg>'],
  waves:["Onde",'<svg viewBox="0 0 60 34"><path d="M2 17 Q6 4 10 17 T18 17 T26 17 Q30 28 34 17 T42 17 Q46 8 50 17 T58 17" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>'],
  spectrum:["Spectrogramme",'<svg viewBox="0 0 60 34"><defs><linearGradient id="g2" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#2a0a5e"/><stop offset=".5" stop-color="#e0407a"/><stop offset="1" stop-color="#ffe08a"/></linearGradient></defs>'+Array.from({length:14},(_,i)=>`<rect x="${2+i*4}" y="${4+((i*7)%9)}" width="3.6" height="${28-((i*7)%9)}" fill="url(#g2)" opacity="${.45+((i*3)%5)/9}"/>`).join("")+'</svg>'],
  scope:["Oscilloscope",'<svg viewBox="0 0 60 34"><path d="M30 4 C44 4 44 30 30 30 C16 30 16 4 30 4 Z M22 10 L38 24 M38 10 L22 24" fill="none" stroke="currentColor" stroke-width="1.8" opacity=".85"/></svg>']
};
const MASK = ["circle","retro","mirror","cubes","aurora"], ROUND = ["circle","tunnel"], CQT = ["circle","retro","mirror","cubes"];
let S = null, settings = null, checked = new Set(), seen = new Set(), selected = null, saveT = null, lastImgs = "", cvName = null;
let globalSet = null, tracks = {}, pendingSave = null;   // réglages communs / propres à certains morceaux
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const fmt = d => { d = Math.round(d||0); return Math.floor(d/60) + ":" + String(d%60).padStart(2,"0"); };
const enc = encodeURIComponent;

async function post(url, data){
  try{
    const r = await fetch(url,{method:"POST",headers:{"Content-Type":"application/json","X-Token":TOKEN},body:JSON.stringify(data||{})});
    return await r.json();
  }catch(e){ return {ok:false,error:"Le programme ne répond pas"}; }
}
async function sendFile(url, file){
  try{ const r = await fetch(url,{method:"POST",headers:{"X-Token":TOKEN},body:file}); return await r.json(); }
  catch(e){ return {ok:false,error:"Le programme ne répond pas"}; }
}
const extOf = n => { const m = /\.[^.]+$/.exec(n||""); return m ? m[0].toLowerCase() : ""; };
const isImg = f => /^image\//.test(f.type) || [".jpg",".jpeg",".png",".webp"].includes(extOf(f.name));

/* ── réglages ── */
function buildStyles(){
  const box = $("#styles"); box.innerHTML = "";
  for (const [k,[name,svg,isNew]] of Object.entries(STYLES)){
    const b = el("div","style" + (isNew ? " new" : "")); b.dataset.style = k; b.title = name;
    b.innerHTML = svg; b.appendChild(el("span",null,name));
    b.onclick = () => {
      if (settings.rotate){
        const r = settings.rotate_styles, i = r.indexOf(k);
        if (i >= 0) r.splice(i, 1); else r.push(k);
        if (r.length) settings.style = r[0];
      } else settings.style = k;
      applySettings(); changed();
    };
    box.appendChild(b);
  }
}
function applySettings(){
  const rot = settings.rotate;
  $$(".style").forEach(b => {
    const k = b.dataset.style, i = settings.rotate_styles.indexOf(k);
    b.classList.toggle("on", rot ? i >= 0 : k === settings.style);
    let rk = b.querySelector(".rk");
    if (rot && i >= 0){ if (!rk){ rk = el("i","rk"); b.appendChild(rk); } rk.textContent = settings.rotate_order === "order" ? i + 1 : "✓"; }
    else if (rk) rk.remove();
  });
  $("#rotOpts").hidden = !rot;
  $("#rotHint").textContent = !rot ? "" : rotHint();
  $$("[data-k]").forEach(inp => {
    const v = settings[inp.dataset.k];
    if (inp.type === "radio") inp.checked = (inp.value === String(v));
    else if (inp.type === "checkbox") inp.checked = !!v;
    else if (inp !== document.activeElement || inp.type !== "text") inp.value = String(v);
  });
  const st = settings.style, img = settings.image;
  const sts = rot && settings.rotate_styles.length ? settings.rotate_styles : [st];   // visualiseurs utilisés
  const mask = sts.some(x => MASK.includes(x)), rnd = sts.every(x => ROUND.includes(x));
  $("#o-size").textContent = (!rnd && settings.viz_size >= 100) ? "Plein" : settings.viz_size + " %";
  $("#o-sens").textContent = settings.sensitivity + " %";
  $("#o-pulse").textContent = settings.pulse ? settings.pulse + " %" : "Aucune";
  $("#l-size").textContent = rnd ? "Taille du cercle" : "Taille";
  const solid = ["solid","duo"].includes(settings.colors);
  $("#r-scheme").classList.toggle("hide", !mask);
  $("#r-color").classList.toggle("hide", !(sts.some(x => ["waves","bars","scope"].includes(x)) || (mask && solid)));
  $("#color2").hidden = !(mask && settings.colors === "duo");
  $("#r-palette").classList.toggle("hide", !sts.some(x => ["spectrum","tunnel"].includes(x)));
  $("#r-glow").classList.toggle("hide", !mask);
  $("#r-sens").classList.toggle("hide", !sts.some(x => CQT.includes(x)));
  $("#r-pos").classList.toggle("hide", rnd || settings.viz_size >= 100);
  $("#r-effect").classList.toggle("hide", img === "__none__");
  $("#r-bg").classList.toggle("hide", img !== "__none__" && img !== "__auto__");
  $("#r-bg label").textContent = img === "__auto__" ? "Fond si pas d'image" : "Couleur de fond";
  $("#r-pulsebg").classList.toggle("hide", !settings.pulse);
  $("#titleSel").value = settings.title ? settings.title_src : "none";
}
const same = () => !globalSet || globalSet.same_for_all;
function curTrack(){ return !same() && selected && tracks[selected] ? selected : null; }
function changed(){
  clearTimeout(saveT);
  if (!same() && selected && settings !== globalSet && !tracks[selected]){   // 1re modification : le morceau garde ses réglages
    tracks[selected] = settings; renderFiles();
  }
  const obj = settings, track = curTrack();
  pendingSave = () => { pendingSave = null; return post("/api/settings",{settings: obj, track}); };
  saveT = setTimeout(pendingSave, 350);
  renderScope();
}
async function flushSave(){ clearTimeout(saveT); if (pendingSave) await pendingSave(); }
function useSettingsFor(){                 // le panneau montre les réglages du morceau choisi
  if (same() || !selected) settings = globalSet;
  else settings = tracks[selected] || JSON.parse(JSON.stringify(globalSet));   // brouillon tant qu'on ne change rien
  $("#same").checked = same();
  $("#filesHint").textContent = same()
    ? "Décoche la case ci-dessus pour régler chaque morceau séparément (visualiseur, jaquette, fond…). Clique sur la vignette d'un morceau pour changer sa jaquette."
    : "Clique sur un morceau : les réglages à droite ne concernent que lui. Clique sur sa vignette pour changer sa jaquette.";
  lastImgs = ""; fillImages(); applySettings(); renderScope(); renderMyCover();
}
function renderScope(){
  const per = !same() && selected, own = !!curTrack(), box = $("#scope"), b = $("#scopeBtn"), t = $("#scopeTxt");
  box.classList.toggle("own", !!per); t.innerHTML = "";
  if (per){ t.append("Réglages de "); t.appendChild(el("b",null,selected)); if (!own) t.append(" (encore identiques aux réglages communs)"); }
  else t.textContent = "Réglages communs à toute la playlist";
  b.textContent = "Reprendre les réglages communs"; b.hidden = !own;
}
const CVTXT = {added:"Ajoutée", image:"Image du même nom", mp3:"Celle du fichier", default:"Par défaut"};
function renderMyCover(){
  const f = S && S.files.find(x => x.name === selected), th = $("#myCv");
  th.innerHTML = ""; th.className = "thumb" + (f && f.cover_src ? " has" : "");
  if (f && f.cover_src){ const im = el("img"); im.alt = ""; im.src = `/api/thumb?name=${enc(f.name)}&v=${f.cover_v}`; th.appendChild(im); }
  else th.textContent = "+";
  $("#myCvTxt").textContent = !f ? "Choisis un morceau" : (CVTXT[f.cover_src] || "Aucune");
  th.disabled = $("#myCvBtn").disabled = !f;
}
function rotHint(){
  const n = settings.rotate_styles.length;
  if (n < 2) return "Clique sur au moins 2 visualiseurs ci-dessus.";
  const f = S && S.files.find(x => x.name === selected), step = settings.rotate_minutes * 60;
  const m = settings.rotate_minutes;
  let txt = `${n} visualiseurs, un nouveau ${m === 1 ? "chaque minute" : "toutes les " + m + " min"} (${settings.rotate_order === "order" ? "dans l'ordre" : "au hasard"}).`;
  if (f && f.duration){
    let p = Math.ceil(f.duration / step); if (p > 1 && f.duration - (p - 1) * step < Math.min(30, step / 2)) p--;
    txt += p > 1 ? ` Sur ce morceau (${fmt(f.duration)}) : ${p} passages.` : ` Ce morceau (${fmt(f.duration)}) est plus court : un seul visualiseur.`;
  }
  return txt;
}
function bindInputs(){
  $$("[data-k]").forEach(inp => {
    const ev = ["range","color","text"].includes(inp.type) ? "input" : "change";
    inp.addEventListener(ev, () => {
      const k = inp.dataset.k;
      if (inp.type === "radio" && !inp.checked) return;
      let v = inp.type === "checkbox" ? inp.checked : inp.value;
      if (["viz_size","fps","crf","audio_kbps","pulse","sensitivity","rotate_minutes"].includes(k)) v = parseInt(v,10);
      settings[k] = v;
      if (k === "rotate" && v && !settings.rotate_styles.length) settings.rotate_styles = [settings.style];
      applySettings(); changed();
    });
  });
  $("#titleSel").onchange = e => {
    const v = e.target.value; settings.title = v !== "none"; if (v !== "none") settings.title_src = v;
    changed();
  };
}
function fillImages(){
  const key = JSON.stringify(S.images);
  if (key === lastImgs) return; lastImgs = key;
  const fill = (sel, first, keep) => {
    sel.innerHTML = "";
    first.forEach(([v,t]) => { const o = el("option",null,t); o.value = v; sel.appendChild(o); });
    S.images.forEach(n => { const o = el("option",null,n); o.value = n; sel.appendChild(o); });
    if (keep) { if (![...first.map(x=>x[0]),...S.images].includes(settings[keep])) settings[keep] = first[0][0]; sel.value = settings[keep]; }
  };
  fill($("#imgSel"), [["__auto__","La jaquette du morceau"],["__none__","Couleur unie"]], "image");
  fill($("#defSel"), [["__none__","Aucune"]], "cover_default");
  fill($("#cvUse"), [["","…ou une image de input/"]], null);
}

/* ── fichiers ── */
const SRC = {added:"jaquette", image:"image", mp3:"pochette", default:"défaut"};
function renderFiles(){
  const box = $("#files"); box.innerHTML = "";
  const names = new Set(S.files.map(f => f.name));
  [...checked].forEach(n => { if (!names.has(n)) checked.delete(n); });
  if (selected && !names.has(selected)) selected = null;
  if (!S.files.length){
    box.appendChild(el("div","empty","Aucun morceau pour l'instant. Glisse-les ci-dessus, ou dépose-les dans le dossier input."));
  }
  for (const f of S.files){
    if (!seen.has(f.name)){ seen.add(f.name); if (!f.done) checked.add(f.name); }
    if (!selected) selected = f.name;
    const row = el("div","file" + (selected === f.name ? " sel" : ""));
    const cb = el("input"); cb.type = "checkbox"; cb.checked = checked.has(f.name);
    cb.onclick = e => e.stopPropagation();
    cb.onchange = () => { cb.checked ? checked.add(f.name) : checked.delete(f.name); updateAction(); };
    const th = el("button","thumb" + (f.cover_src ? " has" : "") + (f.cover_src === "default" ? " dflt" : ""));
    th.title = f.cover_src ? "Jaquette (" + SRC[f.cover_src] + ")" : "Ajouter une jaquette";
    if (f.cover_src){ const im = el("img"); im.alt = ""; im.src = `/api/thumb?name=${enc(f.name)}&v=${f.cover_v}`; th.appendChild(im); }
    else th.textContent = "+";
    th.onclick = e => { e.stopPropagation(); openCover(f.name); };
    const name = el("div","fname",f.name); name.title = f.name;
    if (f.tag) name.appendChild(el("small",null,f.tag));
    const meta = el("div","fmeta");
    if (!same() && tracks[f.name]) meta.appendChild(el("span","tag own","réglages perso"));
    if (f.cover_src && f.cover_src !== "default") meta.appendChild(el("span","tag",SRC[f.cover_src]));
    meta.appendChild(el("span",null,fmt(f.duration)));
    if (f.done){
      meta.appendChild(el("span","tag done","✓ vidéo"));
      const pl = el("button","btn small","▶"); pl.title = "Ouvrir la vidéo";
      pl.onclick = e => { e.stopPropagation(); post("/api/open",{what:"video",name:f.name}); };
      meta.appendChild(pl);
    }
    row.append(cb, th, name, meta);
    row.onclick = async () => {
      if (selected === f.name) return;
      await flushSave(); selected = f.name; renderFiles(); updatePvLabel(); useSettingsFor();
    };
    row.ondragover = e => { e.preventDefault(); e.stopPropagation(); row.classList.add("hot"); };
    row.ondragleave = () => row.classList.remove("hot");
    row.ondrop = async e => {
      e.preventDefault(); e.stopPropagation(); row.classList.remove("hot");
      dragN = 0; document.body.classList.remove("dragging");
      const file = [...e.dataTransfer.files].find(isImg);
      if (!file) { upload(e.dataTransfer.files); return; }
      const r = await sendFile(`/api/cover/upload?name=${enc(f.name)}&ext=${enc(extOf(file.name)||".jpg")}`, file);
      if (!r.ok) alert(r.error || "Erreur"); refresh(true);
    };
    box.appendChild(row);
  }
  $("#count").textContent = S.files.length + " fichier" + (S.files.length > 1 ? "s" : "");
  updateAction(); updatePvLabel(); renderMyCover();
  if (cvName) renderCover();
}
function updateAction(){
  const n = S ? S.files.filter(f => checked.has(f.name)).length : 0;
  const go = $("#go");
  go.textContent = S && S.running ? "Conversion en cours…" : (n ? `Convertir ${n} morceau${n>1?"x":""}` : "Convertir");
  go.disabled = !S || S.running || !n || !S.ffmpeg;
  const tot = S ? S.files.filter(f => checked.has(f.name)).reduce((a,f) => a + (f.duration||0), 0) : 0;
  $("#sum").textContent = n ? `${n} sélectionné${n>1?"s":""} · ${fmt(tot)} de musique` : "";
}

/* ── jaquette d'un morceau ── */
const INFO = {added:"Jaquette ajoutée (dossier input/jaquettes).", image:"Image du même nom dans le dossier input.",
  mp3:"Pochette intégrée au fichier audio.", default:"Pas de jaquette : la jaquette par défaut sera utilisée.", "":"Pas de jaquette pour ce morceau."};
function openCover(name){ cvName = name; $("#cvErr").textContent = ""; renderCover(); $("#coverDlg").classList.add("on"); }
function closeCover(){ cvName = null; $("#coverDlg").classList.remove("on"); }
function renderCover(){
  const f = S.files.find(x => x.name === cvName); if (!f){ closeCover(); return; }
  $("#cvTitle").textContent = f.name;
  const img = $("#cvImg");
  if (f.cover_src){ const u = `/api/thumb?name=${enc(f.name)}&s=440&v=${f.cover_v}`; if (img.dataset.u !== u){ img.src = u; img.dataset.u = u; } img.hidden = false; $("#cvNone").hidden = true; }
  else { img.hidden = true; img.dataset.u = ""; $("#cvNone").hidden = false; }
  $("#cvInfo").textContent = INFO[f.cover_src || ""];
  $("#cvEmbed").hidden = !f.cover_src || f.cover_src === "mp3" || !/\.mp3$/i.test(f.name);
  $("#cvRemove").hidden = f.cover_src !== "added";
  $("#cvUse").hidden = !S.images.length;
}
async function coverAction(body){
  $("#cvErr").textContent = "";
  const r = await post("/api/cover", Object.assign({name:cvName}, body));
  if (!r.ok) $("#cvErr").textContent = r.error || "Erreur";
  await refresh(true);
}

/* ── conversion ── */
const ST = {wait:"En attente", run:"En cours", ok:"Terminé", skip:"Déjà converti", err:"Erreur", cancel:"Annulé"};
function renderJobs(){
  const card = $("#jobsCard"), box = $("#jobs");
  if (!S.jobs.length){ card.style.display = "none"; return; }
  card.style.display = ""; box.innerHTML = "";
  $("#cancel").style.display = S.running ? "" : "none";
  for (const j of S.jobs){
    const d = el("div","job " + j.status);
    const top = el("div","job-top");
    top.appendChild(el("div","fname",j.name));
    let label = ST[j.status] || j.status;
    if (j.status === "run") label += ` · ${Math.floor(j.progress)} %` + (j.speed && j.speed !== "N/A" ? ` · ${j.speed}` : "");
    top.appendChild(el("span","job-st " + (j.status === "ok" ? "ok" : j.status === "err" ? "err" : ""), label));
    const bar = el("div","bar"); const i = el("i"); i.style.width = (j.status === "ok" || j.status === "skip" ? 100 : j.progress) + "%"; bar.appendChild(i);
    d.append(top, bar);
    if (j.error && j.status === "err") d.appendChild(el("div","job-err",j.error));
    box.appendChild(d);
  }
}

/* ── aperçu ── */
function pvTarget(){ return selected || [...checked][0] || (S && S.files[0] && S.files[0].name); }
function updatePvLabel(){
  if ($("#screen").classList.contains("loading") || !$("#pvvid").hidden) return;
  const t = pvTarget();
  $("#pvlbl").textContent = t ? "Morceau : " + t : "Aucun morceau";
}
async function preview(){
  const t = pvTarget(); if (!t) return;
  await flushSave();
  const scr = $("#screen"), v = $("#pvvid"); scr.classList.add("loading"); $("#preview").disabled = true;
  v.pause();
  $("#pvlbl").textContent = "Rendu de " + t + "…"; $("#pvlbl").classList.remove("err");
  const r = await post("/api/preview",{file:t, settings});
  scr.classList.remove("loading"); $("#preview").disabled = false;
  if (r.ok){
    v.src = "/preview.mp4?t=" + Date.now(); v.hidden = false; $("#ph").hidden = true;
    v.play().catch(() => {});
    $("#pvlbl").textContent = `${t} · de ${fmt(r.at)} à ${fmt(r.at + r.dur)}` + (settings.rotate && r.style && STYLES[r.style] ? ` · ${STYLES[r.style][0]}` : "");
  } else { $("#pvlbl").textContent = "Erreur : " + r.error; $("#pvlbl").classList.add("err"); }
}

/* ── envoi de fichiers ── */
async function upload(files){
  const list = [...files]; if (!list.length) return [];
  const drop = $("#drop"); const old = drop.innerHTML;
  let n = 0; const bad = [], done = [];
  for (const f of list){
    drop.textContent = `Copie de ${f.name}… (${++n}/${list.length})`;
    const j = await sendFile("/api/upload?name=" + enc(f.name), f);
    if (j.ok) done.push(j.name); else bad.push(f.name);
  }
  drop.innerHTML = old; bindPicker();
  if (bad.length) alert("Fichiers ignorés (seuls les fichiers audio et les images sont acceptés) :\n" + bad.join("\n"));
  await refresh(true);
  return done;
}
function bindPicker(){ $("#picker").onchange = e => upload(e.target.files); }

/* ── état ── */
let timer = null;
async function refresh(once){
  clearTimeout(timer);
  let next = 2500;
  try{
    const r = await fetch("/api/state",{cache:"no-store"}); S = await r.json();
    $("#offline").classList.remove("on");
    const first = !settings;
    if (first){ globalSet = S.settings; tracks = S.tracks || {}; settings = globalSet; }
    fillImages(); applySettings();
    renderFiles(); renderJobs(); renderStatus();
    if (first) useSettingsFor();
    if (S.running) next = 700;
  }catch(e){ $("#offline").classList.add("on"); next = 3000; }
  timer = setTimeout(refresh, next);
}
function renderStatus(){
  const pill = $("#ffpill");
  pill.classList.toggle("bad", !S.ffmpeg);
  $("#fftext").textContent = S.ffmpeg ? "FFmpeg prêt" : "FFmpeg introuvable";
  const w = $("#warnCard");
  if (!S.ffmpeg){
    w.style.display = "";
    $("#warnBox").innerHTML = "<b>FFmpeg est introuvable.</b> Dépose le fichier <code>ffmpeg</code> dans le dossier du script :<br><code></code><br>La page le détectera automatiquement.";
    $("#warnBox code:last-of-type").textContent = S.input.replace(/[\\/]input$/,"");
  } else if (!S.x264){
    w.style.display = "";
    $("#warnBox").textContent = "Ce ffmpeg ne contient pas l'encodeur H.264 (libx264). Télécharge une autre version de ffmpeg.";
  } else w.style.display = "none";
  $("#hwOpt").textContent = S.hw ? "Rapide (puce graphique, fichiers plus gros)"
                                 : "Rapide (puce graphique indisponible ici : processeur)";
  $("#titleSel").disabled = !S.title_ok;
  $("#titleWarn").hidden = !!S.title_ok;
}

/* ── démarrage ── */
buildStyles(); bindInputs(); bindPicker();
$("#all").onclick = () => { S.files.forEach(f => checked.add(f.name)); renderFiles(); };
$("#none").onclick = () => { checked.clear(); renderFiles(); };
$("#openIn").onclick = () => post("/api/open",{what:"input"});
$("#openOut").onclick = () => post("/api/open",{what:"output"});
$("#preview").onclick = preview;
$("#reset").onclick = () => {
  if (!confirm("Remettre les réglages par défaut ?")) return;
  const d = JSON.parse(JSON.stringify(DEFAULTS));
  if (curTrack()) tracks[selected] = d; else { d.same_for_all = same(); globalSet = d; }
  settings = d; applySettings(); changed();
};
$("#scopeBtn").onclick = async () => {
  if (!selected) return;
  await flushSave();
  if (!curTrack()) return;
  if (!confirm(`« ${selected} » reprendra les réglages communs. Ses réglages à lui seront effacés.`)) return;
  const r = await post("/api/track",{name: selected, action: "drop"});
  if (r.ok) delete tracks[selected];
  useSettingsFor(); renderFiles();
};
$("#same").onchange = async e => {
  await flushSave();
  globalSet.same_for_all = e.target.checked;
  await post("/api/settings",{settings: globalSet});
  useSettingsFor(); renderFiles();
};
$("#myCv").onclick = $("#myCvBtn").onclick = () => { if (selected) openCover(selected); };
$("#cancel").onclick = () => post("/api/cancel").then(() => refresh(true));
$("#go").onclick = async () => {
  const files = S.files.filter(f => checked.has(f.name)).map(f => f.name);
  await flushSave();
  const r = await post("/api/convert",{files, settings: globalSet, force: $("#force").checked});
  if (!r.ok) alert(r.error || "Erreur"); refresh(true);
};
$("#quit").onclick = async () => {
  if (S && S.running && !confirm("Une conversion est en cours. Quitter quand même ?")) return;
  await post("/api/quit"); clearTimeout(timer);
  $("#offMsg").textContent = "Tu peux fermer cet onglet. Pour revenir, relance Onde2Vid.";
  $("#offline").classList.add("on");
};
$("#defPick").onchange = async e => {
  const f = e.target.files[0]; e.target.value = ""; if (!f) return;
  const done = await upload([f]);
  if (done.length){ settings.cover_default = done[0]; lastImgs = ""; fillImages(); applySettings(); changed(); }
};
$("#cvPick").onchange = async e => {
  const f = e.target.files[0]; e.target.value = ""; if (!f || !cvName) return;
  $("#cvErr").textContent = "";
  const r = await sendFile(`/api/cover/upload?name=${enc(cvName)}&ext=${enc(extOf(f.name)||".jpg")}`, f);
  if (!r.ok) $("#cvErr").textContent = r.error || "Erreur";
  refresh(true);
};
$("#cvUse").onchange = e => { const v = e.target.value; e.target.value = ""; if (v) coverAction({action:"use", image:v}); };
$("#cvEmbed").onclick = () => { if (confirm("Écrire cette jaquette dans le fichier MP3 ?\n(le son n'est pas modifié)")) coverAction({action:"embed"}); };
$("#cvRemove").onclick = () => coverAction({action:"remove"});
$("#cvClose").onclick = closeCover;
$("#coverDlg").onclick = e => { if (e.target.id === "coverDlg") closeCover(); };
let dragN = 0;
addEventListener("dragenter", e => { e.preventDefault(); dragN++; document.body.classList.add("dragging"); });
addEventListener("dragleave", e => { if (--dragN <= 0){ dragN = 0; document.body.classList.remove("dragging"); } });
addEventListener("dragover", e => e.preventDefault());
addEventListener("drop", e => { e.preventDefault(); dragN = 0; document.body.classList.remove("dragging"); upload(e.dataTransfer.files); });
addEventListener("pagehide", () => { try { navigator.sendBeacon("/api/bye?t=" + TOKEN); } catch(e){} });
document.addEventListener("visibilitychange", () => { if (!document.hidden && S) refresh(true); });
const DEFAULTS = __DEFAULTS__;
refresh();
</script>
</body>
</html>
""".replace("__DEFAULTS__", json.dumps(DEFAULTS)).replace("__LOGO__", LOGO_SVG).replace(
    "__FAVICON__", quote(LOGO_SVG)).replace("__AUDIO_ACCEPT__", ",".join(sorted(AUDIO_EXT)))


# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description=f"{APP_NAME} : musique (MP3, WAV, FLAC…) → vidéo MP4 animée (interface ou mode batch).")
    p.add_argument("--batch", action="store_true", help="Convertir input/ sans interface")
    p.add_argument("--force", action="store_true", help="(batch) Refaire les vidéos existantes")
    p.add_argument("--no-browser", action="store_true", help="Ne pas ouvrir le navigateur")
    p.add_argument("--app", action="store_true",
                   help="Mode application (sans terminal) : journal dans onde2vid.log, "
                        "arrêt automatique quand l'onglet est fermé")
    p.add_argument("--server", action="store_true", help=argparse.SUPPRESS)
    args, _ = p.parse_known_args()       # macOS peut ajouter ses propres arguments
    if args.batch:
        run_batch(args.force)
        return
    if FROZEN and sys.platform == "darwin" and not args.server:
        # L'app Mac lance le serveur à part puis se ferme : un nouveau double-clic
        # relance alors l'app, qui retrouve simplement l'onglet déjà ouvert.
        ensure_tools()
        url = find_running()
        if url:
            if not args.no_browser:
                webbrowser.open(url)
        else:
            subprocess.Popen([sys.executable, "--server"] + (["--no-browser"] if args.no_browser else []),
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        shutil.rmtree(TMP, ignore_errors=True)
        return
    app_mode = args.app or args.server or FROZEN or sys.stdout is None   # pas de console
    if app_mode:
        start_log()
    run_gui(open_browser=not args.no_browser, app_mode=app_mode)


if __name__ == "__main__":
    main()
