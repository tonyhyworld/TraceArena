from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUT = Path(__file__).parent / "assets"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 1600, 900
BG = (5, 16, 36)
WHITE = (235, 246, 255)
MUTED = (154, 181, 204)
CYAN = (35, 211, 242)
VIOLET = (137, 109, 255)
GOLD = (239, 183, 75)
CARD = (10, 31, 57)


def font(size: int, bold: bool = False):
    name = "/System/Library/Fonts/SFNS.ttf"
    if not Path(name).exists():
        name = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(name, size)


def rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def architecture():
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw.text((72, 48), "AI World OS", font=font(54, True), fill=WHITE)
    draw.text((74, 116), "Load a world. Configure an LLM. Let agents work toward a goal.", font=font(27), fill=MUTED)

    layers = [
        ("SCENARIO PACK", "Goal · Resources · Rules · Tools", (31, 56, 112), VIOLET),
        ("OS RUNTIME", "Observe → Plan → Act → Settle", (8, 52, 78), CYAN),
        ("EVIDENCE + REPLAY", "Every path stays visible and verifiable", (48, 44, 72), GOLD),
    ]
    y = 218
    for i, (label, detail, fill, accent) in enumerate(layers):
        rounded(draw, (100, y, 1500, y + 142), 28, fill, accent, 3)
        draw.ellipse((130, y + 39, 166, y + 75), fill=accent)
        draw.text((198, y + 28), label, font=font(30, True), fill=WHITE)
        draw.text((198, y + 82), detail, font=font(26), fill=(207, 226, 240))
        if i < len(layers) - 1:
            draw.line((800, y + 142, 800, y + 182), fill=CYAN, width=5)
            draw.polygon([(788, y + 176), (812, y + 176), (800, y + 194)], fill=CYAN)
        y += 184

    draw.text((100, 820), "One runtime for capital markets, city governance, drug discovery, logistics, robotics — or your own domain.", font=font(22), fill=MUTED)
    image.save(OUT / "ai-world-os-architecture.png", optimize=True)


def decision_chain():
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw.text((72, 48), "From a question to a settled outcome", font=font(50, True), fill=WHITE)
    draw.text((74, 114), "AI World OS makes the full decision path visible — not just the final answer.", font=font(27), fill=MUTED)
    steps = [
        ("01", "DEFINE", "Goal + constraints", VIOLET),
        ("02", "OBSERVE", "Evidence + tools", CYAN),
        ("03", "COMPETE", "Multiple agent paths", GOLD),
        ("04", "ACT", "Structured world actions", CYAN),
        ("05", "SETTLE", "Authoritative outcome", GOLD),
        ("06", "REPLAY", "Evidence you can inspect", VIOLET),
    ]
    x0, gap, card_w, card_h = 78, 18, 230, 310
    for i, (num, title, detail, accent) in enumerate(steps):
        x = x0 + i * (card_w + gap)
        rounded(draw, (x, 242, x + card_w, 242 + card_h), 24, CARD, accent, 3)
        draw.text((x + 24, 268), num, font=font(32, True), fill=accent)
        draw.text((x + 24, 330), title, font=font(28, True), fill=WHITE)
        draw.multiline_text((x + 24, 406), detail, font=font(23), fill=(195, 218, 235), spacing=9)
        if i < len(steps) - 1:
            ax = x + card_w + 4
            draw.line((ax, 397, ax + gap - 8, 397), fill=CYAN, width=4)
            draw.polygon([(ax + gap - 12, 388), (ax + gap - 12, 406), (ax + gap - 2, 397)], fill=CYAN)

    rounded(draw, (220, 650, 1380, 800), 24, (12, 39, 58), CYAN, 2)
    draw.text((270, 684), "The output is more than a transcript:", font=font(27, True), fill=WHITE)
    draw.text((270, 738), "a replayable chain of evidence → actions → consequences → outcome.", font=font(27), fill=CYAN)
    image.save(OUT / "ai-world-os-decision-chain.png", optimize=True)


if __name__ == "__main__":
    architecture()
    decision_chain()
