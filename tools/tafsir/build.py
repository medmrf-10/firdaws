#!/usr/bin/env python3
"""Build docs/tafsir/data/** from the QUL tafsir45.zip archive.

Usage: build.py <path-to-tafsir45.zip> [--surahs <chapters.json>]

Writes:
  docs/tafsir/data/surahs.json
  docs/tafsir/data/books.json
  docs/tafsir/data/<qulId>/<surah>.json.gz   (one per book per surah)

Per-surah files contain the slice of the original dict for that surah's
keys with the ORIGINAL values byte-preserved (no normalization). If a
pointer or an ayah_keys entry references a key in a different surah, that
target entry is included in the file under the same key.
"""

import gzip
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "docs" / "tafsir" / "data"

EXCLUDED = {28, 29, 33, 34, 42}

# id -> display name, exactly as specified. UI order: 22 first, then the
# rest sorted alphabetically by normalized display name.
BOOK_NAMES = {
    22: "تفسير ابن كثير",
    23: "تفسير القرطبي",
    25: "التحرير والتنوير",
    26: "التفسير الوسيط لطنطاوي",
    37: "تفسير الطبري",
    250: "السراج في بيان غريب القرآن",
    251: "المختصر في تفسير القرآن الكريم",
    488: "تفسير الرازي",
    489: "الوجيز للواحدي",
    490: "الهداية إلى بلوغ النهاية لمكي",
    491: "التسهيل لابن جزي",
    492: "موسوعة التفسير المأثور",
    493: "الدر المنثور",
    494: "فتح القدير للشوكاني",
    495: "فتح البيان للقنوجي",
    496: "زاد المسير لابن الجوزي",
    497: "تفسير أبي السعود",
    498: "نظم الدرر للبقاعي",
    499: "تفسير ابن أبي زمنين",
    500: "تفسير ابن القيم",
    501: "روح المعاني للآلوسي",
    502: "تفسير ابن أبي حاتم",
    505: "الدر المصون للسمين الحلبي",
    506: "إعراب القرآن وبيانه لدرويش",
    508: "جامع البيان للإيجي",
    509: "المحرر الوجيز لابن عطية",
    510: "الكشاف للزمخشري",
    511: "التفسير البسيط للواحدي",
    512: "النكت والعيون للماوردي",
    513: "بحر العلوم للسمرقندي",
    514: "تفسير النسفي",
    516: "اللباب في علوم الكتاب لابن عادل",
    517: "تدبر وعمل",
    518: "تفسير البيضاوي",
    523: "تفسير الجلالين",
    524: "محاسن التأويل للقاسمي",
    525: "أضواء البيان للشنقيطي",
    526: "البحر المحيط لأبي حيان",
    527: "تفسير الثعالبي",
    529: "تفسير السمعاني",
}

DIACRITICS = re.compile(r"[ً-ٰٟـ]")


def sort_key(name):
    n = DIACRITICS.sub("", name)
    n = re.sub(r"[أإآٱ]", "ا", n)
    n = n.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    return n


def load_surahs(path):
    if path:
        chapters = json.loads(Path(path).read_text("utf-8"))["chapters"]
    else:
        import urllib.request
        req = urllib.request.Request(
            "https://api.quran.com/api/v4/chapters?language=ar",
            headers={"User-Agent": "firdaws-build"})
        chapters = json.loads(urllib.request.urlopen(req, timeout=30).read())["chapters"]
    surahs = [{"n": c["id"], "name": c["name_arabic"], "ayahs": c["verses_count"]}
              for c in chapters]
    assert len(surahs) == 114
    assert sum(s["ayahs"] for s in surahs) == 6236
    return surahs


def key_surah(key):
    return int(key.split(":", 1)[0])


def main():
    zip_path = sys.argv[1]
    surahs_file = None
    if "--surahs" in sys.argv:
        surahs_file = sys.argv[sys.argv.index("--surahs") + 1]

    surahs = load_surahs(surahs_file)
    ayah_counts = {s["n"]: s["ayahs"] for s in surahs}

    zf = zipfile.ZipFile(zip_path)
    book_entries = {}  # qulId -> member name of inner .json.zip
    for name in zf.namelist():
        m = re.match(r"^(\d+)-download-.*-tafsir-json-data/([^/]+\.json\.zip)$", name)
        if m:
            qid = int(m.group(1))
            if qid not in EXCLUDED:
                book_entries[qid] = name
    assert set(book_entries) == set(BOOK_NAMES), (
        f"zip ids != expected ids: {sorted(set(book_entries) ^ set(BOOK_NAMES))}")

    cross_refs = []  # (qulId, from_key, target_key, kind)
    books_meta = []
    DATA.mkdir(parents=True, exist_ok=True)

    for qid in [22] + sorted((i for i in BOOK_NAMES if i != 22),
                             key=lambda i: sort_key(BOOK_NAMES[i])):
        member = book_entries[qid]
        with zipfile.ZipFile(zf.open(member)) as inner:
            inner_names = inner.namelist()
            assert len(inner_names) == 1
            book = json.loads(inner.open(inner_names[0]).read())

        assert len(book) == 6236, f"{qid}: {len(book)} keys"
        per_surah = {}
        for k, v in book.items():
            s, a = k.split(":")
            s, a = int(s), int(a)
            assert 1 <= s <= 114 and 1 <= a <= ayah_counts[s], f"{qid}: bad key {k}"
            per_surah.setdefault(s, {})[k] = v
        assert len(per_surah) == 114
        for s in range(1, 115):
            assert len(per_surah[s]) == ayah_counts[s]

        # include cross-surah targets of pointers / ayah_keys
        for s in range(1, 115):
            extra = {}
            queue = []
            for k, v in per_surah[s].items():
                if isinstance(v, str):
                    if key_surah(v) != s:
                        queue.append((k, v, "pointer"))
                elif isinstance(v, dict):
                    for ak in v.get("ayah_keys", []):
                        if key_surah(ak) != s:
                            queue.append((k, ak, "ayah_keys"))
            while queue:
                src, target, kind = queue.pop()
                cross_refs.append((qid, src, target, kind))
                if target in extra or target in per_surah[s]:
                    continue
                tv = book.get(target)
                if tv is None:
                    print(f"WARNING {qid}: target {target} of {kind} from {src} "
                          f"not present in source dict", file=sys.stderr)
                    continue
                extra[target] = tv
                if isinstance(tv, str) and key_surah(tv) != s:
                    queue.append((target, tv, "pointer-chain"))
                elif isinstance(tv, dict):
                    for ak in tv.get("ayah_keys", []):
                        if key_surah(ak) != s:
                            queue.append((target, ak, "ayah_keys-chain"))
            per_surah[s].update(extra)

        outdir = DATA / str(qid)
        outdir.mkdir(exist_ok=True)
        for s in range(1, 115):
            payload = json.dumps(per_surah[s], ensure_ascii=False,
                                 separators=(",", ":")).encode("utf-8")
            (outdir / f"{s}.json.gz").write_bytes(
                gzip.compress(payload, compresslevel=9, mtime=0))

        covered = sum(1 for v in book.values()
                      if isinstance(v, str) or (isinstance(v, dict) and v))
        books_meta.append({"id": qid, "name": BOOK_NAMES[qid],
                           "covered": covered})
        print(f"{qid}: covered={covered}", file=sys.stderr)

    (DATA / "surahs.json").write_text(
        json.dumps(surahs, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")

    zb = Path(zip_path).read_bytes()
    books_doc = {
        "source": {
            "file": Path(zip_path).name,
            "bytes": len(zb),
            "sha256": hashlib.sha256(zb).hexdigest(),
        },
        "books": books_meta,
    }
    (DATA / "books.json").write_text(
        json.dumps(books_doc, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")

    print("\nCROSS-SURAH REFERENCES (included as extra keys):")
    if not cross_refs:
        print("  none")
    for qid, src, tgt, kind in cross_refs:
        print(f"  {qid}: {src} -> {tgt} ({kind})")


if __name__ == "__main__":
    main()
