"""Generate architecture.png — the assignment §9.1 recommended deliverable.
A clean, labelled, A→Z data-flow diagram (ingestion + query paths) using only
Pillow so the build has no extra dependencies."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "architecture.png"

W, H = 1800, 1000
BG = (250, 251, 253)
INK = (24, 32, 48)
SUBTLE = (110, 120, 138)
EDGE = (90, 110, 140)

# Service palette (Azure-ish, accessible)
COLORS = {
    "user":   ((230, 240, 255), (60, 90, 160)),
    "azure":  ((220, 235, 255), (20, 90, 200)),
    "ai":     ((220, 240, 220), (40, 130, 60)),
    "search": ((255, 235, 215), (190, 110, 30)),
    "store":  ((240, 232, 255), (110, 70, 180)),
    "app":    ((255, 230, 230), (180, 60, 70)),
}


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


F_TITLE, F_LANE, F_BOX, F_SUB, F_EDGE = _font(34), _font(22), _font(20), _font(16), _font(15)


def box(draw, x, y, w, h, title, sub, kind):
    fill, border = COLORS[kind]
    draw.rounded_rectangle((x, y, x + w, y + h), radius=14, fill=fill, outline=border, width=2)
    draw.text((x + 14, y + 12), title, font=F_BOX, fill=INK)
    if sub:
        for i, line in enumerate(sub.split("\n")):
            draw.text((x + 14, y + 40 + i * 20), line, font=F_SUB, fill=SUBTLE)
    return (x + w / 2, y + h / 2)


def arrow(draw, src, dst, label="", curve=0):
    x1, y1 = src
    x2, y2 = dst
    if curve == 0:
        draw.line((x1, y1, x2, y2), fill=EDGE, width=2)
        head_x, head_y = x2, y2
    else:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 + curve
        draw.line((x1, y1, mx, my), fill=EDGE, width=2)
        draw.line((mx, my, x2, y2), fill=EDGE, width=2)
        head_x, head_y = x2, y2
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    a1 = (head_x - 12 * math.cos(angle - 0.4), head_y - 12 * math.sin(angle - 0.4))
    a2 = (head_x - 12 * math.cos(angle + 0.4), head_y - 12 * math.sin(angle + 0.4))
    draw.polygon([(head_x, head_y), a1, a2], fill=EDGE)
    if label:
        lx = (x1 + x2) / 2
        ly = (y1 + y2) / 2 + curve - 12
        draw.text((lx, ly), label, font=F_EDGE, fill=SUBTLE, anchor="mm")


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Title
    draw.text((W / 2, 32), "Intelligent Document Processing & Q&A — Azure Free-Tier Architecture",
              font=F_TITLE, fill=INK, anchor="mm")
    draw.text((W / 2, 66),
              "AI-first: every intelligent step is an Azure AI model · Python is thin typed plumbing",
              font=F_SUB, fill=SUBTLE, anchor="mm")

    # Lane labels
    draw.text((40, 110), "INGESTION  (async per document)", font=F_LANE, fill=INK)
    draw.text((40, 540), "QUERY  (per chat turn — multi-turn)", font=F_LANE, fill=INK)
    draw.line((30, 510, W - 30, 510), fill=(220, 222, 228), width=1)

    # Ingestion row
    b_upload = box(draw,   60, 150, 200, 80, "Upload (PDF/DOCX/Image)",
                   "POST /documents · 202 + doc_id\nFastAPI BackgroundTasks", "user")
    b_blob   = box(draw,  300, 150, 200, 80, "Azure Blob Storage",
                   "originals/  · extracts/", "store")
    b_di     = box(draw,  540, 150, 230, 80, "Document Intelligence",
                   "prebuilt-layout (markdown)\npages[].spans → page mapping", "azure")
    b_cls    = box(draw,  810, 150, 200, 80, "GPT-4o-mini",
                   "doc-type classification", "ai")
    b_chunk  = box(draw, 1050, 150, 240, 80, "Hybrid Structural Chunker",
                   "headings → 512-tok cap\ntables atomic · breadcrumbs", "app")
    b_embed  = box(draw, 1330, 150, 200, 80, "Azure OpenAI",
                   "text-embedding-3-small", "ai")
    b_index  = box(draw, 1570, 150, 200, 80, "Azure AI Search",
                   "hybrid index (Free F1)", "search")
    b_status = box(draw,  540, 280, 720, 60, "Status machine",
                   "uploaded → extracting → classifying → chunking → indexing → ready | failed", "app")

    for a, b in [(b_upload, b_blob), (b_blob, b_di), (b_di, b_cls), (b_cls, b_chunk),
                 (b_chunk, b_embed), (b_embed, b_index)]:
        arrow(draw, a, b)

    # Query row
    b_q      = box(draw,   60, 580, 200, 80, "User question",
                   "+ chat history", "user")
    b_plan   = box(draw,  300, 580, 240, 80, "GPT-4o-mini · Query Planner",
                   "Structured Outputs:\nstandalone_query + intent", "ai")
    b_simple = box(draw,  600, 540, 240, 70, "Hybrid Search (simple)",
                   "BM25 + vector + RRF", "search")
    b_fanout = box(draw,  600, 630, 240, 70, "Comparison Fan-out",
                   "facet doc_name → per-doc subqueries", "search")
    b_gate   = box(draw,  900, 580, 220, 80, "Refusal Gate",
                   "RRF floor + LLM\ninsufficient_context", "app")
    b_ans    = box(draw, 1170, 580, 240, 80, "GPT-4o-mini · Grounded Answer",
                   "Structured Outputs:\nanswer + citations[]", "ai")
    b_ui     = box(draw, 1470, 580, 220, 80, "Streamlit Chat UI",
                   "clickable citations →\npage + verbatim quote", "user")

    arrow(draw, b_q, b_plan)
    arrow(draw, b_plan, b_simple, curve=-30)
    arrow(draw, b_plan, b_fanout, curve=30)
    arrow(draw, b_simple, b_gate, curve=-10)
    arrow(draw, b_fanout, b_gate, curve=10)
    arrow(draw, b_gate, b_ans)
    arrow(draw, b_ans, b_ui)

    # Index plumb-line from ingestion → query
    arrow(draw, (b_index[0], 230), (b_simple[0], 540), curve=0)
    draw.text((b_index[0] - 60, 380), "indexed chunks", font=F_EDGE, fill=SUBTLE)

    # Legend
    legend_y = 840
    draw.text((60, legend_y - 10), "Legend", font=F_LANE, fill=INK)
    for i, (kind, label) in enumerate([
        ("azure",  "Azure AI service"),
        ("ai",     "Azure OpenAI (model)"),
        ("search", "Azure AI Search (hybrid)"),
        ("store",  "Azure Blob Storage"),
        ("app",    "Application logic"),
        ("user",   "User / UI"),
    ]):
        x = 60 + i * 270
        fill, border = COLORS[kind]
        draw.rounded_rectangle((x, legend_y + 20, x + 30, legend_y + 44), radius=6,
                               fill=fill, outline=border, width=2)
        draw.text((x + 40, legend_y + 22), label, font=F_SUB, fill=INK)

    draw.text((W / 2, H - 20),
              "Free tier: Document Intelligence F0 (500 pages/mo, 2-page-window splitter)  ·  "
              "Azure AI Search Free F1 (hybrid BM25+vector+RRF)  ·  "
              "Azure OpenAI on Free Account $200 credit  ·  total project spend < $5",
              font=F_EDGE, fill=SUBTLE, anchor="mm")

    img.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
