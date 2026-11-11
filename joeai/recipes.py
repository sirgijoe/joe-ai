"""Recipe scaling and substitutions for the Budget meal planner (2.3).

Give the meal planner a recipe (a file, or pasted into the box) and say "double it", "half", "for 10
people" or "x3": Joe scales every amount himself (fractions, mixed numbers, ranges, 1/2 tsp -> 1 tsp),
no AI guessing. Say what you're out of or what to avoid ("no eggs", "out of buttermilk", "dairy-free")
and he lists swaps from his own table of common kitchen substitutions; nothing is made up, and a
swap that changes a recipe a lot says so.
"""
from __future__ import annotations

import re
from fractions import Fraction

_UNICODE = {"½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8"}
_NUM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
_QTY = re.compile(r"^(\s*(?:[-*•]\s+|\d+[.)]\s+)?)(" + _NUM + r")(?:\s*(?:-|to|–)\s*(" + _NUM + r"))?(?=\s|[a-zA-Z])")
_SERVES = re.compile(r"(?im)^\s*(?:serves|servings?|makes|yields?)\s*:?\s*(\d{1,3})\b")
_UNITS = r"(?:cups?|c\.|tablespoons?|tbsps?|tbs|tsps?|teaspoons?|oz|ounces?|lbs?|pounds?|g|grams?|kg|ml|l|liters?|litres?|cans?|cloves?|pinch(?:es)?|sticks?|slices?|eggs?)"
_ING_LINE = re.compile(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)?" + _NUM + r"\s*(?:-\s*" + _NUM + r")?\s*(?:" + _UNITS + r")?\b", re.I)


def _norm(text: str) -> str:
    for k, v in _UNICODE.items():
        text = re.sub(r"(\d)" + k, r"\1 " + v, text).replace(k, v)
    return text


def _frac(s: str) -> Fraction:
    s = s.strip()
    if " " in s:
        a, b = s.split(None, 1)
        return Fraction(a) + Fraction(b)
    return Fraction(s)


def nice(q: Fraction) -> str:
    """3/2 -> '1 1/2', 0.333.. -> '1/3', 2.5 -> '2 1/2': kitchen numbers (nearest 1/8, or 1/3s)."""
    if q <= 0:
        return "0"
    best = min((Fraction(round(q * d), d) for d in (8, 3)), key=lambda f: abs(f - q))
    whole, rest = divmod(best, 1)
    whole = int(whole)
    if rest == 0:
        return str(whole)
    r = f"{rest.numerator}/{rest.denominator}"
    return f"{whole} {r}" if whole else r


def is_ingredient(line: str) -> bool:
    return bool(_ING_LINE.match(_norm(line)))


def scale_line(line: str, factor: Fraction) -> str:
    t = _norm(line)
    m = _QTY.match(t)
    if not m or not is_ingredient(t):
        return line
    a = nice(_frac(m.group(2)) * factor)
    b = f"-{nice(_frac(m.group(3)) * factor)}" if m.group(3) else ""
    return m.group(1) + a + b + t[m.end():]


def serves(text: str) -> int | None:
    m = _SERVES.search(text or "")
    return int(m.group(1)) if m else None


def factor_from(wish: str, recipe_serves: int | None) -> Fraction | None:
    w = (wish or "").lower()
    for word, f in (("double", 2), ("twice", 2), ("triple", 3), ("quadruple", 4), ("half", Fraction(1, 2)),
                    ("halve", Fraction(1, 2))):
        if re.search(r"\b" + word, w):
            return Fraction(f)
    m = re.search(r"\b(?:x|times)\s*(\d+(?:\.\d+)?)\b|\b(\d+(?:\.\d+)?)\s*x\b", w)
    if m:
        return Fraction(m.group(1) or m.group(2)).limit_denominator(8)
    m = re.search(r"\b(?:for|feed|serves?|scale (?:it )?to|make it for)\s+(\d{1,3})\s*(?:people|persons|servings?|of us|kids|guests)?\b", w)
    if m and recipe_serves:
        return Fraction(int(m.group(1)), recipe_serves)
    return None


def wants_scaling(wish: str) -> bool:
    return bool(re.search(r"\b(double|twice|triple|quadruple|half|halve|scale|x\s*\d|\d\s*x\b|times\s+\d)", wish or "", re.I))


def scale_recipe(text: str, factor: Fraction) -> str:
    out = []
    for ln in (text or "").splitlines():
        m = _SERVES.match(ln)
        if m and len(ln) < 60:                                       # "Serves 4" -> "Serves 8"
            n = round(int(m.group(1)) * factor)
            out.append(ln[:m.start(1)] + str(max(1, n)) + ln[m.end(1):])
            continue
        out.append(scale_line(ln, factor))
    return "\n".join(out)


# ingredient words -> (swap, note). Common, well-known kitchen swaps only.
SUBS = [
    (r"\beggs?\b", "for each egg: 1 tbsp ground flaxseed + 3 tbsp water (rest 5 minutes), or 1/4 cup applesauce",
     "fine in muffins, pancakes and cakes; not for omelets or meringue"),
    (r"\bbuttermilk\b", "for each cup: 1 cup milk + 1 tbsp lemon juice or white vinegar (rest 5 minutes)", ""),
    (r"\bbutter\b", "the same amount of margarine, or 3/4 as much vegetable oil", "oil makes baked things a little denser"),
    (r"\bmilk\b", "the same amount of oat, soy or almond milk, or 1/2 water + 1/2 evaporated milk", ""),
    (r"\bsour cream\b", "the same amount of plain yogurt", ""),
    (r"\bheavy cream\b|\bdouble cream\b", "for each cup: 3/4 cup milk + 1/4 cup melted butter (not for whipping)", ""),
    (r"\bbrown sugar\b", "for each cup: 1 cup white sugar + 1 tbsp molasses", ""),
    (r"\bself[- ]rising flour\b|\bself[- ]raising flour\b", "for each cup: 1 cup plain flour + 1 1/2 tsp baking powder + 1/4 tsp salt", ""),
    (r"\bbaking powder\b", "for each tsp: 1/4 tsp baking soda + 1/2 tsp cream of tartar", ""),
    (r"\bcornstarch\b|\bcorn starch\b", "for each tbsp: 2 tbsp plain flour", "a little cloudier sauce"),
    (r"\bbreadcrumbs?\b", "the same amount of crushed crackers or quick oats", ""),
    (r"\bfresh herbs?\b|\bfresh (?:basil|parsley|oregano|thyme)\b", "1/3 as much of the dried herb", ""),
    (r"\bgarlic cloves?\b|\bcloves? (?:of )?garlic\b", "for each clove: 1/8 tsp garlic powder", ""),
    (r"\bonion\b", "for each medium onion: 1 tbsp onion powder", "no crunch"),
    (r"\bwine\b", "the same amount of broth + 1 tsp vinegar per cup", ""),
    (r"\bhoney\b", "the same amount of maple syrup or golden syrup", "honey isn't for babies under 1 anyway"),
    (r"\bground beef\b|\bmince\b", "the same weight of ground turkey, or half the meat + cooked lentils", "cheaper with lentils"),
    (r"\bbroth\b|\bstock\b", "water + a bouillon cube (1 per 2 cups)", ""),
    (r"\bcheddar\b|\bcheese\b", "any melting cheese you have; dairy-free: nutritional yeast for flavor", ""),
    (r"\blemon juice\b", "the same amount of white vinegar (for acid; not for flavor)", ""),
]
_AVOID = {"egg": r"\beggs?\b", "eggs": r"\beggs?\b", "dairy": r"\b(?:milk|butter|cream|cheese|cheddar|yogurt|buttermilk)\b",
          "milk": r"\bmilk\b", "butter": r"\bbutter\b", "buttermilk": r"\bbuttermilk\b", "wine": r"\bwine\b",
          "cream": r"\bcream\b", "cheese": r"\b(?:cheese|cheddar)\b", "onion": r"\bonions?\b", "garlic": r"\bgarlic\b",
          "honey": r"\bhoney\b", "beef": r"\b(?:ground beef|mince)\b", "meat": r"\b(?:ground beef|mince)\b"}


def wanted_swaps(wish: str) -> list[str]:
    """'no eggs', 'out of buttermilk', 'dairy-free', 'without wine' -> ['egg', 'buttermilk', 'dairy', 'wine']."""
    w = (wish or "").lower()
    found = []
    for m in re.finditer(r"\b(?:no|without|out of|ran out of|instead of|swap|replace|free of|allergic to|can't have|cannot have)\s+"
                         r"([a-z]+(?:\s[a-z]+)?)|\b([a-z]+)[- ]free\b", w):
        word = (m.group(1) or m.group(2) or "").split()[0]
        if word in _AVOID and word not in found:
            found.append(word)
    return found


def substitutions(recipe: str, avoid: list[str]) -> list[tuple[str, str, str]]:
    """(ingredient line, swap, note) for each recipe line holding something to avoid. Lines Joe has no
    swap for come back with swap '' (the caller marks them [CHECK])."""
    rows = []
    for ln in (recipe or "").splitlines():
        if not is_ingredient(ln):
            continue
        low = ln.lower()
        if not any(re.search(_AVOID[a], low) for a in avoid if a in _AVOID):
            continue
        swap = next(((s, n) for rx, s, n in SUBS if re.search(rx, low)), ("", ""))
        rows.append((ln.strip(" -*•"), swap[0], swap[1]))
    return rows


def recipe_text(files_text: str, wish: str) -> str:
    """The recipe: a file, or one pasted into the box (3+ ingredient lines)."""
    for src in (files_text, wish):
        lines = [ln for ln in (src or "").splitlines() if is_ingredient(ln)]
        if len(lines) >= 3:
            return src
    return ""


def make(recipe: str, wish: str) -> str | None:
    """The scaled / swapped recipe as Markdown, or None when this isn't a recipe request."""
    avoid = wanted_swaps(wish)
    if not recipe or not (wants_scaling(wish) or avoid or factor_from(wish, serves(recipe))):
        return None
    factor = factor_from(wish, serves(recipe))
    body = scale_recipe(recipe, factor) if factor and factor != 1 else recipe
    L = []
    if factor and factor != 1:
        was = serves(recipe)
        L += [f"# Recipe, scaled x{nice(factor)}" + (f" (serves {round(was * factor)} instead of {was})" if was else ""), "",
              "Joe changed every amount himself. Baking times stay about the same for the same pan; a bigger "
              "batch in a bigger pan may need a few more minutes. Spices and salt: add the scaled amount a "
              "little at a time and taste.", ""]
    else:
        L += ["# Recipe", ""]
    L += [body.strip(), ""]
    if avoid:
        rows = substitutions(body, avoid)
        L += ["## Swaps", ""]
        if not rows:
            L += [f"Nothing in this recipe needs swapping for: {', '.join(avoid)}.", ""]
        for line, swap, note in rows:
            L.append(f"- **{line}**: " + (swap + (f" ({note})" if note else "") if swap else
                                         "Joe has no tried-and-true swap for this one [CHECK]"))
        L.append("")
    return "\n".join(L)
