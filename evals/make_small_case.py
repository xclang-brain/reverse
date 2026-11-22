"""小さい評価用の入力を作る。

ATK2-SC1 の kernel と include、外部仕様書の一部のページ（タスク、カウンタ、アラーム）を
evals/materials/small/ に写す。先に fetch_materials.py を動かしておく。
使い方: python evals/make_small_case.py
"""
import shutil
import sys
from pathlib import Path

import pypdfium2 as pdfium

MATERIALS = Path(__file__).resolve().parent / "materials"
SMALL = MATERIALS / "small"
SOURCE_DIRS = ["kernel", "include"]
PDF_NAME = "ATK2-0010_ATK2_spec_122.pdf"
# 1始まりのページ番号（両端を含む）: 2.5 タスク、2.10 カウンタ〜2.12 アラーム
PAGE_RANGES = [(44, 57), (78, 88)]


def main():
    src = SMALL / "src"
    for name in SOURCE_DIRS:
        if not (src / name).exists():
            shutil.copytree(MATERIALS / "atk2-sc1" / name, src / name)
    pdf_dir = SMALL / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    target = pdf_dir / "ATK2_spec_extract.pdf"
    if not target.exists():
        original = pdfium.PdfDocument(str(MATERIALS / "pdf" / PDF_NAME))
        pages = [p - 1 for start, end in PAGE_RANGES for p in range(start, end + 1)]
        extract = pdfium.PdfDocument.new()
        extract.import_pages(original, pages)
        extract.save(str(target))
    print("ok", SMALL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
