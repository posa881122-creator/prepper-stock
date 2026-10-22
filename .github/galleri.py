#!/usr/bin/env python3
"""Bygger galleriet.

Laser filerna i galleri-original/, aven i undermappar, gor om dem till
webbvanliga kopior i galleri-klar/ och skriver listan galleri-klar/lista.json
som sidorna laser.

En mapp som heter sv eller svenska gor att bilderna i den bara visas nar
sidan star pa svenska. En mapp som heter en eller engelska gor tvartom.
Allt annat visas pa bada spraken.

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
HOPPA = {".txt", ".md", ".json", ".ds_store"}

SPRAKMAPP = {
    "sv": "sv", "svenska": "sv", "swedish": "sv", "se": "sv",
    "en": "en", "engelska": "en", "english": "en",
}

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


def utan_nummer(s):
    return re.sub(r"^\s*\d+\s*[._-]*\s*", "", s).strip()


def putsa(x):
    x = x.strip()
    # filnamn utan mellanslag ar oftast skrivna med bindestreck i stallet
    x = x.replace("_", " ") if " " in x else x.replace("_", " ").replace("-", " ")
    x = re.sub(r"\s+", " ", x).strip()
    if x and x == x.lower():
        x = x[0].upper() + x[1:]
    return x


def texter(stem):
    """Filnamnet blir bildtexten. '01 Mitt lager__My stock' ger bada spraken."""
    s = utan_nummer(stem)
    sv, en = (s.split("__", 1) if "__" in s else (s, s))
    return putsa(sv), putsa(en)


def sprak_av(delar):
    for d in delar:
        tr = SPRAKMAPP.get(utan_nummer(d).lower())
        if tr:
            return tr
    return ""


def nyckel(rel):
    ut = []
    for d in rel.replace("\\", "/").split("/"):
        m = re.match(r"\s*(\d+)", d)
        ut.append((int(m.group(1)) if m else 10 ** 6, d.lower()))
    return ut


def matt(fil):
    b, h = kor(IDENTIFY + ["-format", "%w %h", fil + "[0]"]).split()[:2]
    return int(b), int(h)


def gor_bild(kalla, mal, bredd):
    kor([MAGICK, kalla + "[0]", "-auto-orient", "-strip",
         "-resize", "%dx%d>" % (bredd, bredd * 3),
         "-quality", "82", mal])


def film_matt(fil):
    b, h = kor(["ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0:s=x", fil]).split("x")[:2]
    return int(b), int(h)


def gor_film(kalla, mal):
    kor(["ffmpeg", "-y", "-v", "error", "-i", kalla,
         "-map_metadata", "-1", "-map_chapters", "-1",
         "-vf", "scale='min(1280,iw)':-2",
         "-c:v", "libx264", "-crf", "25", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", mal])


def gor_omslag(kalla, mal):
    tmp = mal + ".png"
    for sek in ("1", "0"):
        try:
            kor(["ffmpeg", "-y", "-v", "error", "-ss", sek, "-i", kalla,
                 "-frames:v", "1", "-map_metadata", "-1", tmp])
            break
        except RuntimeError:
            continue
    gor_bild(tmp, mal, BRED_MINI)
    os.remove(tmp)


def samla():
    träff = []
    for rot, mappar, filer in os.walk(SRC):
        mappar[:] = sorted(m for m in mappar if not m.startswith("."))
        for f in filer:
            if f.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(rot, f), SRC).replace("\\", "/")
            träff.append(rel)
    return sorted(träff, key=nyckel)


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(SRC, exist_ok=True)

    poster = []
    behall = {os.path.basename(LISTA)}

    for rel in samla():
        kalla = os.path.join(SRC, rel)
        delar = rel.split("/")
        stem, andelse = os.path.splitext(delar[-1])
        andelse = andelse.lower()

        if andelse not in BILD and andelse not in FILM:
            if andelse not in HOPPA:
                varningar.append("Hoppade over %s, filtypen stods inte." % rel)
            continue

        namnrot = slug(os.path.splitext(rel)[0])[:70]
        sv, en = texter(stem)
        sprak = sprak_av(delar[:-1])

        try:
            if andelse in BILD:
                full, mini = namnrot + ".webp", namnrot + "-mini.webp"
                if not os.path.exists(os.path.join(OUT, full)):
                    gor_bild(kalla, os.path.join(OUT, full), BRED_FULL)
                if not os.path.exists(os.path.join(OUT, mini)):
                    gor_bild(kalla, os.path.join(OUT, mini), BRED_MINI)
                b, h = matt(os.path.join(OUT, full))
                typ = "bild"
            else:
                mb = os.path.getsize(kalla) / 1e6
                if mb > 90:
                    varningar.append("%s ar %.0f MB, for stor for GitHub. Korta ner filmen." % (rel, mb))
                    continue
                full, mini = namnrot + ".mp4", namnrot + "-mini.webp"
                if not os.path.exists(os.path.join(OUT, full)):
                    gor_film(kalla, os.path.join(OUT, full))
                if not os.path.exists(os.path.join(OUT, mini)):
                    gor_omslag(os.path.join(OUT, full), os.path.join(OUT, mini))
                b, h = film_matt(os.path.join(OUT, full))
                typ = "film"

            poster.append({"typ": typ, "full": full, "mini": mini, "b": b, "h": h,
                           "sprak": sprak, "sv": sv, "en": en})
            behall |= {full, mini}
        except Exception as e:
            varningar.append("Kunde inte anvanda %s: %s" % (rel, e))

    for f in os.listdir(OUT):
        if f not in behall:
            os.remove(os.path.join(OUT, f))

    with open(LISTA, "w", encoding="utf-8") as fh:
        json.dump(poster, fh, ensure_ascii=False, indent=1)

    bilder = sum(1 for p in poster if p["typ"] == "bild")
    bara_sv = sum(1 for p in poster if p["sprak"] == "sv")
    bara_en = sum(1 for p in poster if p["sprak"] == "en")
    print("::notice title=Galleri::%d bilder och %d filmer. %d visas bara pa svenska, %d bara pa engelska."
          % (bilder, len(poster) - bilder, bara_sv, bara_en))
    for v in varningar:
        print("::warning title=Galleri::%s" % v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
