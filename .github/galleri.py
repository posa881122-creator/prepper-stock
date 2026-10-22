#!/usr/bin/env python3
"""Bygger galleriet.

Laser filerna i galleri-original/, gor om dem till webbvanliga kopior i
galleri-klar/ och skriver listan galleri-klar/lista.json som sidan laser.

All platsinformation och annan dold information i bilderna tas bort.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata

SRC = "galleri-original"
OUT = "galleri-klar"
LISTA = os.path.join(OUT, "lista.json")

BILD = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif", ".tif", ".tiff"}
FILM = {".mp4", ".mov", ".m4v", ".webm", ".avi"}

MAGICK = "magick" if shutil.which("magick") else "convert"
IDENTIFY = [MAGICK, "identify"] if MAGICK == "magick" else ["identify"]

BRED_FULL = 1600
BRED_MINI = 760

varningar = []


def kor(args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip()[:400])
    return r.stdout.strip()


def slug(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("ø", "o").replace("Ø", "O").replace("æ", "ae").replace("ß", "ss")
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "fil"


def texter(stem):
    """Filnamnet blir bildtexten. '01 Mitt lager__My stock' ger bada spraken."""
    s = re.sub(r"^\s*\d+\s*[._-]*\s*", "", stem)
    sv, en = (s.split("__", 1) + [""])[:2] if "__" in s else (s, s)
    putsa = lambda x: re.sub(r"\s+", " ", x.replace("_", " ")).strip()
    return putsa(sv), putsa(en)


def ordning(namn):
    m = re.match(r"\s*(\d+)", namn)
    return (int(m.group(1)) if m else 10 ** 6, namn.lower())


def matt(fil):
    ut = kor(IDENTIFY + ["-format", "%w %h", fil + "[0]"])
    b, h = ut.split()[:2]
    return int(b), int(h)


def gor_bild(kalla, mal, bredd):
    """Skalar ner, tar bort all metadata och sparar som webp."""
    kor([MAGICK, kalla + "[0]", "-auto-orient", "-strip",
         "-resize", "%dx%d>" % (bredd, bredd * 3),
         "-quality", "82", mal])


def film_matt(fil):
    ut = kor(["ffprobe", "-v", "error", "-select_streams", "v:0",
              "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", fil])
    b, h = ut.split("x")[:2]
    return int(b), int(h)


def gor_film(kalla, mal):
    kor(["ffmpeg", "-y", "-v", "error", "-i", kalla,
         "-map_metadata", "-1", "-map_chapters", "-1",
         "-vf", "scale='min(1280,iw)':-2",
         "-c:v", "libx264", "-crf", "25", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", mal])


def gor_omslag(kalla, mal):
    tmp = mal + ".png"
    try:
        kor(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", kalla,
             "-frames:v", "1", "-map_metadata", "-1", tmp])
    except RuntimeError:
        kor(["ffmpeg", "-y", "-v", "error", "-i", kalla,
             "-frames:v", "1", "-map_metadata", "-1", tmp])
    gor_bild(tmp, mal, BRED_MINI)
    os.remove(tmp)


def main():
    os.makedirs(OUT, exist_ok=True)
    if not os.path.isdir(SRC):
        os.makedirs(SRC, exist_ok=True)

    filer = sorted((f for f in os.listdir(SRC) if not f.startswith(".")), key=ordning)
    poster = []
    behall = {os.path.basename(LISTA)}

    for namn in filer:
        kalla = os.path.join(SRC, namn)
        if not os.path.isfile(kalla):
            continue
        stem, andelse = os.path.splitext(namn)
        andelse = andelse.lower()
        if andelse not in BILD and andelse not in FILM:
            if andelse not in (".txt", ".md"):
                varningar.append("Hoppade over %s, filtypen stods inte." % namn)
            continue

        namnrot = slug(stem)[:60]
        sv, en = texter(stem)
        try:
            if andelse in BILD:
                full = namnrot + ".webp"
                mini = namnrot + "-mini.webp"
                if not os.path.exists(os.path.join(OUT, full)):
                    gor_bild(kalla, os.path.join(OUT, full), BRED_FULL)
                if not os.path.exists(os.path.join(OUT, mini)):
                    gor_bild(kalla, os.path.join(OUT, mini), BRED_MINI)
                b, h = matt(os.path.join(OUT, full))
                poster.append({"typ": "bild", "full": full, "mini": mini,
                               "b": b, "h": h, "sv": sv, "en": en})
                behall |= {full, mini}
            else:
                mb = os.path.getsize(kalla) / 1e6
                if mb > 90:
                    varningar.append("%s ar %.0f MB, for stor for GitHub. Korta ner filmen." % (namn, mb))
                    continue
                fil = namnrot + ".mp4"
                mini = namnrot + "-mini.webp"
                if not os.path.exists(os.path.join(OUT, fil)):
                    gor_film(kalla, os.path.join(OUT, fil))
                if not os.path.exists(os.path.join(OUT, mini)):
                    gor_omslag(os.path.join(OUT, fil), os.path.join(OUT, mini))
                b, h = film_matt(os.path.join(OUT, fil))
                poster.append({"typ": "film", "full": fil, "mini": mini,
                               "b": b, "h": h, "sv": sv, "en": en})
                behall |= {fil, mini}
        except Exception as e:
            varningar.append("Kunde inte anvanda %s: %s" % (namn, e))

    for f in os.listdir(OUT):
        if f not in behall:
            os.remove(os.path.join(OUT, f))

    with open(LISTA, "w", encoding="utf-8") as fh:
        json.dump(poster, fh, ensure_ascii=False, indent=1)

    bilder = sum(1 for p in poster if p["typ"] == "bild")
    filmer = len(poster) - bilder
    print("::notice title=Galleri::%d bilder och %d filmer ligger nu i galleriet." % (bilder, filmer))
    for v in varningar:
        print("::warning title=Galleri::%s" % v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
