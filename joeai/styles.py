"""Picture styles: Joe picks a way of drawing that fits the request (a photo, a flat
illustration, a mascot, a product shot, a coloring page) and uses it for three things:
which installed checkpoint draws it, what the prompt writer is told, and what is left out.

A task can say which one with STYLE: one of NAMES (photo, anime, painting, concept, render3d,
scifi, cartoon, pixel, surreal, illustration, character, product, coloring, general).
Without it Joe guesses from the task's name and brief. Which checkpoints suit each style is
matched by words in their file names; the lists live in model_picks.json ("styles"), so they
can be changed on GitHub without a new version. Nothing here downloads anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

NAMES = ("general", "photo", "anime", "painting", "concept", "render3d", "scifi", "cartoon", "pixel",
         "surreal", "illustration", "character", "product", "coloring")

# words in a checkpoint's file name -> good for that style (first match wins)
PHOTO_HINTS = ["juggernaut", "realvis", "realism", "realistic", "epicrealism", "photon", "absolutereality",
               "cyberrealistic", "dirtymoss", "photo"]
ART_HINTS = ["illustr", "anime", "animagine", "toon", "cartoon", "flat", "vector", "pony", "counterfeit",
             "dreamshaper", "meina", "aam", "comic"]
ANIME_HINTS = ["animagine", "anime", "pony", "meina", "counterfeit", "aam", "illustr"]
TOON_HINTS = ["toon", "cartoon", "comic", "flat", "vector", "dreamshaper", "illustr"]
PAINT_HINTS = ["dreamshaper", "paint", "art", "illustr", "sdxl_base", "sd_xl_base"]
DEFAULT_HINTS = {"photo": PHOTO_HINTS, "product": PHOTO_HINTS, "illustration": ART_HINTS,
                 "character": ART_HINTS, "coloring": ART_HINTS, "anime": ANIME_HINTS, "cartoon": TOON_HINTS,
                 "painting": PAINT_HINTS, "concept": PAINT_HINTS, "surreal": PAINT_HINTS,
                 "pixel": ["pixel"] + TOON_HINTS, "render3d": ["3d", "render", "dreamshaper", "juggernaut"],
                 "scifi": ["dreamshaper", "juggernaut", "realvis"]}
# styles that should avoid photo-realism checkpoints when anything else is installed
ART_STYLES = ("illustration", "character", "coloring", "anime", "cartoon", "painting", "pixel")

PHOTO_NOTE = ("STYLE: real photograph. In every prompt name the lens (85mm portrait, 50mm, 35mm, 24mm wide), "
              "where the light comes from (soft window light, overcast daylight, golden hour from the left), "
              "depth of field, and natural texture (skin pores, fabric weave, worn surfaces). Avoid 'perfect', "
              "'flawless', 'well-lit'.")
NEG_PHOTO = ("cartoon, illustration, painting, drawing, anime, 3d render, cgi, plastic skin, airbrushed, "
             "overly smooth, oversaturated, doll")
NEG_ART = "photo, photograph, photorealistic, realistic skin, 3d render, cgi, film grain, lens blur"


@dataclass(frozen=True)
class Style:
    id: str
    label: str
    note: str = ""          # told to the prompt writer
    suffix: str = ""        # added to every prompt
    negative: str = ""      # added to the leave-out list
    cfg: float = 0.0        # nudge to prompt strength: lower = more natural photos, higher = crisper flat art


STYLES = {
    "general": Style("general", "Joe decides"),
    "photo": Style("photo", "Photo", PHOTO_NOTE, "", NEG_PHOTO, cfg=-1.5),
    "anime": Style("anime", "Anime / manga",
                   "STYLE: anime illustration. Cel shading, clean dynamic line work, expressive eyes and "
                   "faces, bold flat color areas, simple soft backgrounds. No camera or lens words.",
                   "anime style, cel shaded, clean line art", NEG_ART + ", western cartoon", cfg=1.0),
    "painting": Style("painting", "Painting (oil, watercolor...)",
                      "STYLE: traditional painting. Name the medium (oil on canvas, watercolor on paper, ink "
                      "wash, gouache) and describe brush strokes, paper or canvas texture and the color mixing. "
                      "No camera or lens words.", "traditional painting, visible brush strokes",
                      "photo, photograph, photorealistic, 3d render, cgi, digital art, smooth plastic look"),
    "concept": Style("concept", "Concept art / digital painting",
                     "STYLE: concept art for a game or film. Strong silhouette, clear sense of scale, "
                     "atmospheric perspective, dramatic but believable lighting, painterly digital brushwork.",
                     "concept art, digital painting", "photo, amateur, flat lighting, clip art"),
    "render3d": Style("render3d", "3D render / CGI",
                      "STYLE: polished 3D render. Describe materials (glossy plastic, brushed metal, soft "
                      "subsurface skin), studio or HDRI lighting, soft global illumination, shallow depth of "
                      "field.", "3d render, octane render, global illumination",
                      "photo, drawing, sketch, painting, flat colors, line art"),
    "scifi": Style("scifi", "Sci-fi / cyberpunk",
                   "STYLE: science fiction. Futuristic technology, neon or cool artificial lights, reflections "
                   "on wet or metal surfaces, haze, strong color contrast (cyan and magenta).",
                   "sci-fi, futuristic, cinematic lighting", "medieval, rustic, old-fashioned"),
    "cartoon": Style("cartoon", "Cartoon / comic",
                     "STYLE: western cartoon or comic art. Bold black outlines, flat bright colors, simple "
                     "exaggerated shapes, optional halftone dots. No camera or lens words.",
                     "cartoon, bold outlines, flat colors", NEG_ART + ", anime", cfg=1.0),
    "pixel": Style("pixel", "Pixel art",
                   "STYLE: retro pixel art like a 16-bit video game. Small limited palette, crisp square "
                   "pixels, simple readable shapes, no smooth gradients.",
                   "pixel art, 16-bit, limited palette, crisp pixels",
                   NEG_ART + ", blurry, smooth gradients, soft shading, anti-aliasing, high detail", cfg=1.0),
    "surreal": Style("surreal", "Surreal / abstract",
                     "STYLE: surreal or abstract art. Dreamlike impossible scenes, unexpected scale and "
                     "combinations, or non-representational shapes and color fields; still a clear focal point.",
                     "surreal art, dreamlike", "photo, ordinary, cluttered, low contrast", cfg=0.5),
    "illustration": Style("illustration", "Illustration / flat art",
                          "STYLE: illustration. Describe it as a drawn or painted illustration: simple clear "
                          "shapes, clean outlines, a limited color palette, soft even light. No camera or lens "
                          "words.", "illustration, clean shapes", NEG_ART),
    "character": Style("character", "Mascot / character",
                       "STYLE: character design. One character, full body, plain light background, the same "
                       "design in every prompt (repeat its colors and features exactly), friendly simple "
                       "shapes, clean outlines. No camera or lens words.",
                       "character design, full body, plain background",
                       NEG_ART + ", busy background, multiple characters, crowd"),
    "product": Style("product", "Product shot",
                     "STYLE: studio product photo. The item alone, centered, on a clean seamless background, "
                     "softbox lighting with a gentle shadow, sharp focus, 70-100mm lens, true colors.",
                     "studio product photo, seamless background",
                     NEG_PHOTO + ", clutter, hands, people", cfg=-1.0),
    "coloring": Style("coloring", "Coloring page",
                      "STYLE: coloring-book page. Black outlines on white only: thick clean lines, large "
                      "simple areas to color, no shading, no gray, no color, no texture.",
                      "black and white line art, coloring book page, thick clean outlines, white background, "
                      "no shading",
                      "color, colored, shading, shadows, gray, grayscale, gradient, texture, photo, "
                      "realistic, filled areas", cfg=1.0),
}

# the style with the most matching words wins (ties: the earlier one here)
_WORDS = [
    ("coloring", r"colou?ring|line ?art|outline drawing"),
    ("character", r"mascot|character sheet|character design|sticker"),
    ("product", r"product (?:shot|photo|picture)|packshot|listing photo|studio shot"),
    ("pixel", r"pixel ?art|\b(?:8|16)[- ]bit\b|sprite"),
    ("anime", r"\banime\b|manga|cel[- ]shad\w*"),
    ("render3d", r"\b3d\b|octane|unreal engine|\bcgi\b|blender render"),
    ("scifi", r"sci[- ]?fi|cyberpunk|futuristic|\bneon\b|spaceship"),
    ("concept", r"concept art|digital painting|matte painting|fantasy (?:art|landscape)"),
    ("painting", r"oil painting|watercolou?r|ink wash|gouache|impressionis\w*|renaissance|cubis\w*|"
                 r"\bpainted\b|on canvas"),
    ("surreal", r"surreal\w*|\babstract\b|dreamlike"),
    ("cartoon", r"cartoon|\bcomic\w*|halftone"),
    ("photo", r"\bphoto(?:s|graph\w*|real\w*)?\b|realistic|real[- ]life|portrait|candid|\bdslr\b|bokeh"),
    ("illustration", r"illustrat\w*|\bflat\b|vector|drawing|clip ?art|storybook|children'?s book|"
                     r"\bicons?\b"),
]


# Only when the task says the pictures are for children: everyone fully clothed, nothing
# suggestive. Nothing is filtered otherwise (not every coloring book is for kids).
KIDS = re.compile(r"\b(?:kids?|child(?:ren|'s)?|toddlers?|preschool\w*|kindergarten|nursery|"
                  r"family[- ]friendly|for (?:my )?(?:son|daughter|grandkids?)|baby|babies|young readers)\b", re.I)
KID_NOTE = ("FOR CHILDREN: everything is family-friendly. Every person or creature is fully clothed or "
            "covered (a mermaid wears a shell top), nothing scary, violent or suggestive.")
KID_NEGATIVE = "(nsfw, nude, naked, topless, nipples, cleavage, lingerie, underwear, sexy, suggestive, gore:1.4)"


def for_kids(job) -> bool:
    return bool(KIDS.search(f"{getattr(job, 'name', '')}\n{getattr(job, 'format', '')}\n"
                            f"{getattr(job, 'rules', '')}"))


def valid(name: str) -> bool:
    return (name or "").strip().lower() in NAMES


def pick(job) -> Style:
    """The task's STYLE, else a guess from its name and brief (general when nothing fits)."""
    s = (getattr(job, "style", "") or "").strip().lower()
    if s in STYLES:
        return STYLES[s]
    text = f"{getattr(job, 'name', '')}\n{getattr(job, 'format', '')}".lower()
    best, most = "general", 0
    for sid, pat in _WORDS:                    # most matching words wins; ties go to the earlier style
        n = len(re.findall(pat, text))
        if n > most:
            best, most = sid, n
    return STYLES[best]


def hints(style: str, picks: dict | None = None) -> list[str]:
    """Checkpoint-name words for a style: model_picks.json's "styles" when it has them."""
    got = ((picks or {}).get("styles") or {}).get(style)
    if isinstance(got, list) and got and all(isinstance(x, str) and 0 < len(x) <= 40 for x in got):
        return [x.lower() for x in got]
    return DEFAULT_HINTS.get(style, [])


def choose_model(models: list, style: str, picks: dict | None = None):
    """The installed checkpoints that suit `style` (hint order = preference), or [] when none
    match (then Joe picks as before). Photo/product never fall back to art models and the
    reverse: an art style avoids photo-realism checkpoints when anything else is installed."""
    h = hints(style, picks)
    if not h:
        return []
    for word in h:
        hit = [m for m in models if word in m.name.lower()]
        if hit:
            return hit
    if style in ART_STYLES:
        rest = [m for m in models if not any(w in m.name.lower() for w in hints("photo", picks))]
        return rest if rest and len(rest) < len(models) else []
    return []


def add(prompt: str, style: Style) -> str:
    return f"{prompt.rstrip(' .,')}, {style.suffix}" if style.suffix else prompt
