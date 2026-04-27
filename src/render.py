"""anseropolis.render — Tailwind HTML card + Playwright screenshot (1080×1080)."""

from pathlib import Path

from src.config import OUTPUT_DIR

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
TEMPLATE = (TEMPLATES_DIR / "card.html").read_text(encoding="utf-8")

RECOMMENDED_THEMES = ["slate", "sky", "emerald", "amber", "violet", "rose"]


def _theme_classes(theme: str) -> dict:
    return {
        "bg_dark": f"{theme}-900",
        "bg_card": f"{theme}-800",
        "accent": f"{theme}-400",
        "text_muted": f"{theme}-400",
        "text_dim": f"{theme}-500",
        "border": f"{theme}-700",
    }


def _score_color(total: int) -> str:
    if total >= 70:
        return "text-red-400"
    elif total >= 40:
        return "text-amber-400"
    elif total >= 20:
        return "text-yellow-300"
    return "text-green-400"


def _render_phrases(phrases: list[dict]) -> str:
    if not phrases:
        return ""
    tags = " ".join(
        f'<span class="bg-red-500/20 text-red-300 text-xs px-2 py-0.5 rounded">{p["phrase"]}</span>'
        for p in phrases[:5]
    )
    return f'<div class="flex flex-wrap gap-1 ml-4">{tags}</div>'


def _render_match(match_result: list[dict]) -> str:
    if not match_result:
        return '<div class="text-sm text-slate-400 mb-3">謠言庫無相似比對</div>'
    top = match_result[0]
    sim = top.get("similarity", 0)
    title = top.get("title", "")[:50]
    verdict = top.get("verdict", "")
    return f'''<div class="bg-red-900/30 rounded-lg p-3 mb-3">
    <div class="text-xs text-red-300 mb-1">謠言庫最佳比對 (sim={sim:.3f})</div>
    <div class="text-sm font-medium">[{verdict}] {title}</div>
  </div>'''


def _render_claims(claims: list[dict]) -> str:
    if not claims:
        return '<div class="text-sm text-slate-400">無聲明拆解結果</div>'
    html = ""
    for c in claims:
        text = c.get("text", "")[:55]
        verdict = c.get("assessment", {}).get("verdict", "?")
        icon = {"supported": "✓", "refuted": "✗", "insufficient": "？"}.get(verdict, "？")
        color = {"supported": "text-green-400", "refuted": "text-red-400"}.get(verdict, "text-yellow-400")
        html += f'''<div class="flex items-start gap-2">
      <span class="{color} font-bold">{icon}</span>
      <span class="text-sm">{text}</span>
    </div>\n'''
    return html


def _render_diff(claims: list[dict]) -> str:
    """Render NER/number/timeline diff for all claims."""
    all_diffs = []
    for c in claims:
        d = c.get("diff", {})
        for item in d.get("ner", []):
            all_diffs.append(("NER", "bg-red-500/20 text-red-400", item))
        for item in d.get("numbers", []):
            all_diffs.append(("數字", "bg-amber-500/20 text-amber-400", item))
        for item in d.get("timeline", []):
            all_diffs.append(("時間", "bg-purple-500/20 text-purple-400", item))

    if not all_diffs:
        return ""

    html = '<div class="space-y-2 mb-3">\n'
    html += '<div class="text-xs text-slate-400 mb-1 uppercase tracking-wide">結構化比對</div>\n'
    for label, cls, item in all_diffs[:5]:  # limit to 5 to fit card
        html += f'''<div class="flex items-start gap-2">
      <span class="shrink-0 {cls} text-xs font-bold px-1.5 py-0.5 rounded">{label}</span>
      <div class="text-xs">
        <span class="text-red-300">{item.get("claim_says","")[:40]}</span> →
        <span class="text-green-300">{item.get("evidence_says","")[:40]}</span>
      </div>
    </div>\n'''
    html += '</div>'
    return html


def render_html(pkg: dict, theme: str = "slate") -> str:
    """Render a package result to HTML."""
    tc = _theme_classes(theme)
    score_data = pkg.get("score", {})
    total = score_data.get("total", 0)
    claims = pkg.get("claims", [])

    html = TEMPLATE
    for key, val in tc.items():
        html = html.replace("{{" + key + "}}", val)

    original = pkg.get("original_text", pkg.get("text", ""))
    if len(original) > 100:
        original = original[:100] + "…"

    html = html.replace("{{original_text}}", original)
    html = html.replace("{{score}}", str(total))
    html = html.replace("{{score_label}}", score_data.get("label", ""))
    html = html.replace("{{score_color}}", _score_color(total))
    html = html.replace("{{suspect_phrases}}", _render_phrases(score_data.get("phrases", [])))
    html = html.replace("{{match_section}}", _render_match(pkg.get("matches", [])))
    html = html.replace("{{claims}}", _render_claims(claims))
    html = html.replace("{{diff_section}}", _render_diff(claims))
    html = html.replace("{{footer}}", "Anseropolis v0.1 · 可疑度分數僅供參考，非最終判定")
    return html


def render(pkg: dict, theme: str = "slate") -> Path:
    """Render package to 1080×1080 PNG. Returns output path."""
    from playwright.sync_api import sync_playwright

    OUTPUT_DIR.mkdir(exist_ok=True)
    fingerprint = pkg.get("slug", "card")
    out_path = OUTPUT_DIR / f"{fingerprint}_card.png"

    html = render_html(pkg, theme)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1080})
        page.set_content(html, wait_until="networkidle")
        page.screenshot(path=str(out_path), clip={"x": 0, "y": 0, "width": 1080, "height": 1080})
        browser.close()

    return out_path
