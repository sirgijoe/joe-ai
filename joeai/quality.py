"""Quality vs speed: one Low / Medium / High choice each for writing, pictures and video
(Setup > Writing, Setup > Images & video). Low = fastest, rougher results. High = best results, takes longest.
Medium = the balance for daytime use. High is the default (Joe mostly runs overnight). Everything here is plain numbers handed to the
models; nothing is downloaded or installed from this module.
"""
from __future__ import annotations

from dataclasses import dataclass

LEVELS = ("low", "medium", "high")
NAMES = {"low": "Low (fastest)", "medium": "Medium (balanced)", "high": "High (best, slowest)"}


def level(settings, kind: str) -> str:
    v = str(getattr(getattr(settings, "quality", None), kind, "high") or "high").lower()
    return v if v in LEVELS else "high"


# --------------------------------------------------------------------------- writing
@dataclass
class WritingPlan:
    smaller_model: bool      # use the next smaller installed writing model
    think: bool              # let the model think before it writes (better, much slower)

    def describe(self) -> str:
        return ("a smaller, quicker model" if self.smaller_model else "the best model for this PC") + \
               (", thinking first" if self.think else "")


def writing(settings) -> WritingPlan:
    lv = level(settings, "writing")
    return WritingPlan(smaller_model=lv == "low", think=lv == "high")


# --------------------------------------------------------------------------- pictures
@dataclass
class PicturePlan:
    steps_sdxl: int
    steps_sd15: int
    sampler: str
    scale: float             # of the model's normal picture size (only when the task gives no SIZE)

    def steps(self, family: str) -> int:
        return self.steps_sd15 if family == "sd15" else self.steps_sdxl

    def size(self, w: int, h: int) -> tuple[int, int]:
        if self.scale == 1:
            return w, h
        r = lambda v: max(512, int(v * self.scale) // 64 * 64)   # noqa: E731  (models want /64)
        return r(w), r(h)


PICTURES = {
    "low": PicturePlan(14, 15, "dpmpp_2m", 0.8),
    "medium": PicturePlan(28, 25, "dpmpp_2m", 1.0),
    "high": PicturePlan(40, 35, "dpmpp_2m_sde", 1.0),
}


def pictures(settings) -> PicturePlan:
    return PICTURES[level(settings, "pictures")]


# --------------------------------------------------------------------------- video
@dataclass
class VideoPlan:
    size: tuple[int, int]
    frames: int              # Wan makes 24 per second: 121 = about 5 s
    steps: int
    cfg: float
    turbo: bool              # the Turbo add-on (4 steps) is used

    def describe(self) -> str:
        secs = round((self.frames - 1) / 24)
        return (f"{'Turbo, ' if self.turbo else ''}{self.steps} steps, {self.size[0]}x{self.size[1]}, "
                f"about {secs} s")


def video(settings, turbo_installed: bool) -> VideoPlan:
    lv = level(settings, "video")
    if lv == "high":
        return VideoPlan((1280, 704), 121, 30, 5.0, False)
    if lv == "medium":
        if turbo_installed:
            return VideoPlan((1280, 704), 121, 4, 1.0, True)
        return VideoPlan((1280, 704), 121, 20, 5.0, False)
    if turbo_installed:                                   # low
        return VideoPlan((960, 544), 73, 4, 1.0, True)
    return VideoPlan((960, 544), 73, 12, 5.0, False)
