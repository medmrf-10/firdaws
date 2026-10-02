#!/usr/bin/env python3
"""Verify docs/tafsir/data/** preserves the source values exactly.

Usage: verify.py <path-to-tafsir45.zip>

For every included tafsir and every one of its 6236 keys, decompresses
the emitted per-surah file and asserts the stored value is deep-equal to
the source value in the zip. Any extra keys (cross-surah targets) are
also checked against the source. Prints totals and per-book value-type
counts. Also asserts the 5 excluded ids are absent from docs/.
"""

import gzip
import json
import re
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "docs" / "tafsir" / "data"

EXCLUDED = {28, 29, 33, 34, 42}


def main():
    zip_path = sys.argv[1]

    # excluded ids must not exist under docs/
    for qid in EXCLUDED:
        assert not (DATA / str(qid)).exists(), f"excluded id {qid} present in docs/"
    print(f"excluded ids absent from docs/: {sorted(EXCLUDED)} OK")

    zf = zipfile.ZipFile(zip_path)
    book_entries = {}
    for name in zf.namelist():
        m = re.match(r"^(\d+)-download-.*-tafsir-json-data/([^/]+\.json\.zip)$", name)
        if m:
            qid = int(m.group(1))
            if qid not in EXCLUDED:
                book_entries[qid] = name

    total_checked = 0
    total_mismatched = 0
    books_sorted = sorted(book_entries)
    print(f"books in zip (after exclusions): {len(books_sorted)}")
    print(f"{'id':>5} {'text':>6} {'ptr':>6} {'empty':>6} {'keys':>6} {'extra':>6} {'mismatch':>8}")

    for qid in books_sorted:
        member = book_entries[qid]
        with zipfile.ZipFile(zf.open(member)) as inner:
            book = json.loads(inner.open(inner.namelist()[0]).read())
        assert len(book) == 6236

        per_surah = {}
        for k in book:
            s = int(k.split(":", 1)[0])
            per_surah.setdefault(s, []).append(k)

        n_text = n_ptr = n_empty = 0
        n_extra = n_mismatch = 0
        for s in range(1, 115):
            fpath = DATA / str(qid) / f"{s}.json.gz"
            assert fpath.exists(), f"missing {fpath}"
            emitted = json.loads(gzip.decompress(fpath.read_bytes()))
            expected_keys = set(per_surah.get(s, []))
            for k in expected_keys:
                if emitted.get(k) != book[k] or (k not in emitted):
                    n_mismatch += 1
                    print(f"MISMATCH {qid} {k}", file=sys.stderr)
            for k in set(emitted) - expected_keys:
                # extra keys = cross-surah targets; still must match source
                if emitted[k] != book.get(k):
                    n_mismatch += 1
                    print(f"MISMATCH extra {qid} {k}", file=sys.stderr)
                n_extra += 1
            for k in expected_keys:
                v = book[k]
                if isinstance(v, str):
                    n_ptr += 1
                elif isinstance(v, dict) and v:
                    n_text += 1
                else:
                    n_empty += 1
        total_checked += len(book)
        total_mismatched += n_mismatch
        print(f"{qid:>5} {n_text:>6} {n_ptr:>6} {n_empty:>6} {len(book):>6} "
              f"{n_extra:>6} {n_mismatch:>8}")

    print(f"\nTOTAL keys checked: {total_checked}")
    print(f"TOTAL mismatches:   {total_mismatched}")
    assert total_mismatched == 0, "VERIFICATION FAILED"
    print("VERIFICATION PASSED")


if __name__ == "__main__":
    main()
