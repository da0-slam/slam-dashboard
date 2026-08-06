"""콘텐츠 성과 리포트를 PDF로 내보내기.

브라우저 인쇄(Ctrl+P)는 사이드바·다크 배경·표 잘림 등으로 결과물이 깨지기 쉬워서,
서버에서 reportlab으로 직접 PDF를 조립한다. 차트는 matplotlib으로 정적 이미지를
만들어 삽입한다 (인터랙티브 plotly 대신 — kaleido 같은 무거운 렌더러 의존성을 피함).
"""
import io
import os
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage,
)

_FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts", "NotoSansKR-Variable.ttf")
_FONT_NAME = "NotoKR"
_ACCENT = "#FF6B2C"

_registered = False


def _ensure_font() -> None:
    global _registered
    if _registered:
        return
    pdfmetrics.registerFont(TTFont(_FONT_NAME, _FONT_PATH))
    if _FONT_PATH not in [f.fname for f in fm.fontManager.ttflist]:
        fm.fontManager.addfont(_FONT_PATH)
    plt.rcParams["font.family"] = fm.FontProperties(fname=_FONT_PATH).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    _registered = True


def _fig_to_image(fig, width_mm: float) -> RLImage:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    img = RLImage(buf)
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth = width_mm * mm
    img.drawHeight = width_mm * mm * ratio
    return img


def _bar_chart_image(df: pd.DataFrame, cols: list[str], colors_: list[str], width_mm: float):
    fig, ax = plt.subplots(figsize=(5, 3.2))
    df[cols].plot(kind="bar", ax=ax, color=colors_, width=0.7)
    ax.set_xlabel("")
    ax.tick_params(axis="x", rotation=30, labelsize=8)
    ax.tick_params(axis="y", labelsize=8)
    ax.legend(fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    return _fig_to_image(fig, width_mm)


def _pie_chart_image(counter: Counter, colors_: list[str], width_mm: float, top_n: int = 5):
    total = sum(counter.values())
    ranked = counter.most_common()
    top, rest = ranked[:top_n], ranked[top_n:]
    labels = [name for name, _ in top]
    values = [cnt for _, cnt in top]
    if rest:
        labels.append("기타")
        values.append(sum(cnt for _, cnt in rest))

    fig, ax = plt.subplots(figsize=(3.4, 3.4))
    ax.pie(
        values, labels=labels, autopct=lambda p: f"{p:.1f}%" if p >= 1 else "",
        startangle=90, colors=colors_[:len(labels)],
        wedgeprops=dict(width=0.55, edgecolor="white"),
        textprops=dict(fontsize=8),
    )
    fig.tight_layout()
    return _fig_to_image(fig, width_mm)


def build_content_report_pdf(
    *,
    brand_name: str,
    campaign_name: str,
    kpi: dict,
    top_influencers_df: pd.DataFrame,
    platform_df: pd.DataFrame,
    region_counter: Counter | None,
    language_counter: Counter | None,
    influencer_summary_df: pd.DataFrame,
    top_views_df: pd.DataFrame,
    top_er_df: pd.DataFrame,
) -> bytes:
    _ensure_font()

    styles = {
        "title": ParagraphStyle("title", fontName=_FONT_NAME, fontSize=18, leading=22, spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", fontName=_FONT_NAME, fontSize=9, textColor=colors.grey, spaceAfter=12),
        "h2": ParagraphStyle("h2", fontName=_FONT_NAME, fontSize=13, leading=16, spaceBefore=14, spaceAfter=8,
                              textColor=colors.HexColor("#111111")),
        "body": ParagraphStyle("body", fontName=_FONT_NAME, fontSize=9, leading=13),
        "cell": ParagraphStyle("cell", fontName=_FONT_NAME, fontSize=8, leading=11),
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=16 * mm, bottomMargin=16 * mm, leftMargin=16 * mm, rightMargin=16 * mm,
    )
    story = []

    story.append(Paragraph("SLAM — 공유된 콘텐츠 성과 리포트", styles["subtitle"]))
    story.append(Paragraph(f"{brand_name} · {campaign_name}", styles["title"]))

    # ── KPI ──────────────────────────────────────────────────────────────────
    kpi_rows = []
    if kpi.get("participant_count"):
        kpi_rows.append([
            ("📦 발송 인원", f"{kpi['participant_count']:,}명"),
            ("📤 업로드 인원", f"{kpi['total_influencers']:,}명"),
            ("📊 업로드율", f"{kpi['upload_rate']:.1f}%"),
        ])
    kpi_rows.append([
        ("참여 인플루언서", f"{kpi['total_influencers']:,}"),
        ("총 게시물", f"{kpi['total_posts']:,}"),
        ("Instagram", f"{kpi['ig_posts']:,}"),
        ("TikTok", f"{kpi['tt_posts']:,}"),
        ("X / 기타", f"{kpi['x_other_posts']:,}"),
    ])
    kpi_rows.append([
        ("평균 참여율", f"{kpi['avg_er']:.1f}%"),
        ("총 조회수", f"{kpi['total_views']:,}"),
        ("총 좋아요", f"{kpi['total_likes']:,}"),
        ("총 댓글", f"{kpi['total_comments']:,}"),
        ("총 저장", f"{kpi['total_saves']:,}"),
    ])

    for row in kpi_rows:
        t = Table(
            [[Paragraph(f"<font size=7 color='#888888'>{lbl}</font><br/><font size=13>{val}</font>", styles["cell"])
              for lbl, val in row]],
            colWidths=[(178 * mm) / len(row)] * len(row),
        )
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)
    story.append(Spacer(1, 4 * mm))

    # ── 차트 ─────────────────────────────────────────────────────────────────
    if not top_influencers_df.empty:
        story.append(Paragraph("👑 인플루언서별 조회수 TOP 10", styles["h2"]))
        story.append(_bar_chart_image(top_influencers_df, ["총 조회수"], [_ACCENT], 170))

    if not platform_df.empty:
        story.append(Paragraph("📊 플랫폼별 성과 비교", styles["h2"]))
        story.append(_bar_chart_image(platform_df, ["총_조회수", "총_좋아요"], ["#1d4ed8", "#93c5fd"], 170))

    # ── 댓글 분석 ────────────────────────────────────────────────────────────
    if region_counter or language_counter:
        story.append(Paragraph("💬 틱톡 댓글 분석", styles["h2"]))
        _region_colors   = ["#6366f1", "#818cf8", "#a5b4fc", "#c7d2fe", "#e0e7ff", "#d1d5db"]
        _language_colors = ["#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe", "#dbeafe", "#d1d5db"]
        cells = []
        if region_counter:
            cells.append(_pie_chart_image(region_counter, _region_colors, 78))
        if language_counter:
            cells.append(_pie_chart_image(language_counter, _language_colors, 78))
        if len(cells) == 2:
            t = Table([cells], colWidths=[89 * mm, 89 * mm])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story.append(t)
        elif cells:
            story.append(cells[0])

    # ── 인플루언서별 성과 요약 ────────────────────────────────────────────────
    if not influencer_summary_df.empty:
        story.append(Paragraph("인플루언서별 성과 요약", styles["h2"]))
        story.append(_df_to_table(influencer_summary_df, styles["cell"]))

    # ── 우수 콘텐츠 ──────────────────────────────────────────────────────────
    if not top_views_df.empty or not top_er_df.empty:
        story.append(Paragraph("⭐ 우수 콘텐츠", styles["h2"]))
        if not top_views_df.empty:
            story.append(Paragraph("조회수 TOP 5", styles["body"]))
            story.append(_df_to_table(top_views_df, styles["cell"]))
            story.append(Spacer(1, 3 * mm))
        if not top_er_df.empty:
            story.append(Paragraph("참여율 TOP 5", styles["body"]))
            story.append(_df_to_table(top_er_df, styles["cell"]))

    doc.build(story)
    return buf.getvalue()


def _df_to_table(df: pd.DataFrame, cell_style: ParagraphStyle) -> Table:
    header = [Paragraph(f"<b>{c}</b>", cell_style) for c in df.columns]
    body = [
        [Paragraph(_cell_text(v), cell_style) for v in row]
        for row in df.itertuples(index=False)
    ]
    t = Table([header] + body, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _cell_text(v) -> str:
    if isinstance(v, float):
        return f"{v:,.1f}" if v != int(v) else f"{int(v):,}"
    if isinstance(v, int):
        return f"{v:,}"
    s = str(v)
    return s if len(s) <= 60 else s[:57] + "..."
