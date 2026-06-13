#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
인스타 카드뉴스 생성기 — "한국에서 1인 창업 정보"

content.py 의 CARDS / BRAND 를 읽어 1080x1080 카드 HTML 들과
미리보기 갤러리(index.html)를 만든다. PNG 추출은 render.sh 참고.

사용법:
    python3 generate.py
"""
import html
import os
import pathlib

from content import BRAND, CARDS

ROOT = pathlib.Path(__file__).resolve().parent
CARDS_DIR = ROOT / "cards"
SIZE = 1080  # 인스타 정사각형


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def nl(s: str) -> str:
    """본문 줄바꿈(\n)을 <br>로."""
    return esc(s).replace("\n", "<br>")


# ----------------------------------------------------------------------------
# 카드 본문(type 별) 렌더링
# ----------------------------------------------------------------------------
def render_points(points):
    rows = []
    for i, p in enumerate(points, 1):
        if isinstance(p, str):
            head, desc = p, ""
        else:
            head, desc = p.get("head", ""), p.get("desc", "")
        desc_html = f'<div class="p-desc">{nl(desc)}</div>' if desc else ""
        rows.append(
            f'<li class="point">'
            f'<span class="p-num">{i}</span>'
            f'<div class="p-body"><div class="p-head">{nl(head)}</div>{desc_html}</div>'
            f"</li>"
        )
    return f'<ul class="points">{"".join(rows)}</ul>'


def render_checks(points):
    rows = []
    for p in points:
        head = p if isinstance(p, str) else p.get("head", "")
        rows.append(f'<li class="check"><span class="box">✓</span><span>{nl(head)}</span></li>')
    return f'<ul class="checks">{"".join(rows)}</ul>'


def render_body(card):
    t = card.get("type", "content")

    if t == "cover":
        sub = f'<p class="cover-sub">{nl(card.get("subtitle",""))}</p>' if card.get("subtitle") else ""
        return (
            '<div class="cover">'
            f'<div class="cover-kicker">{nl(card.get("kicker",""))}</div>'
            f'<h1 class="cover-title">{nl(card.get("title",""))}</h1>'
            f"{sub}"
            "</div>"
        )

    if t == "cta":
        sub = f'<p class="cta-sub">{nl(card.get("subtitle",""))}</p>' if card.get("subtitle") else ""
        action = f'<div class="cta-action">{nl(card.get("action",""))}</div>' if card.get("action") else ""
        note = f'<p class="cta-note">{nl(card.get("note",""))}</p>' if card.get("note") else ""
        return (
            '<div class="cover cta">'
            f'<div class="cover-kicker">{nl(card.get("kicker",""))}</div>'
            f'<h1 class="cover-title">{nl(card.get("title",""))}</h1>'
            f"{action}{sub}{note}"
            "</div>"
        )

    # content / stat 공통 헤더
    step = f'<div class="step">{nl(card.get("step",""))}</div>' if card.get("step") else ""
    head = f'<h2 class="card-title">{nl(card.get("title",""))}</h2>'
    lead = f'<p class="lead">{nl(card.get("subtitle",""))}</p>' if card.get("subtitle") else ""

    if t == "stat":
        big = f'<div class="stat-big">{nl(card.get("big",""))}</div>' if card.get("big") else ""
        cap = f'<div class="stat-cap">{nl(card.get("big_caption",""))}</div>' if card.get("big_caption") else ""
        pts = render_points(card.get("points", [])) if card.get("points") else ""
        return f'<div class="card-head">{step}{head}{lead}</div><div class="stat-wrap">{big}{cap}</div>{pts}'

    if card.get("style") == "check":
        body = render_checks(card.get("points", []))
    else:
        body = render_points(card.get("points", []))
    return f'<div class="card-head">{step}{head}{lead}</div>{body}'


# ----------------------------------------------------------------------------
# 페이지 템플릿
# ----------------------------------------------------------------------------
def page_html(card, idx, total, standalone=True):
    theme = card.get("theme", "light")
    body = render_body(card)
    handle = esc(BRAND["handle"])
    tag = esc(BRAND.get("tagline", ""))
    indicator = f"{idx:02d} <span>/ {total:02d}</span>"
    css_ref = '<link rel="stylesheet" href="../style.css">' if standalone else ""
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{handle} · {idx:02d}</title>{css_ref}</head>
<body class="theme-{theme}">
<section class="page">
  <div class="bg-blob blob-a"></div>
  <div class="bg-blob blob-b"></div>
  <header class="top">
    <div class="brand">{handle}</div>
    <div class="indicator">{indicator}</div>
  </header>
  <main class="content">
    {body}
  </main>
  <footer class="bottom">
    <div class="foot-tag">{tag}</div>
    <div class="swipe">{"시작 →" if card.get("type")=="cover" else ("저장하기 📌" if card.get("type")=="cta" else "넘기기 →")}</div>
  </footer>
</section>
</body></html>"""


def gallery_html(total):
    cells = []
    for i in range(1, total + 1):
        cells.append(
            f'<a class="cell" href="cards/{i:02d}.html" target="_blank">'
            f'<div class="frame"><iframe src="cards/{i:02d}.html" scrolling="no"></iframe></div>'
            f'<div class="cap">{i:02d}</div></a>'
        )
    handle = esc(BRAND["handle"])
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>카드뉴스 미리보기 — 한국에서 1인 창업</title>
<style>
  :root {{ --thumb: 300px; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#0e0f13; color:#f4f3ef;
    font-family:"Apple SD Gothic Neo","Pretendard",system-ui,sans-serif; padding:48px; }}
  h1 {{ font-size:28px; margin:0 0 6px; }}
  .sub {{ color:#9aa0aa; margin:0 0 32px; font-size:15px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(var(--thumb),1fr)); gap:28px; }}
  .cell {{ text-decoration:none; color:inherit; }}
  .frame {{ width:var(--thumb); height:var(--thumb); border-radius:18px; overflow:hidden;
    box-shadow:0 10px 30px rgba(0,0,0,.45); background:#fff; }}
  iframe {{ width:{SIZE}px; height:{SIZE}px; border:0;
    transform:scale(calc(var(--thumb) / {SIZE})); transform-origin:top left; }}
  .cap {{ margin-top:10px; font-size:13px; color:#9aa0aa; letter-spacing:.05em; }}
  .cell:hover .frame {{ outline:3px solid #5b5bd6; }}
</style></head>
<body>
  <h1>한국에서 1인 창업 — 인스타 카드뉴스</h1>
  <p class="sub">{handle} · 총 {total}장 · 카드를 클릭하면 1080×1080 원본이 열립니다. PNG 추출은 render.sh 참고.</p>
  <div class="grid">{"".join(cells)}</div>
</body></html>"""


def main():
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    total = len(CARDS)
    for i, card in enumerate(CARDS, 1):
        (CARDS_DIR / f"{i:02d}.html").write_text(page_html(card, i, total), encoding="utf-8")
    (ROOT / "index.html").write_text(gallery_html(total), encoding="utf-8")
    (ROOT / "style.css").write_text(STYLE, encoding="utf-8")
    print(f"✓ {total}장 생성 완료 → {CARDS_DIR}")
    print(f"✓ 미리보기 → {ROOT/'index.html'}")


# ----------------------------------------------------------------------------
# 디자인 (style.css)
# ----------------------------------------------------------------------------
STYLE = r"""
/* ===== 한국 1인 창업 카드뉴스 디자인 ===== */
:root{
  --ink:#16181d; --paper:#faf8f3; --muted:#5b6068;
  --accent:#5b5bd6;        /* iris/indigo */
  --accent-2:#12b886;      /* growth green */
  --accent-soft:#ecebff;
  --line:#e7e3da;
}
*{box-sizing:border-box;margin:0;padding:0;}
html,body{width:1080px;height:1080px;}
body{
  font-family:"Apple SD Gothic Neo","Pretendard","Noto Sans KR",system-ui,sans-serif;
  -webkit-font-smoothing:antialiased; overflow:hidden;
  word-break:keep-all;
}
.page{
  position:relative; width:1080px; height:1080px; overflow:hidden;
  display:flex; flex-direction:column;
  padding:90px 88px 76px; background:var(--paper); color:var(--ink);
}
/* 테마 */
.theme-light .page{ background:var(--paper); color:var(--ink); }
.theme-dark .page{ background:#14141b; color:#f6f5f1; }

/* 배경 장식 */
.bg-blob{ position:absolute; border-radius:50%; filter:blur(10px); opacity:.5; z-index:0; }
.blob-a{ width:520px; height:520px; right:-160px; top:-160px;
  background:radial-gradient(circle at 30% 30%, var(--accent), transparent 70%); }
.blob-b{ width:460px; height:460px; left:-180px; bottom:-200px;
  background:radial-gradient(circle at 50% 50%, var(--accent-2), transparent 70%); opacity:.35; }
.theme-dark .blob-a{ opacity:.55; }
.theme-dark .blob-b{ opacity:.4; }

/* 상·하단 바 */
.top,.bottom{ position:relative; z-index:2; display:flex; align-items:center;
  justify-content:space-between; }
.brand{ font-weight:800; font-size:30px; letter-spacing:-.01em; }
.indicator{ font-size:26px; font-weight:700; color:var(--accent); }
.indicator span{ color:var(--muted); font-weight:600; }
.theme-dark .indicator span{ color:#8b8f99; }
.bottom{ margin-top:auto; padding-top:24px; border-top:2px solid var(--line); }
.theme-dark .bottom{ border-top-color:rgba(255,255,255,.12); }
.foot-tag{ font-size:25px; color:var(--muted); }
.theme-dark .foot-tag{ color:#9aa0aa; }
.swipe{ font-size:25px; font-weight:700; color:var(--accent); }

/* 본문 컨테이너 */
.content{ position:relative; z-index:2; flex:1; display:flex; flex-direction:column;
  justify-content:center; padding:30px 0; }

/* ----- 표지 / CTA ----- */
.cover{ display:flex; flex-direction:column; gap:30px; }
.cover-kicker{ display:inline-block; align-self:flex-start; font-size:30px; font-weight:800;
  color:#fff; background:var(--accent); padding:12px 26px; border-radius:999px;
  letter-spacing:.02em; }
.cover-title{ font-size:108px; line-height:1.12; font-weight:900; letter-spacing:-.03em; }
.theme-dark .cover-title{ color:#fff; }
.cover-sub,.cta-sub{ font-size:40px; line-height:1.5; color:var(--muted); font-weight:500; }
.theme-dark .cover-sub,.theme-dark .cta-sub{ color:#c3c7cf; }
.cta-action{ font-size:46px; font-weight:800; color:var(--accent-2); line-height:1.4; }
.cta-note{ margin-top:8px; font-size:26px; line-height:1.55; color:#8b8f99; }

/* ----- 콘텐츠 헤더 ----- */
.card-head{ margin-bottom:44px; }
.step{ display:inline-block; font-size:27px; font-weight:800; color:var(--accent);
  background:var(--accent-soft); padding:9px 22px; border-radius:12px; margin-bottom:22px; }
.theme-dark .step{ background:rgba(91,91,214,.22); }
.card-title{ font-size:70px; line-height:1.18; font-weight:900; letter-spacing:-.03em; }
.lead{ margin-top:18px; font-size:34px; line-height:1.5; color:var(--muted); }
.theme-dark .lead{ color:#c3c7cf; }

/* ----- 포인트 리스트 ----- */
.points{ list-style:none; display:flex; flex-direction:column; gap:30px; }
.point{ display:flex; gap:26px; align-items:flex-start; }
.p-num{ flex:0 0 64px; width:64px; height:64px; border-radius:18px; background:var(--accent);
  color:#fff; font-weight:800; font-size:34px; display:flex; align-items:center;
  justify-content:center; }
.p-body{ padding-top:2px; }
.p-head{ font-size:42px; font-weight:800; line-height:1.32; letter-spacing:-.02em; }
.p-desc{ margin-top:8px; font-size:31px; line-height:1.5; color:var(--muted); font-weight:500; }
.theme-dark .p-desc{ color:#aab0ba; }

/* ----- 체크리스트 ----- */
.checks{ list-style:none; display:flex; flex-direction:column; gap:28px; }
.check{ display:flex; gap:24px; align-items:center; font-size:42px; font-weight:700;
  line-height:1.35; }
.check .box{ flex:0 0 60px; width:60px; height:60px; border-radius:16px;
  background:var(--accent-2); color:#fff; font-size:34px; font-weight:900;
  display:flex; align-items:center; justify-content:center; }

/* ----- 스탯 ----- */
.stat-wrap{ text-align:center; margin:10px 0 40px; }
.stat-big{ font-size:150px; font-weight:900; line-height:1; letter-spacing:-.04em;
  color:var(--accent); }
.stat-cap{ margin-top:14px; font-size:34px; font-weight:600; color:var(--muted); }
.theme-dark .stat-cap{ color:#c3c7cf; }
"""


if __name__ == "__main__":
    main()
