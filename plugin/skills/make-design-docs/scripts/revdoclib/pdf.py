"""PDF を読む（スクリプトの仕様の 2.5、2.6）。pypdfium2 は、--pdf があるときだけ読み込む。"""
import math
import os
import re
import unicodedata

from . import files, values

SIDES = ("top", "bottom", "left", "right")
_CHECK_RUN = re.compile("[%s]+" % values.CHECK_CHARS)
_NOT_CHECK = re.compile("[^%s]+" % values.CHECK_CHARS)
_NUMBERED = re.compile(r"^\s*([0-9]+)(\s|$)")
_LINE_NUMBER = re.compile(r"^\s*[0-9]+ ?")


def check_strings(text):
    """検査する文字列（6.2）。検査する文字が続く所の1つずつ。"""
    return _CHECK_RUN.findall(unicodedata.normalize("NFKC", text))


def joined_chars(text):
    """つないだ文字（6.2）。検査する文字だけを順につないだもの。"""
    return _NOT_CHECK.sub("", unicodedata.normalize("NFKC", text))


def _scale(v):
    # Python の round は偶数への丸めなので、四捨五入を自分で行う。
    return int(math.floor(v * values.POSITION_SCALE + 0.5))


def text_units(textpage, width, height):
    """2.6 のテキストの単位を [(文字列, [x0, y0, x1, y1])] で返す。位置は左上を原点にした 0〜10000。"""
    units = []
    for i in range(textpage.count_rects()):
        left, bottom, right, top = textpage.get_rect(i)
        box = [_scale(left / width), _scale((height - top) / height),
               _scale(right / width), _scale((height - bottom) / height)]
        units.append((textpage.get_text_bounded(left, bottom, right, top), box))
    return units


def edge_side(box):
    x0, y0, x1, y1 = box
    inner = values.POSITION_SCALE - values.EDGE
    for side, hit in zip(SIDES, (y1 <= values.EDGE, y0 >= inner, x1 <= values.EDGE, x0 >= inner)):
        if hit:
            return side
    return None


def margin_key(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text) if not (c.isspace() or "0" <= c <= "9"))


def page_text(textpage):
    return textpage.get_text_range().replace("\r\n", "\n")


def line_numbers(text):
    """行番号のあるページなら、番号つきの行の番号（文字列）のリストを返す。そうでなければ空のリスト（2.6）。"""
    lines = [x for x in text.split("\n") if x.strip()]  # 空でない行
    nums = [m.group(1) for m in map(_NUMBERED.match, lines) if m]
    numbered = (len(nums) >= values.LINE_NUMBER_MIN_LINES and len(nums) * 5 >= len(lines) * 4  # 8割以上
                and all(int(b) == int(a) + 1 for a, b in zip(nums, nums[1:])))
    return nums if numbered else []


def _strip_text(text):
    return "\n".join(_LINE_NUMBER.sub("", x) if _NUMBERED.match(x) else x for x in text.split("\n"))


def _strip_units(units, nums):
    """units は [{"text", ...}]。番号ごとに、前に選んだ単位より後ろの、番号で始まる最初の単位から番号を除く。"""
    k = 0
    for n in nums:
        head = re.compile(r"^\s*%s(\s|$)" % n)
        hit = next((i for i in range(k, len(units)) if head.match(units[i]["text"])), None)
        if hit is not None:
            units[hit]["text"] = re.sub(r"^\s*%s\s?" % n, "", units[hit]["text"])
            k = hit + 1


def unit_height(box):
    return (box[1] + box[3]) // 2


def find_margins(pages):
    """pages はページごとの単位のリスト。毎ページ繰り返すヘッダーとフッターの文字列を返す（2.6 の 1〜4）。"""
    if len(pages) < values.MARGIN_MIN_PAGES:
        return []
    by_key = {}
    for p, units in enumerate(pages, 1):
        for i, (text, box) in enumerate(units):
            side = edge_side(box)
            if side:
                by_key.setdefault(margin_key(text), []).append((unit_height(box), p, i, side, text))
    found = []
    for key, items in by_key.items():
        items.sort(key=lambda t: t[:3])
        while items:
            h = items[0][0]
            group = [t for t in items if t[0] <= h + values.MARGIN_BAND]
            items = items[len(group):]
            if len({t[1] for t in group}) * 2 >= len(pages):
                first = min(group, key=lambda t: t[1])
                found.append({"key": key, "side": group[0][3], "y": h, "text": first[4]})
    found.sort(key=lambda m: (SIDES.index(m["side"]), m["y"], m["key"]))
    return found


def read_pdf(path):
    """(ページの数, text_check, margins, line_numbers) を返す。開けないときと、0 ページのときは ValueError。"""
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    try:
        doc = pdfium.PdfDocument(path)
    except Exception as e:
        raise ValueError(str(e))
    try:
        if len(doc) == 0:
            raise ValueError("0 ページ")
        total = unmapped = 0
        pages, numbered = [], 0
        for k in range(len(doc)):
            page = doc[k]
            textpage = page.get_textpage()
            n = textpage.count_chars()
            total += n
            unmapped += sum(1 for c in range(n) if raw.FPDFText_HasUnicodeMapError(textpage.raw, c) == 1)
            width, height = page.get_size()
            pages.append(text_units(textpage, width, height))
            numbered += bool(line_numbers(page_text(textpage)))
            textpage.close()
            page.close()
    finally:
        doc.close()
    text_check = total > 0 and unmapped / total <= values.UNMAPPED_RATIO
    return len(pages), text_check, find_margins(pages), numbered * 2 >= len(pages)


def is_margin(text, box, margins):
    """余白の単位か（2.6 の最後）。"""
    if not edge_side(box):
        return False
    key, h = margin_key(text), unit_height(box)
    return any(m["key"] == key and m["y"] <= h <= m["y"] + values.MARGIN_BAND for m in margins)


def prepare_pages(path, info, pages, folder):
    """ページの画像、埋め込みテキスト、単位の JSON を作る（6.2 の渡す前の準備）。あるファイルは作り直さない。"""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(path)
    try:
        for n in pages:
            base = os.path.join(folder, "%04d" % n)
            if all(os.path.isfile(base + ext) for ext in (".png", ".txt", ".json")):
                continue
            page = doc[n - 1]
            textpage = page.get_textpage()
            width, height = page.get_size()
            if not os.path.isfile(base + ".png"):
                os.makedirs(folder, exist_ok=True)
                page.render(scale=values.PAGE_DPI / 72).to_pil().save(base + ".png")
            text = page_text(textpage)
            nums = line_numbers(text) if info["line_numbers"] else []
            if not os.path.isfile(base + ".txt"):
                files.write_text(base + ".txt", _strip_text(text) if nums else text)
            if not os.path.isfile(base + ".json"):
                units = [{"text": t, "box": b, "margin": is_margin(t, b, info["margins"])}
                         for t, b in text_units(textpage, width, height)]
                _strip_units(units, nums)
                check = info["text_check"] and any(check_strings(u["text"]) for u in units if not u["margin"])
                files.write_text(base + ".json", files.dumps(
                    {"page": n, "size": [width, height], "check": check, "units": units}))
            textpage.close()
            page.close()
    finally:
        doc.close()


def crop_figures(path, figures):
    """figures は (ページ, (x0, y0, x1, y1), 書く先) のリスト。範囲は 0〜1 の割合。"""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(path)
    try:
        for n in sorted({f[0] for f in figures}):
            page = doc[n - 1]
            image = page.render(scale=values.FIGURE_DPI / 72).to_pil()
            w, h = image.size
            for _, (x0, y0, x1, y1), dest in (f for f in figures if f[0] == n):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                image.crop((round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h))).save(dest)
            page.close()
    finally:
        doc.close()
