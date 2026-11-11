"""Joe's tools: ready-made jobs that work on the person's own files (recordings, photos,
documents) instead of writing from scratch.

Every tool is reached three ways, all running the same code here:
  1. Just ask: the "What do you need?" box writes `TYPE: <tool id>` tasks (describe.py).
  2. The Tools tab (F3): a card per tool opens a short form (drop files, pick options, RUN).
  3. Missions: `TASK: Meeting notes  TYPE: transcribe  INPUT: tools/meeting.mp3`.

A tool task reads its files from Inbox (INPUT: files or folders), saves into a folder under
Output, and resumes file by file if a run stops. OPTIONS picks extras (comma-separated).

The registry below also lists planned tools so the Tools tab can show what's coming; only
tools with `ready=True` can run.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .fsutil import atomic_write_text
from .items import count_words, find_flags

if TYPE_CHECKING:                                    # pragma: no cover
    from .engine import Engine, JobState
    from .mission import Job, Mission

AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wma", ".amr")
VIDEO_IN_EXT = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv", ".3gp")
SHEET_EXT = (".csv", ".tsv", ".xlsx")
DOC_EXT = (".txt", ".md", ".markdown", ".docx", ".pdf", ".html", ".htm")
VISION_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")
VISION_HELP_TEXT = ("Uses a vision model on this PC (Setup > System check offers a free one). Big "
                    "photos are shrunk first with FFmpeg. Your pictures never leave this computer "
                    "and are never changed.")
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")
TEXT_DOC_EXT = (".txt", ".md", ".markdown", ".docx", ".pdf", ".html", ".htm")
LANGUAGES = (("spanish", "Spanish"), ("french", "French"), ("german", "German"),
             ("italian", "Italian"), ("portuguese", "Portuguese"), ("dutch", "Dutch"),
             ("polish", "Polish"), ("russian", "Russian"), ("ukrainian", "Ukrainian"),
             ("greek", "Greek"), ("turkish", "Turkish"), ("arabic", "Arabic"), ("hebrew", "Hebrew"),
             ("hindi", "Hindi"), ("bengali", "Bengali"), ("chinese", "Chinese (Simplified)"),
             ("japanese", "Japanese"), ("korean", "Korean"), ("vietnamese", "Vietnamese"),
             ("thai", "Thai"), ("indonesian", "Indonesian"), ("tagalog", "Tagalog"),
             ("swahili", "Swahili"), ("english", "English"))
# Whisper's code for each language Joe lists (Transcribe can hear all of these).
WHISPER_CODES = {"spanish": "es", "french": "fr", "german": "de", "italian": "it",
                 "portuguese": "pt", "dutch": "nl", "polish": "pl", "russian": "ru",
                 "ukrainian": "uk", "greek": "el", "turkish": "tr", "arabic": "ar", "hebrew": "he",
                 "hindi": "hi", "bengali": "bn", "chinese": "zh", "japanese": "ja", "korean": "ko",
                 "vietnamese": "vi", "thai": "th", "indonesian": "id", "tagalog": "tl",
                 "swahili": "sw", "english": "en"}
HEAR_LANGUAGES = (("english", "English"), ("auto", "Find out by itself")) + tuple(
    (v, n) for v, n in LANGUAGES if v != "english")
COMFY_PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp")     # what ComfyUI's LoadImage reads
VIDEO_TOOL_EXT = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
UPLOAD_MAX_BYTES = 8 * 1024 ** 3                  # 8 GB per file for the Tools form


@dataclass(frozen=True)
class Option:
    """A tick box (OPTIONS: subtitles), or with `choices` a pick-one list written as
    'key value' (OPTIONS: size 1600). `value` is the choice used when nothing is said."""
    key: str
    label: str
    default: bool = True
    hint: str = ""
    choices: tuple[tuple[str, str], ...] = ()       # (value, plain label)
    value: str = ""
    multi: bool = False                              # several picks allowed ("to spanish, to french")
    required: bool = False                           # at least one pick needed (no default)


@dataclass(frozen=True)
class Tool:
    id: str
    name: str                   # card title, plain words
    group: str                  # Writing | Pictures | Video | Audio | Files
    blurb: str                  # one line on the card
    accepts: tuple[str, ...] = ()
    options: tuple[Option, ...] = ()
    needs: tuple[str, ...] = ()          # voice | ollama | ffmpeg | comfy | vision
    ready: bool = False
    help: str = ""                       # shown in the form
    plan_hint: str = ""                  # one line for the describe planner
    examples: tuple[str, ...] = field(default_factory=tuple)
    extra_hint: str = ""                 # placeholder for the form's "Anything else?" box
    mark: bool = False                   # takes WATERMARK: (text or a logo .png), only if asked
    extra_label: str = ""                # the form's "Anything else?" box, named for this tool


from .makers import LOOKS, NO_INPUT_OK, PATTERNS as ILLUSION_PATTERNS  # noqa: E402  (batch 3 tools' choices)
from .writetools import CODE_EXT  # noqa: E402
from .avtools import SIZES as SOCIAL_SIZES  # noqa: E402
from .i18n import LANGUAGES as UI_LANGUAGES  # noqa: E402  (Joe's own screens)

# light name -> (label, words for the editor)
RELIGHTS = {
    "golden": ("Golden hour", "warm golden-hour sunlight low from the side, long soft shadows"),
    "studio": ("Studio", "clean, even studio lighting with a soft key light and gentle fill"),
    "soft": ("Soft window light", "soft, diffused window light"),
    "night": ("Night", "night time: cool moonlight with warm lamp light"),
    "dramatic": ("Dramatic", "dramatic side light with deep shadows and strong contrast"),
    "candle": ("Candlelight", "warm, flickering candlelight glow"),
    "overcast": ("Cloudy day", "even, soft overcast daylight with no harsh shadows"),
}
# style name -> (label, words for the editor)
RESTYLES = {
    "watercolor": ("Watercolor", "a soft watercolor painting on textured paper"),
    "oil": ("Oil painting", "a classic oil painting with visible brush strokes"),
    "sketch": ("Pencil sketch", "a detailed graphite pencil sketch on white paper"),
    "anime": ("Anime", "a clean anime illustration with cel shading"),
    "comic": ("Comic book", "a comic book panel with bold ink lines and flat colors"),
    "cartoon": ("3D cartoon", "a cute 3D animated movie style render"),
    "pixel": ("Pixel art", "detailed 16-bit pixel art"),
    "stained": ("Stained glass", "a stained glass window with dark lead lines"),
    "vintage": ("Old photo", "a faded vintage photograph from the 1960s"),
    "coloring": ("Coloring page", "a black and white coloring page with clean outlines, no shading"),
    "picture": ("Like my last picture", ""),
}


TOOLS: dict[str, Tool] = {t.id: t for t in (
    Tool("transcribe", "Transcribe a recording", "Audio",
         "Turn audio or video into text, subtitles and short notes.",
         accepts=AUDIO_EXT + VIDEO_IN_EXT,
         options=(Option("subtitles", "Subtitles file (.srt)", True,
                         "For video players and YouTube."),
                  Option("notes", "Notes: summary, key points, to-dos", True,
                         "Written by the writing model from the transcript."),
                  Option("language", "Spoken in", hint="Pick the language if you know it: that's "
                         "faster and more accurate than letting Joe find out.",
                         choices=HEAR_LANGUAGES, value="english"),
                  Option("notes-in", "Write the notes in",
                         choices=(("same", "The recording's language"), ("english", "English")),
                         value="same")),
         needs=("voice", "ffmpeg"), ready=True,
         help="Uses the Hearing setting (Setup > Voice & Talk): Most accurate is slower but makes "
              "fewer mistakes. Runs on the processor, so it can work while pictures are drawing. "
              "Roughly real time on Balanced. Other languages use Whisper's all-languages "
              "model: the first time, Joe downloads it once from Hugging Face (about 75-480 MB, "
              "only the model, never your recording). Big languages are heard best; check "
              "names and numbers.",
         plan_hint="Transcribe: TYPE: transcribe, INPUT: the recording file(s) from the list "
                   "below, OPTIONS: subtitles, notes (leave out what they don't want), plus "
                   "language <name> when it isn't English (language auto if they don't know; "
                   "names: " + ", ".join(v for v, _ in HEAR_LANGUAGES[2:]) + ") and notes-in "
                   "english if they want English notes from another language. No CHUNKS.",
         examples=("Turn my meeting recording into notes", "Make subtitles for this video")),
    Tool("read-aloud", "Read a document aloud", "Audio",
         "Turn writing into an MP3 you can listen to.",
         accepts=DOC_EXT,
         options=(Option("chapters", "One track per chapter", False,
                         "Splits at headings like '# Title' or 'Chapter 3'. Handy for long documents."),),
         needs=("voice", "ffmpeg"), ready=True,
         help="Uses Joe's voice and speed from Setup > Voice & Talk (your own copied voice isn't "
              "used here yet). Runs on the processor, so it can work while pictures are drawing. "
              "Without FFmpeg Joe saves WAV files (much bigger) instead of MP3. Reading PDFs needs "
              "Joe's voice add-on. Long books take a while: a stopped run picks up where it left off.",
         plan_hint="Read aloud (document -> MP3): TYPE: read-aloud, INPUT: the document file(s) "
                   "from the list below, OPTIONS: chapters (only if they want one track per "
                   "chapter, else none). No CHUNKS.",
         examples=("Read my short story aloud as an MP3", "Turn this guide into an audiobook"),
         extra_hint="optional, e.g. skip the table of contents"),
    Tool("find-book", "Find a book to read aloud", "Audio",
         "By ISBN, title or a photo of the cover: free public-domain books downloaded and read aloud.",
         accepts=PHOTO_EXT,
         options=(Option("aloud", "Then read it aloud", choices=(("yes", "Yes, queue Read aloud"), ("no", "No, just get it")),
                         value="yes"),),
         needs=(), ready=True,
         help="Type the ISBN or the title (and author) in the box, or add a photo of the cover or the barcode. "
              "Joe looks it up in Open Library; if it's in the public domain and Project Gutenberg has it, he "
              "downloads the text and queues Read a document aloud. Books still under copyright can't be "
              "downloaded: scan your own copy's pages (Read scans and receipts) and Joe reads those. Needs online "
              "lookups on (Setup > Voice & Talk); only the ISBN or title is sent.",
         plan_hint="Find / download / read aloud a book by ISBN, title or cover photo: TYPE: find-book, FORMAT: the "
                   "ISBN or title and author, word for word, OPTIONS: aloud yes|no. INPUT only a cover/barcode photo "
                   "they point at. No CHUNKS.",
         examples=("Read me Pride and Prejudice", "Find the book with ISBN 978-0-14-143951-8"),
         extra_hint="e.g. Pride and Prejudice, Jane Austen  or  978-0-14-143951-8",
         extra_label="ISBN or title"),
    Tool("memory-voice", "Hear it in a loved one's voice", "Audio",
         "A letter, story or note read in the voice of someone you miss, made from family recordings.",
         accepts=DOC_EXT,
         needs=("ffmpeg",), ready=True,
         help="First make the voice in Setup > Voice & Talk > A voice to remember: add a family recording of them "
              "talking (a few clear seconds are enough) and tick the three promises. Then type their name in the box "
              "here. Everything stays on this PC. Each recording comes with a note saying it was made by AI, and the "
              "voice program hides an inaudible watermark that marks it as AI-made. Needs the voice-copy add-on "
              "(NVIDIA card).",
         plan_hint="Read a document in a loved one's (copied) voice: TYPE: memory-voice, INPUT: the document, FORMAT: "
                   "whose voice, word for word (the name they gave it). No CHUNKS.",
         examples=("Read my letter in Grandpa's voice",),
         extra_hint="the name you gave the voice, e.g. Grandpa",
         extra_label="Whose voice"),
    Tool("proofread", "Proofread my writing", "Writing",
         "Fix spelling and grammar, with a list of every change.",
         accepts=DOC_EXT,
         options=(Option("clarity", "Also suggest clearer wording", False,
                         "Off: only real mistakes (spelling, grammar, punctuation). On: also "
                         "awkward or unclear sentences."),
                  Option("copy", "Corrected copy", True,
                         "A fixed copy next to the change list. Your original file is never changed.")),
         needs=("ollama",), ready=True,
         help="Joe lists every change with the before and after, so nothing is changed silently, "
              "and your original file is never touched. Word files come back as a text copy "
              "(plus a Word copy if Pandoc is installed); formatting like fonts isn't kept. "
              "Reading PDFs needs Joe's voice add-on.",
         plan_hint="Proofread (spelling/grammar with a change list): TYPE: proofread, INPUT: the "
                   "document file(s) from the list below, OPTIONS: copy, plus clarity only if "
                   "they want wording suggestions too. No CHUNKS.",
         examples=("Proofread my cover letter", "Check the grammar in my newsletter"),
         extra_hint="optional, e.g. British spelling, keep the casual tone"),
    Tool("translate", "Translate", "Writing",
         "Make a copy of finished text in another language.",
         accepts=DOC_EXT,
         options=(Option("to", "Into", hint="Pick one or more. Each language gets its own copy.",
                         choices=LANGUAGES, multi=True, required=True),),
         needs=("ollama",), ready=True,
         help="Translated by the writing model on this PC, so nothing leaves it. Quality depends "
              "on the model: big languages work best. Anything Joe isn't sure about is marked "
              "[CHECK]. Have someone who speaks the language read it before you publish it. Your "
              "original is never changed. Word files come back as text (plus Word with Pandoc).",
         plan_hint="Translate finished writing: TYPE: translate, INPUT: the document file(s) from "
                   "the list below, OPTIONS: to <language> for each language (e.g. to spanish, to "
                   "french). Languages: " + ", ".join(v for v, _ in LANGUAGES) + ". No CHUNKS.",
         examples=("Translate my menu into Spanish", "Make French and German copies of this flyer"),
         extra_hint="optional, e.g. formal tone, Latin American Spanish"),
    Tool("ask-files", "Ask my files", "Writing",
         "Answers and summaries from a folder of your documents.",
         accepts=DOC_EXT,
         options=(Option("summaries", "A short summary of each document", False,
                         "On its own (no question) Joe just makes the summaries."),),
         needs=("ollama",), ready=True,
         help="Type your question(s) in the box below (one per line, or end each with ?). Joe finds "
              "the parts of your documents that fit and answers only from them, showing which "
              "excerpts he used; if the documents don't say, he says so. Works straight away; a small "
              "search model (Setup > System check, about 270 MB) helps him find the right parts in "
              "big folders. Everything stays on this computer.",
         plan_hint="Questions about / summaries of the person's documents: TYPE: ask-files, INPUT: the "
                   "document file(s) or folder from the list below, FORMAT: their question(s), one "
                   "per line, word for word, OPTIONS: summaries (only if they want summaries), else "
                   "none. No CHUNKS.",
         examples=("What do my contracts say about cancelling?", "Summarize every document in this folder"),
         extra_hint="e.g. What do these say about refunds? When is each one due?",
         extra_label="Your question(s)"),
    Tool("summarize", "Summarize", "Writing",
         "The key points of an article, PDF, book or web page.",
         accepts=DOC_EXT,
         options=(Option("length", "How", choices=(("short", "Short: one paragraph"),
                                                   ("points", "Key points, names, numbers and to-dos"),
                                                   ("chapters", "Chapter by chapter")), value="points"),),
         needs=("ollama",), ready=True,
         help="Long documents are read in parts and the notes joined into one summary, so even a whole "
              "book works (it just takes longer). Names, numbers and dates are copied as written; "
              "anything unclear is marked [CHECK]. Your file is never changed.",
         plan_hint="Summarize documents: TYPE: summarize, INPUT: the document file(s) from the list below, "
                   "OPTIONS: length short|points|chapters (points if they don't say). No CHUNKS.",
         examples=("Summarize this article", "Give me the key points of my lease", "Summarize this book chapter by chapter"),
         extra_hint="optional, e.g. focus on money and dates"),
    Tool("rewrite", "Rewrite or change the tone", "Writing",
         "Friendlier, more formal, shorter, simpler, an email, or a resume for a job.",
         accepts=DOC_EXT,
         options=(Option("style", "Make it", choices=(("friendly", "Friendlier"), ("formal", "More formal"),
                                                      ("shorter", "Shorter"), ("simpler", "Simpler to read"),
                                                      ("email", "Into an email"),
                                                      ("resume", "A resume tailored to a job post"),
                                                      ("custom", "My own way (say how below)")),
                         value="friendly"),),
         needs=("ollama",), ready=True,
         help="Makes a new copy plus a short 'what changed' list; your original is never touched. Joe "
              "keeps every fact and never adds new ones: for a resume he never invents jobs, skills or "
              "results (missing things are marked [CHECK]). For a resume, paste the job post in the box.",
         plan_hint="Rewrite / change tone / notes into an email / tailor a resume: TYPE: rewrite, INPUT: the "
                   "document file(s), OPTIONS: style friendly|formal|shorter|simpler|email|resume|custom, "
                   "FORMAT: anything they asked for (for a resume: the job post, word for word). No CHUNKS.",
         examples=("Make my email sound friendlier", "Turn my notes into an email", "Tailor my resume to this job post"),
         extra_hint="optional, e.g. paste the job post here, or: sound confident but not pushy",
         extra_label="Anything else? (or the job post)"),
    Tool("brainstorm", "Brainstorm", "Writing",
         "Ideas, names, gift ideas, marketing angles, outlines or ways to solve a problem.",
         accepts=DOC_EXT,
         options=(Option("kind", "What kind", choices=tuple((k, k.capitalize() if k != "gifts" else "Gift ideas")
                                                          for k in ("ideas", "names", "gifts", "angles",
                                                                    "outline", "solutions")), value="ideas"),
                  Option("count", "How many", choices=(("10", "10"), ("25", "25"), ("50", "50")), value="25"),
                  Option("park", "Note it in Ideas.md", False, "Adds one line to Ideas.md pointing at the list.")),
         needs=("ollama",), ready=True,
         help="Say what you need ideas for in the box. A file is optional: add notes or a draft and the "
              "ideas build on it. Like one? Type \"park this: ...\" in Joe's box to keep it.",
         plan_hint="Brainstorm ideas / names / gift ideas / angles / an outline: TYPE: brainstorm, FORMAT: what "
                   "they need ideas for, word for word, OPTIONS: kind ideas|names|gifts|angles|outline|solutions, "
                   "count 10|25|50. INPUT only if they point at a file. No CHUNKS.",
         examples=("Give me 25 names for my bakery", "Gift ideas for my dad who loves fishing",
                   "Outline a blog post about raised garden beds"),
         extra_hint="e.g. names for a pottery shop that sounds warm and handmade",
         extra_label="What do you need ideas for?"),
    Tool("study", "Study helper", "Writing",
         "Explains your material at your level, with flashcards and a practice quiz.",
         accepts=DOC_EXT,
         options=(Option("level", "Explain for", choices=(("kid", "A kid"), ("teen", "A teen"),
                                                          ("adult", "A grown-up, new to it"),
                                                          ("expert", "Someone who knows the basics")),
                         value="adult"),
                  Option("explain", "Explanation", True),
                  Option("cards", "Flashcards (.csv for Anki or Quizlet)", True),
                  Option("quiz", "Practice quiz with answers", True),
                  Option("teach", "Teach me (questions first, try-it tasks)", False,
                         "Makes you think before you read, so you learn it instead of just getting answers.")),
         needs=("ollama",), ready=True,
         help="Uses only your material (class notes, a chapter, a manual), so nothing is made up from "
              "elsewhere; unclear bits are marked [CHECK]. Flashcards come as a Front,Back spreadsheet that "
              "Anki, Quizlet and Excel open.",
         plan_hint="Study help (explain / flashcards / quiz) from the person's material: TYPE: study, INPUT: the "
                   "document file(s), OPTIONS: level kid|teen|adult|expert plus explain, cards, quiz, teach "
                   "(what they asked for). No CHUNKS.",
         examples=("Make flashcards from my biology notes", "Explain this chapter like I'm 10",
                   "Quiz me on this manual")),
    Tool("code-review", "Explain or review my code", "Writing",
         "What your code does, likely bugs with fixes, and tests to add. Joe never runs it.",
         accepts=CODE_EXT,
         options=(Option("explain", "Explain what it does", True),
                  Option("bugs", "Likely bugs and risks, with fixes", True),
                  Option("tests", "Tests to add", False),
                  Option("tidy", "Easy improvements", False)),
         needs=("ollama",), ready=True,
         help="Joe reads the code and writes a review; he never runs it, and your files are never changed. "
              "Line numbers are real, so you can find each spot. Test every suggested fix yourself.",
         plan_hint="Explain or review code: TYPE: code-review, INPUT: the code file(s) or folder, OPTIONS: "
                   "explain, bugs, tests, tidy (what they asked for). No CHUNKS.",
         examples=("Explain what this script does", "Find bugs in my Python file"),
         extra_hint="optional, e.g. it crashes when the list is empty"),
    Tool("ai-search", "Get found by AI search", "Writing",
         "FAQ, website code and llms.txt so AI assistants can describe your business correctly.",
         accepts=DOC_EXT,
         needs=("ollama",), ready=True,
         help="Tell Joe about the business in the box (name, what you do, where, hours, phone, website), or add "
              "your About page or menu. You get a FAQ, a short description, schema code for your website and an "
              "llms.txt file, with a README saying where each goes. Joe only uses the facts you give: missing "
              "ones are listed, never guessed. He can't check how AI search ranks you (that needs paid services).",
         plan_hint="Help a business get found by AI search / answer engines (AEO, FAQ, schema, llms.txt): TYPE: "
                   "ai-search, FORMAT: the business details they gave, word for word. INPUT only if they point at "
                   "a file (about page, menu). No CHUNKS.",
         examples=("Help my pottery studio show up in ChatGPT answers", "Make an FAQ and schema for my shop"),
         extra_hint="e.g. Corner Bakery, fresh bread and cakes, 12 Main St, Springfield, open Tue-Sat 7-3, 555-0100",
         extra_label="About the business"),
    Tool("meal-plan", "Budget meal planner", "Writing",
         "A week of meals and a shopping list that fits your budget, with the total added up.",
         accepts=(".csv",) + DOC_EXT,
         options=(Option("days", "Days", choices=(("3", "3"), ("5", "5"), ("7", "7")), value="7"),),
         needs=("ollama",), ready=True,
         help="Say your budget, how many people and anything to avoid (allergies, picky eaters). Joe adds up "
              "the shopping list himself and says plainly if it goes over. For real prices, add a spreadsheet "
              "from Read scans and receipts (or your own price list): otherwise prices are estimates marked "
              "[CHECK], because Joe can't see store prices online.",
         plan_hint="Budget meal plan / feed a family on a budget: TYPE: meal-plan, FORMAT: their words (budget, "
                   "people, diet), word for word, OPTIONS: days 3|5|7. INPUT only a receipts spreadsheet or price "
                   "list if they point at one. No CHUNKS.",
         examples=("I have $80 this week to feed a family of 8", "Cheap dinners for 2 for 5 days, no pork"),
         extra_hint="e.g. $80 for the week, family of 8, one is allergic to peanuts",
         extra_label="Budget, people, anything to avoid"),
    Tool("clean-audio", "Clean up a recording", "Audio",
         "Less background noise and hum, and an even volume, for a recording or a video's sound.",
         accepts=AUDIO_EXT + VIDEO_IN_EXT,
         options=(Option("strength", "Noise removal", choices=(("light", "Light"), ("normal", "Normal"),
                                                              ("strong", "Strong (can sound a bit hollow)")), value="normal"),
                  Option("hum", "Remove electrical hum", False, "The low buzz from lights or a cable (50/60 Hz)."),
                  Option("level", "Even out the volume", True, "The usual level for podcasts and YouTube.")),
         needs=("ffmpeg",), ready=True,
         help="FFmpeg does it on this PC in seconds; no AI involved, so nothing is made up. A video keeps its "
              "picture as it was; only the sound is cleaned. Your original is never changed. Try Normal first.",
         plan_hint="Clean up / denoise a recording or a video's sound: TYPE: clean-audio, INPUT: the file(s), "
                   "OPTIONS: strength light|normal|strong, plus hum (only if they mention a buzz or hum), level. No CHUNKS.",
         examples=("Clean up the background noise in my podcast", "Fix the hum in this video")),
    Tool("tidy-speech", "Cut out ums and long pauses", "Audio",
         "A recording or talking video without the 'um', 'uh' and long silences.",
         accepts=AUDIO_EXT + VIDEO_IN_EXT,
         options=(Option("fillers", "Cut um, uh, er", True),
                  Option("pauses", "Shorten long pauses", True),
                  Option("pause", "A pause is longer than", choices=(("0.7", "0.7 s"), ("1.0", "1 s"), ("1.5", "1.5 s"),
                                                                     ("2.5", "2.5 s")), value="1.0"),
                  Option("language", "Spoken in", choices=HEAR_LANGUAGES[:1] + HEAR_LANGUAGES[2:], value="english")),
         needs=("voice", "ffmpeg"), ready=True,
         help="Joe listens word by word (like Transcribe), then FFmpeg cuts out the fillers and trims long "
              "silences to a short natural gap. You get the tidy copy and a list of every cut. Listen through "
              "once before you post it. Videos are re-saved (that takes a little while).",
         plan_hint="Remove ums / filler words / long pauses from a recording or talking video: TYPE: tidy-speech, "
                   "INPUT: the file(s), OPTIONS: fillers, pauses, pause 0.7|1.0|1.5|2.5. No CHUNKS.",
         examples=("Cut the ums out of my podcast", "Remove the long pauses from this video")),
    Tool("joe-language", "Joe's screens in another language", "Writing",
         "Joe translates his own window into another language with the writing model.",
         options=(Option("to", "Into", choices=tuple((en.lower(), own if own == en else f"{own} ({en})")
                                                     for c, (en, own) in UI_LANGUAGES.items()
                                                     if c != "en"), required=True),),
         needs=("ollama",), ready=True,
         help="Joe collects every line of his own screens and the writing model translates them in small batches, "
              "saved to Languages/<code>.json in Joe's folder as he goes (a stopped run carries on next time). Then pick "
              "the language in Setup > Display & sound. A machine translation: fix any line in that file.",
         plan_hint="Translate Joe's own screens / app window into another language: TYPE: joe-language, OPTIONS: to <language>. "
                   "No INPUT, no CHUNKS.",
         examples=("Translate Joe's screens into Spanish",)),
    Tool("edit-words", "Edit a video by its words", "Video",
         "Delete words from what was said and Joe cuts them out of the video or recording (like Descript).",
         accepts=VIDEO_IN_EXT + AUDIO_EXT + (".txt", ".md"),
         options=(Option("fillers", "Also cut um, uh, er", False),
                  Option("pauses", "Also shorten long pauses", False),
                  Option("pause", "A pause is longer than", choices=(("0.7", "0.7 s"), ("1.0", "1 s"), ("1.5", "1.5 s"),
                                                                     ("2.5", "2.5 s")), value="1.0"),
                  Option("language", "Spoken in", choices=HEAR_LANGUAGES[:1] + HEAR_LANGUAGES[2:], value="english")),
         needs=("voice", "ffmpeg"), ready=True,
         help="Two steps. 1) Add the video (or recording) and run it: Joe writes what was said as a words file in "
              "Output. 2) Open that file, delete the words you don't want (don't retype or add words: Joe can only "
              "cut), save it, put it in the Inbox next to the video and run it again: Joe cuts those words out and "
              "lists every cut. Your original is never changed. Watch it through once before you post it.",
         plan_hint="Edit a video or recording by its transcript / cut out words or sentences they deleted: TYPE: "
                   "edit-words, INPUT: the video or recording, plus their edited words .txt file if they have one "
                   "(without it, Joe writes the words file first), OPTIONS: fillers, pauses (only if asked). No CHUNKS.",
         examples=("Let me edit my video by deleting words", "Cut the sentences I deleted out of my video")),
    Tool("dub-video", "Dub or voice-over a video", "Video",
         "Your video in another language: translated subtitles, and a voice-over for many languages.",
         accepts=VIDEO_IN_EXT + AUDIO_EXT,
         options=(Option("to", "Into", choices=LANGUAGES, required=True),
                  Option("voice", "Add a voice-over", True, "Joe's voice speaks English, Spanish, French, Italian, "
                         "Portuguese and Hindi; other languages get subtitles only."),
                  Option("voice-of", "Voice", choices=(("man", "A man's voice"), ("woman", "A woman's voice")), value="man"),
                  Option("original", "Original sound", choices=(("low", "Turned down (you hear it softly)"),
                                                                ("half", "Half volume"), ("off", "Off")), value="low"),
                  Option("language", "Spoken in", choices=HEAR_LANGUAGES[:1] + HEAR_LANGUAGES[2:], value="english")),
         needs=("voice", "ffmpeg", "ollama"), ready=True,
         help="Joe listens (like Transcribe), the writing model translates each line, and you get a subtitles "
              "file in the new language. With a voice-over, Joe's voice says each line at its time (a little "
              "faster where it has to fit) over the original sound turned down; the video gets the voice-over and "
              "subtitles built in. It's a machine translation: have someone who speaks the language check it "
              "before you publish.",
         plan_hint="Dub / voice-over / translate a video or recording into another language: TYPE: dub-video, INPUT: "
                   "the file(s), OPTIONS: to <language>, voice (unless they only want subtitles), voice-of man|woman, "
                   "original low|half|off. No CHUNKS.",
         examples=("Dub my video into Spanish", "Spanish subtitles for this video")),
    Tool("b-roll", "Add B-roll to a talking video", "Video",
         "Cut to your own clips and photos where they match what's being said.",
         accepts=VIDEO_IN_EXT + PHOTO_EXT,
         options=(Option("amount", "How much", choices=(("few", "A few cutaways"), ("some", "Some (about a third)"),
                                                        ("lots", "Lots (about half)")), value="some"),
                  Option("language", "Spoken in", choices=HEAR_LANGUAGES[:1] + HEAR_LANGUAGES[2:], value="english")),
         needs=("voice", "ffmpeg", "ollama"), ready=True,
         help="Add the talking video plus the clips and photos you want to cut to (a folder works). Joe listens, the "
              "writing model matches clips to what's said, and FFmpeg lays each one over the speaker for a few "
              "seconds while the sound stays theirs. Name clips for what they show ('kiln-firing.mp4'): that's how "
              "Joe matches them. Never two cutaways in a row, never the first 2 seconds. A list of every cutaway is saved.",
         plan_hint="Add B-roll / cutaways to a talking video from their own clips: TYPE: b-roll, INPUT: the talking "
                   "video and the clips/photos (or a folder), OPTIONS: amount few|some|lots. No CHUNKS.",
         examples=("Add my B-roll clips to this video", "Cut to my product photos when I talk about them")),
    Tool("privacy-blur", "Privacy blur", "Pictures",
         "Blur faces, license plates, house numbers and screens before you post a photo.",
         accepts=PHOTO_EXT,
         options=(Option("blur", "Blur", choices=tuple((k, {"faces": "Faces", "plates": "License plates",
                                                            "addresses": "House numbers and addresses",
                                                            "screens": "Screens and papers",
                                                            "kids": "Children (whole body)"}[k]) for k in
                                                       ("faces", "plates", "addresses", "screens", "kids")),
                         multi=True),),
         needs=("ollama", "vision", "ffmpeg"), ready=True,
         help="The vision model on this PC finds them; FFmpeg blurs a little more than each spot, hard enough "
              "that it can't be read back. Hidden details like GPS location are left out of the copy. AI can "
              "miss things: always look at the picture before posting. Nothing picked = faces, plates, "
              "addresses and screens.",
         plan_hint="Blur faces / license plates / addresses / screens in photos: TYPE: privacy-blur, INPUT: the "
                   "photo(s), OPTIONS: blur faces, blur plates, blur addresses, blur screens, blur kids (what they "
                   "asked for; none = the first four). No CHUNKS.",
         examples=("Blur the faces in these party photos", "Hide the license plate in my car photo")),
    Tool("social-graphic", "Social graphics and flyers", "Pictures",
         "Your exact words on a photo or a plain color, at each social site's size.",
         accepts=PHOTO_EXT,
         options=(Option("size", "Sizes", hint="Pick one or more: each gets its own picture.",
                         choices=tuple((k, v[0]) for k, v in SOCIAL_SIZES.items()),
                         multi=True),
                  Option("place", "Words go", choices=(("bottom", "At the bottom"), ("middle", "In the middle"),
                                                       ("top", "At the top")), value="bottom"),
                  Option("color", "Background (no photo)", choices=(("dark", "Dark"), ("white", "White"), ("navy", "Navy"),
                                                                     ("green", "Green"), ("red", "Red"), ("purple", "Purple"),
                                                                     ("teal", "Teal"), ("warm", "Warm orange")), value="dark")),
         needs=("ffmpeg",), ready=True,
         help="Type the words in the box: the first line is the big headline, the rest is smaller. Joe places "
              "them with a real font (no AI drawing letters), so spelling is exactly yours. Add a photo for the "
              "background, or leave it out for a plain color. Want a picture made first? Make one, then use it here.",
         plan_hint="Social media graphic / post image / flyer with exact text: TYPE: social-graphic, FORMAT: ALL the "
                   "words to put on the picture, word for word, headline first, lines separated by ' | ' (the TASK "
                   "name is NOT shown on the picture, so never move words from FORMAT into it), OPTIONS: size ig-post|ig-portrait|story|fb-post|"
                   "fb-cover|x-post|yt-thumb|pinterest|flyer|flyer-a4 (one or more), place bottom|middle|top. INPUT "
                   "only a photo they point at. No CHUNKS.",
         examples=("Make an Instagram post that says Grand Opening Saturday", "A flyer for our yard sale"),
         extra_hint="e.g. Grand opening Saturday!\n10% off everything, 9am-3pm, 12 Main St",
         extra_label="The words (first line = headline)"),
    Tool("ask-sheet", "Ask my spreadsheet", "Files",
         "Totals, averages, counts and charts from a spreadsheet, worked out by Joe's own math.",
         accepts=SHEET_EXT,
         needs=("ollama",), ready=True,
         help="Type your question(s) in the box (one per line), like 'which month sold the most?' or 'total "
              "spent on supplies in 2026'. The writing model only turns each question into a plan; Joe's own code "
              "does the math, so the numbers are always right, and each answer says how it was worked out. "
              "Answers with several rows come with a bar chart. Your spreadsheet is never changed.",
         plan_hint="Questions about a spreadsheet (totals, averages, counts, which is biggest, per month): TYPE: "
                   "ask-sheet, INPUT: the CSV or Excel file, FORMAT: their question(s), one per line, word for word. No CHUNKS.",
         examples=("Which product sold the most?", "Total spent per month in my expenses sheet"),
         extra_hint="e.g. Total sales per month?\nWhich item sold the most?",
         extra_label="Your question(s)"),
    Tool("sort-files", "Sort and rename my files", "Files",
         "Documents sorted into folders with clear names like '2026-03-02 Electric bill.pdf'.",
         accepts=DOC_EXT + (".csv",),
         options=(Option("folders", "Sort into folders", True),
                  Option("rename", "Give clear names (with the document's date)", True)),
         needs=("ollama",), ready=True,
         help="Joe reads the start of each document and picks a folder and a clear name. He makes sorted COPIES: "
              "your originals stay exactly where they were. Want your own folders? Type them in the box "
              "(Bills, Taxes, School...). A list of what went where is saved too.",
         plan_hint="Sort / organize / rename documents: TYPE: sort-files, INPUT: the files or folder, OPTIONS: folders, "
                   "rename, FORMAT: their own category names if they gave any. No CHUNKS.",
         examples=("Sort my scanned bills into folders", "Give my downloads clear names"),
         extra_hint="optional, e.g. Bills, Taxes, Medical, School, Car",
         extra_label="Your folders (optional)"),
    Tool("calendar-file", "Dates and to-dos to my calendar", "Files",
         "A calendar file (.ics) with the dates and to-dos from notes, emails or a transcript.",
         accepts=DOC_EXT,
         needs=("ollama",), ready=True,
         help="Joe finds the dates, times and to-dos in your documents ('dentist Tuesday 3pm', 'send the forms by "
              "the 20th') and makes calendar.ics: double-click it or import it into Google Calendar, Outlook or "
              "Apple Calendar. Joe never touches your calendar account. Guessed dates are marked [CHECK].",
         plan_hint="Put dates / appointments / to-dos from notes or emails into a calendar: TYPE: calendar-file, "
                   "INPUT: the document(s). No CHUNKS.",
         examples=("Put the dates from my meeting notes in my calendar", "Make a calendar file from this school letter")),
    Tool("tidy-sheet", "Tidy a spreadsheet", "Files",
         "Fix duplicates, spelling and categories in a CSV.",
         accepts=SHEET_EXT,
         options=(Option("spaces", "Tidy extra spaces", True, "Trims spaces at the ends and doubled spaces."),
                  Option("dupes", "Remove duplicate rows", True,
                         "Rows that match apart from capitals and spacing. The first one stays."),
                  Option("spelling", "Fix spelling", False,
                         "Only misspelled ordinary words; never numbers, codes, emails, names."),
                  Option("categorize", "Add a Category column", False,
                         "Give the categories in 'Anything else?' (categories: mugs, bowls) or Joe picks a few."),
                  Option("split", "Split a column", False,
                         "Say which in 'Anything else?', e.g. split Name into First name, Last name.")),
         needs=("ollama",), ready=True,
         help="Reads CSV, TSV and Excel (.xlsx, first sheet, values only) and saves a tidy CSV that "
              "opens in Excel, Google Sheets or LibreOffice, plus a list of every change. Your "
              "original is never changed. Spaces and duplicates are done by Joe himself (instant); "
              "spelling, categories and splitting use the writing model.",
         plan_hint="Tidy a spreadsheet: TYPE: tidy-sheet, INPUT: the .csv/.tsv/.xlsx file(s) from the "
                   "list below, OPTIONS: spaces, dupes, plus spelling / categorize / split only if "
                   "asked. FORMAT: 'categories: a, b, c' and/or 'split <Column> into <New>, <New>' "
                   "when they said so. No CHUNKS.",
         examples=("Remove the duplicates from my customer list", "Sort my product sheet into categories"),
         extra_hint="optional, e.g. categories: mugs, bowls, vases · split Name into First name, Last name"),
    Tool("photo-batch", "Resize and convert photos", "Files",
         "Shrink, convert, rename or watermark a folder of photos.",
         accepts=PHOTO_EXT,
         options=(Option("size", "Longest side", hint="Photos are only ever made smaller, never stretched.",
                         choices=(("keep", "Keep the size"), ("800", "Small: 800 px (email, chat)"),
                                  ("1200", "Medium: 1200 px"), ("1600", "Web: 1600 px (shops, sites)"),
                                  ("2400", "Large: 2400 px")), value="1600"),
                  Option("format", "Save as", hint="JPG: photos, small files. WebP: smaller still, "
                         "for websites. PNG: sharp edges and see-through backgrounds, big files.",
                         choices=(("same", "Same as now"), ("jpg", "JPG"), ("webp", "WebP"),
                                  ("png", "PNG")), value="same"),
                  Option("rename", "Rename in order (name-01, name-02...)", False,
                         "Uses the job name. Off: each photo keeps its own name."),
                  Option("corner", "Watermark spot", hint="Only used when you give a watermark.",
                         choices=(("bottom-right", "Bottom right"), ("bottom-left", "Bottom left"),
                                  ("top-right", "Top right"), ("top-left", "Top left"),
                                  ("center", "Middle")), value="bottom-right")),
         needs=("ffmpeg",), ready=True, mark=True,
         help="Your originals are never changed: new copies go in Output. A watermark is only "
              "added if you type one (or pick a logo .png); it's faint, in the spot you choose. "
              "Hidden photo details like the camera and GPS location are left out of the copies. "
              "Needs FFmpeg (Setup > System check). iPhone HEIC photos aren't supported yet: save "
              "them as JPG first.",
         plan_hint="Resize/convert photos: TYPE: photo-batch, INPUT: the photo file(s) or folder "
                   "from the list below, OPTIONS: size 800|1200|1600|2400|keep, format "
                   "same|jpg|webp|png, rename (only if asked), corner bottom-right|bottom-left|"
                   "top-right|top-left|center (only with a watermark). WATERMARK: the exact text, "
                   "ONLY if they asked for a watermark. No CHUNKS.",
         examples=("Shrink my product photos for the website", "Convert these photos to JPG"),
         extra_hint=""),
    Tool("read-scans", "Read scans and receipts", "Files",
         "Pull the text out of scans, receipts and forms.",
         accepts=VISION_EXT,
         options=(Option("as", "Read as", hint="Text: everything written. Receipts: date, shop, total "
                         "and items in a spreadsheet. Table: a table in the picture as a spreadsheet.",
                         choices=(("text", "Text (letters, pages, signs)"), ("receipts", "Receipts and invoices"),
                                  ("table", "A table")), value="text"),),
         needs=("vision",), ready=True,
         help="Copies exactly what's written, never guesses: anything it can't read clearly is "
              "marked [CHECK], so check totals before you rely on them. Photos of paper work too; "
              "flat, bright and in focus works best. PDFs aren't read here yet (take a screenshot). "
              + VISION_HELP_TEXT,
         plan_hint="Read scans/receipts/photos of text: TYPE: read-scans, INPUT: the picture file(s) "
                   "from the list below, OPTIONS: as text|receipts|table. No CHUNKS.",
         examples=("Type up the text from these scanned pages", "Put my receipts in a spreadsheet"),
         extra_hint="optional, e.g. the receipts are from March"),
    Tool("photo-listing", "Listings from photos", "Pictures",
         "Titles, descriptions, tags and alt text from product photos.",
         accepts=VISION_EXT,
         options=(Option("csv", "Spreadsheet (for shop uploads)", True),
                  Option("doc", "Readable document", True)),
         needs=("vision",), ready=True,
         help="One listing per photo: title, description, search tags and alt text. Joe only "
              "describes what he can see: sizes, materials and prices are left for you and marked "
              "[CHECK] if needed. Tell him about the products in 'Anything else?' for better words. "
              + VISION_HELP_TEXT,
         plan_hint="Listings from product photos: TYPE: photo-listing, INPUT: the photo file(s) or "
                   "folder from the list below, OPTIONS: csv, doc. FORMAT: what they told you about "
                   "the products and the tone. No CHUNKS.",
         examples=("Write listings for my product photos", "Alt text for these pictures"),
         extra_hint="optional, e.g. handmade stoneware mugs, warm friendly tone"),
    Tool("sort-photos", "Sort my photos", "Pictures",
         "Tag and sort a folder of pictures by what's in them.",
         accepts=VISION_EXT,
         options=(Option("folders", "Copy into a folder per category", True,
                         "Copies: your photos stay where they are."),),
         needs=("vision",), ready=True,
         help="Gives every photo a category, tags and a one-line caption (photo-list.csv), and "
              "copies it into a folder named after its category. Give your own categories in "
              "'Anything else?' (categories: family, garden, pets) or Joe picks and reuses short "
              "ones. Faces are never named. " + VISION_HELP_TEXT,
         plan_hint="Sort/tag photos: TYPE: sort-photos, INPUT: the photo folder or files from the "
                   "list below, OPTIONS: folders (or none). FORMAT: 'categories: a, b, c' if they "
                   "named them. No CHUNKS.",
         examples=("Sort my vacation photos", "Tag these pictures by what's in them"),
         extra_hint="optional, e.g. categories: family, garden, pets"),
    Tool("remove-bg", "Remove background and upscale", "Pictures",
         "Clean, sharp product shots.", accepts=COMFY_PHOTO_EXT, needs=("comfy",), ready=True,
         options=(Option("background", "Background", choices=(
                      ("transparent", "See-through (PNG)"), ("white", "White (JPG, for shops)")),
                         value="transparent"),
                  Option("upscale", "Make it bigger and sharper", hint="Real-ESRGAN: 2x is usually "
                         "plenty; 4x makes big files.", choices=(("none", "No"), ("2x", "2x"),
                                                                  ("4x", "4x")), value="none"),
                  Option("keep", "Keep", hint="Main subject only drops smaller things the cut-out kept "
                         "(a brush or tool lying next to the product).", choices=(
                             ("all", "Everything it finds"), ("main", "Main subject only")), value="all")),
         help="Cuts the subject out with BiRefNet (MIT license, under 1 GB, offered once). Runs in "
              "ComfyUI on the graphics card, a few seconds a photo. Your originals are never changed.",
         plan_hint="Remove backgrounds: TYPE: remove-bg, INPUT: the photo file(s)/folder from the list "
                   "below, OPTIONS: background transparent|white, upscale none|2x|4x, keep all|main (main = "
                   "only the biggest object, when they want just the product). No CHUNKS.",
         examples=("Remove the background from my product photos", "White background for my shop pictures")),
    Tool("edit-picture", "Edit a picture by asking", "Pictures",
         "\"Swap the background\", \"remove the cup\".", accepts=COMFY_PHOTO_EXT, needs=("comfy",),
         ready=True,
         help="Say what to change in plain words; the same change is made to every picture. Uses "
              "Qwen-Image-Edit 2511 (Apache-2.0, about 31 GB, offered once): best with a 12 GB+ "
              "graphics card and 32 GB of memory, about 1-3 minutes a picture (about 4-5 on a 12 GB card). Quality > High in "
              "Setup is slower but finer. Your originals are never changed.",
         plan_hint="Edit pictures by instruction: TYPE: edit-picture, INPUT: the picture file(s) from "
                   "the list below, FORMAT: the change in their words (e.g. replace the background "
                   "with a white marble counter). No CHUNKS, no OPTIONS.",
         examples=("Swap the background of this photo for a beach", "Remove the cup from these pictures"),
         extra_label="What should change?", extra_hint="e.g. replace the background with a white marble counter"),
    Tool("restore-photo", "Restore old photos", "Pictures",
         "Undo fading and color casts, true to the photo.", accepts=COMFY_PHOTO_EXT, needs=("ffmpeg",),
         ready=True,
         options=(Option("colorize", "Add color", False, "Off keeps black and white or sepia."),
                  Option("sepia", "Keep sepia tone", False,
                         "For brown-toned old prints: Joe restores it, then puts the warm tone back "
                         "(otherwise it can come out grey)."),
                  Option("upscale", "Make it bigger and sharper", choices=(
                      ("none", "No"), ("2x", "2x"), ("4x", "4x")), value="2x"),
                  Option("method", "How to restore", choices=(
                      ("true", "True to the photo (no AI redraw, faces stay theirs)"),
                      ("ai", "AI repair (also scratches and tears; can change faces)")), value="true"),
                  Option("change-faces", "Let AI repair redraw faces too", False,
                         "Off (the usual): with AI repair, Joe finds the faces first and puts the real "
                         "ones back afterwards, so nobody turns into a stranger (needs a vision model; "
                         "System check offers one)."),
                  Option("strength", "How strong (true to the photo)", choices=(
                      ("auto", "Joe decides from how faded each photo is"),
                      ("strong", "Strong (very faded)"), ("medium", "Medium"),
                      ("light", "Light (barely faded)")), value="auto")),
         help="True to the photo (the usual choice) does only what a darkroom would: undoes fading "
              "and the pink or orange cast of old prints, smooths grain, makes it bigger and a little "
              "sharper. Nothing is redrawn, so faces stay exactly theirs; it needs FFmpeg only. AI "
              "repair uses the picture editor (about 31 GB, offered once) to also mend scratches, tears "
              "and stamps, and to add color, but it can make someone look like a different person: "
              "compare with the original before you share it. Your originals are never changed. "
              "Scanning tips: scan at 300 dpi (600 dpi for small prints and wallet photos), in color "
              "even for black-and-white photos, with the scanner's auto-correct, auto-color and "
              "dust removal turned off (Joe does that part), and wipe the glass first.",
         plan_hint="Restore old photos: TYPE: restore-photo, INPUT: the photo file(s)/folder from the "
                   "list below, OPTIONS: upscale none|2x|4x, method true (default) or ai (only if they ask to "
                   "fix scratches/tears/stamps), strength auto (default)|strong|medium|light, sepia (only if they "
                   "say the photo is sepia or brown-toned and want to keep that), colorize (only "
                   "if they want color; uses ai). "
                   "No CHUNKS.",
         examples=("Restore my grandparents' old photos", "Fix and colorize this old picture"),
         extra_hint="optional, e.g. the dress was blue"),
    Tool("fix-spot", "Fix one spot", "Pictures",
         "Mark a spot; only that spot changes.", accepts=COMFY_PHOTO_EXT, needs=("comfy",), ready=True,
         help="Add the picture, press MARK THE SPOT and paint over what to fix (a date stamp, a "
              "scratch, a stranger, a cup). Only the painted part is redrawn; everything else stays "
              "exactly as it was. Leave the box below empty to remove what's there, or say what "
              "should go there instead. " + "Uses the Qwen-Image-Edit 2511 picture editor (Apache-2.0, about 31 GB, offered once; the same one Edit a picture uses), about 1-3 minutes a picture on a big graphics card (about 4-5 minutes on a 12 GB card, which reads your request on the processor). Your originals are never changed.",
         plan_hint="Fix one marked spot in a picture (needs a mask painted in the Tools tab): TYPE: "
                   "fix-spot, INPUT: the picture file(s), FORMAT: what goes there (empty = remove it). "
                   "No CHUNKS, no OPTIONS.",
         examples=("Remove the date stamp from this photo", "Take the cup off the table in this picture"),
         extra_label="What goes there? (optional)", extra_hint="empty = remove it; or e.g. a vase of flowers"),
    Tool("merge-pictures", "Put pictures together", "Pictures",
         "Two or three pictures into one.", accepts=COMFY_PHOTO_EXT, needs=("comfy",), ready=True,
         help="Add 2 or 3 pictures and say how to combine them, calling them picture 1, 2 and 3 in "
              "the order you added them (\"put the mug from picture 2 on the table in picture 1\"). "
              "Makes one new picture. " + "Uses the Qwen-Image-Edit 2511 picture editor (Apache-2.0, about 31 GB, offered once; the same one Edit a picture uses), about 1-3 minutes a picture on a big graphics card (about 4-5 minutes on a 12 GB card, which reads your request on the processor). Your originals are never changed.",
         plan_hint="Combine 2-3 pictures into one: TYPE: merge-pictures, INPUT: the picture files in "
                   "order, FORMAT: how to combine them, naming them picture 1, 2, 3. No CHUNKS, no OPTIONS.",
         examples=("Put my dog from this photo into the beach picture", "Place my mug on this kitchen counter"),
         extra_label="How should they go together?",
         extra_hint="e.g. put the mug from picture 2 on the table in picture 1"),
    Tool("relight", "Change the lighting", "Pictures",
         "Golden hour, studio light, night...", accepts=COMFY_PHOTO_EXT, needs=("comfy",), ready=True,
         options=(Option("light", "Light", choices=tuple((k, v[0]) for k, v in RELIGHTS.items()), value="golden"),),
         help="Changes only the light and shadows; people, things and the scene stay the same. " + "Uses the Qwen-Image-Edit 2511 picture editor (Apache-2.0, about 31 GB, offered once; the same one Edit a picture uses), about 1-3 minutes a picture on a big graphics card (about 4-5 minutes on a 12 GB card, which reads your request on the processor). Your originals are never changed.",
         plan_hint="Change the lighting of pictures: TYPE: relight, INPUT: the picture file(s), "
                   "OPTIONS: light " + "|".join(RELIGHTS) + ", FORMAT: extra wishes (optional). No CHUNKS.",
         examples=("Make this photo look like golden hour", "Give my product photo studio lighting"),
         extra_label="Anything else? (optional)", extra_hint="e.g. light coming from the window on the left"),
    Tool("restyle", "Redraw in a new style", "Pictures",
         "Your picture as watercolor, anime, a sketch...", accepts=COMFY_PHOTO_EXT, needs=("comfy",), ready=True,
         options=(Option("style", "Style", choices=tuple((k, v[0]) for k, v in RESTYLES.items()), value="watercolor"),),
         help="Keeps what's in the picture and how it's laid out; changes how it's drawn. \"Like my "
              "last picture\" copies the look of the LAST picture you add onto the others. " + "Uses the Qwen-Image-Edit 2511 picture editor (Apache-2.0, about 31 GB, offered once; the same one Edit a picture uses), about 1-3 minutes a picture on a big graphics card (about 4-5 minutes on a 12 GB card, which reads your request on the processor). Your originals are never changed.",
         plan_hint="Redraw pictures in another art style: TYPE: restyle, INPUT: the picture file(s) "
                   "(for 'picture', the last file is the style example), OPTIONS: style "
                   + "|".join(RESTYLES) + ". No CHUNKS.",
         examples=("Turn this photo of my house into a watercolor", "Make my dog photo look like anime"),
         extra_label="Anything else? (optional)", extra_hint="e.g. soft pastel colors"),
    Tool("redraw", "Change a picture a little or a lot", "Pictures",
         "Same picture, new take: you pick how much changes.", accepts=COMFY_PHOTO_EXT, needs=("comfy",),
         ready=True,
         options=(Option("change", "How much may change", choices=(
             ("little", "A little (stays close)"), ("some", "Some"), ("lots", "A lot (freer)")), value="some"),),
         help="Say what it should look like; a little keeps it close to your picture, a lot gives the "
              "AI more freedom. " + "Uses the Qwen-Image-Edit 2511 picture editor (Apache-2.0, about 31 GB, offered once; the same one Edit a picture uses), about 1-3 minutes a picture on a big graphics card (about 4-5 minutes on a 12 GB card, which reads your request on the processor). Your originals are never changed.",
         plan_hint="Redraw pictures with a chosen amount of change: TYPE: redraw, INPUT: the picture "
                   "file(s), OPTIONS: change little|some|lots, FORMAT: what it should look like. No CHUNKS.",
         examples=("Make this sketch look finished", "Turn my rough drawing into a clean picture"),
         extra_label="What should it look like?", extra_hint="e.g. a clean, colorful finished illustration"),
    Tool("make-bigger", "Make a picture wider or taller", "Pictures",
         "AI fills in more of the scene around it.", accepts=COMFY_PHOTO_EXT, needs=("comfy",), ready=True,
         options=(Option("shape", "Make it", choices=(
             ("wider", "Wider (for a banner or desktop)"), ("taller", "Taller (for a phone or story)"),
             ("square", "Square (for a post)"), ("around", "Bigger all around")), value="wider"),),
         help="Your picture stays untouched in the middle; the AI paints the new parts around it to "
              "match. " + "Uses the Qwen-Image-Edit 2511 picture editor (Apache-2.0, about 31 GB, offered once; the same one Edit a picture uses), about 1-3 minutes a picture on a big graphics card (about 4-5 minutes on a 12 GB card, which reads your request on the processor). Your originals are never changed.",
         plan_hint="Extend pictures (outpaint): TYPE: make-bigger, INPUT: the picture file(s), OPTIONS: "
                   "shape wider|taller|square|around. No CHUNKS.",
         examples=("Make this photo wide enough for a banner", "Make my picture tall for a phone wallpaper"),
         extra_label="What's around it? (optional)", extra_hint="e.g. more beach and sky"),
    Tool("character-scenes", "Same character, new scenes", "Pictures",
         "One character, many pictures that match.", accepts=COMFY_PHOTO_EXT, needs=("comfy",), ready=True,
         help="Add one picture of your character (a mascot, a drawing, a toy) and write one scene per "
              "line, or separate them with ;. Each scene gets its own picture with the same face, "
              "outfit and colors. " + "Uses the Qwen-Image-Edit 2511 picture editor (Apache-2.0, about 31 GB, offered once; the same one Edit a picture uses), about 1-3 minutes a picture on a big graphics card (about 4-5 minutes on a 12 GB card, which reads your request on the processor). Your originals are never changed.",
         plan_hint="The same character in new scenes: TYPE: character-scenes, INPUT: one picture of the "
                   "character, FORMAT: one scene per line. No CHUNKS, no OPTIONS.",
         examples=("Put my mascot in 5 different scenes", "Show my dragon drawing at the beach and in space"),
         extra_label="Scenes (one per line, or separated by ;)",
         extra_hint="e.g. waving at the beach; reading a book; riding a bike"),
    Tool("character-spin", "Character turnaround", "Pictures",
         "Front, side and back views, plus a sheet.", accepts=COMFY_PHOTO_EXT, needs=("comfy",), ready=True,
         options=(Option("views", "Views", hint="Quick is about half the time.", choices=(
             ("full", "All six (front, three-quarters, sides, back)"), ("quick", "Quick: front, side and back")),
             value="full"),),
         help="Add one picture of a character; Joe makes six views (front, three-quarter, sides, back), or "
              "three with Quick, and puts them side by side on one sheet. Handy for drawing, 3D and games. "
              "The plan shows how long it will take before anything starts. " + "Uses the Qwen-Image-Edit 2511 picture editor (Apache-2.0, about 31 GB, offered once; the same one Edit a picture uses), about 1-3 minutes a picture on a big graphics card (about 4-5 minutes on a 12 GB card, which reads your request on the processor). Your originals are never changed.",
         plan_hint="Character turnaround (front/side/back views): TYPE: character-spin, INPUT: one "
                   "picture of the character, OPTIONS: views full|quick (quick = front, side, back only, "
                   "when they want it fast). No CHUNKS.",
         examples=("Make a turnaround sheet of my mascot", "Show my character from every side")),
    Tool("sketch-to-picture", "Sketch to picture", "Pictures",
         "Your drawing, finished by the AI.", accepts=COMFY_PHOTO_EXT, needs=("comfy", "sdxl"), ready=True,
         options=(Option("look", "Look", choices=tuple((k, v[0]) for k, v in LOOKS.items()), value="auto"),
                  Option("follow", "How closely to follow your lines", choices=(
                      ("close", "Closely"), ("some", "Some freedom"), ("loose", "Loosely (just the idea)")),
                         value="some"),
                  Option("lines", "Your drawing is", choices=(
                      ("rough", "A rough sketch or doodle"), ("clean", "Clean line art")), value="rough")),
         help="Add a drawing (a photo or scan of paper is fine) and say what it is. Joe keeps your "
              "shapes and layout and paints a finished picture over them. Uses ControlNet Union SDXL "
              "(Apache-2.0, about 2.5 GB, offered once) with the SDXL picture models Joe already uses; "
              "about 30 seconds a picture. Your originals are never changed.",
         plan_hint="Finish a sketch or drawing into a picture: TYPE: sketch-to-picture, INPUT: the drawing "
                   "file(s), OPTIONS: look auto|" + "|".join(k for k in LOOKS if k != "auto")
                   + ", follow close|some|loose, lines rough|clean, FORMAT: what the drawing shows. No CHUNKS.",
         examples=("Turn my sketch of a castle into a real painting", "Finish my kid's drawing as a cartoon"),
         extra_label="What does the drawing show?", extra_hint="e.g. a red dragon sleeping on a pile of gold"),
    Tool("illusion-art", "Hidden-picture illusion", "Pictures",
         "A scene with a shape or word hidden in it.", accepts=COMFY_PHOTO_EXT, needs=("comfy", "sdxl"),
         ready=True,
         options=(Option("hidden", "Hide", choices=tuple((k, v[0]) for k, v in ILLUSION_PATTERNS.items()),
                         value="spiral"),
                  Option("show", "How easy to see", choices=(
                      ("hidden", "Hidden (squint to see it)"), ("clear", "Clear"), ("bold", "Bold")), value="clear"),
                  Option("look", "Look", choices=tuple((k, v[0]) for k, v in LOOKS.items()), value="auto"),
                  Option("versions", "Versions", hint="Hidden words miss more often than shapes: 4 gives "
                         "you a good pick.", choices=(("1", "1"), ("2", "2"), ("4", "4")), value="4")),
         help="Write the scene (a village, a forest, clouds). Joe hides a spiral, circles, a word or "
              "your own black-and-white shape or logo in it, so it pops out when you squint or step "
              "back. For a word, add a line like  word: JOE  (14 letters at most). Uses QR Code Monster "
              "SDXL (OpenRAIL++, about 5 GB, offered once) with the SDXL picture models Joe already "
              "uses; about 30 seconds a picture. Every version looks different: pick the best one, and "
              "check it small or squinting (that's how people see these): the AI sometimes draws a "
              "letter backwards or loose. Short words in capitals (3-6 letters) work best.",
         plan_hint="Hidden-picture illusion art: TYPE: illusion-art, INPUT: a black-and-white shape/logo "
                   "picture (only for hidden picture), OPTIONS: hidden " + "|".join(ILLUSION_PATTERNS)
                   + ", show hidden|clear|bold, versions 1|2|4, FORMAT: the scene, plus a line 'word: TEXT' "
                     "for a hidden word. No CHUNKS.",
         examples=("Hide the word JOE in a forest picture", "Make a spiral illusion of a medieval village"),
         extra_label="The scene (and word: TEXT to hide a word)",
         extra_hint="e.g. a cozy mountain village in winter\nword: JOE"),
    Tool("make-3d", "Picture to 3D model", "Pictures",
         "One picture in, a 3D model (.glb) out.", accepts=COMFY_PHOTO_EXT, needs=("comfy",), ready=True,
         help="Works best with one object or character, whole and in the middle, on a plain "
              "background (Joe cuts it out when the background remover is installed). Makes the shape "
              "only: a plain white model, ready to paint or print. Opens in Windows 3D Viewer, Blender, "
              "Unity and Unreal. Uses Hunyuan3D 2.1 (about 4.6 GB, offered once; Tencent's community "
              "license, which does not cover the European Union, the United Kingdom or South Korea); "
              "about 1-2 minutes a model. Your originals are never changed.",
         plan_hint="Turn pictures of an object/character into 3D models (.glb): TYPE: make-3d, INPUT: the "
                   "picture file(s). No CHUNKS, no OPTIONS, no FORMAT.",
         examples=("Make a 3D model from my mascot drawing", "Turn this photo of my mug into a 3D model")),
    Tool("animate-photo", "Animate a photo", "Video",
         "Turn one of your photos into a short clip.", accepts=COMFY_PHOTO_EXT, needs=("comfy",),
         ready=True,
         help="A 5-second clip that starts from your photo, made with the Wan 2.2 video model "
              "(Apache-2.0, the same one Joe's videos use). Describe the motion, or leave it empty "
              "for gentle natural movement. About 2 minutes a clip with the Turbo add-on, much longer "
              "without. Your originals are never changed.",
         plan_hint="Animate photos into clips: TYPE: animate-photo, INPUT: the photo file(s) from the "
                   "list below, FORMAT: the motion they want (optional). No CHUNKS, no OPTIONS.",
         examples=("Make this photo move", "Animate my product photo with a slow turn"),
         extra_label="What should move? (optional)", extra_hint="e.g. steam rising from the mug, slow camera push-in"),
    Tool("restyle-video", "Restyle a video", "Video",
         "Same motion, new look: anime, watercolor...", accepts=VIDEO_TOOL_EXT + COMFY_PHOTO_EXT,
         needs=("comfy", "ffmpeg"), ready=True,
         options=(Option("style", "New look", choices=tuple((k, v[0]) for k, v in RESTYLES.items()
                                                             if k != "picture") + (("own", "My words below"),),
                         value="anime"),
                  Option("length", "How much of the video", choices=(
                      ("5", "First 5 seconds"), ("10", "First 10 seconds"), ("20", "First 20 seconds"),
                      ("30", "First 30 seconds")), value="5"),
                  Option("follow", "Follow the original", choices=(
                      ("close", "Closely (every outline)"), ("loose", "Loosely (main shapes only)")),
                         value="close")),
         help="Add a video (and, if you like, one picture whose look it should take). Joe traces the "
              "outlines of every frame and the AI paints a new video over them: same moves, new look. "
              "Works in 5-second pieces that are joined at the end; the original sound is put back. "
              "Uses Wan 2.2 Fun Control 5B (Apache-2.0, about 10 GB more when Joe's video model is "
              "installed, offered once). Slow: several minutes for every 5 seconds. Your originals are "
              "never changed.",
         plan_hint="Restyle a video (keep its motion, change its look): TYPE: restyle-video, INPUT: the video "
                   "file (+ optional picture to copy the look from), OPTIONS: style "
                   + "|".join(k for k in RESTYLES if k != "picture") + "|own, length 5|10|20|30, "
                   "follow close|loose, FORMAT: the look in their words (needed for own). No CHUNKS.",
         examples=("Make my dance video look like anime", "Turn this clip into a watercolor painting"),
         extra_label="The new look (optional)", extra_hint="e.g. a claymation world with soft colors"),
    Tool("make-shorts", "Make shorts from a long video", "Video",
         "The best moments as vertical clips with big captions.", accepts=VIDEO_IN_EXT,
         needs=("voice", "ffmpeg", "ollama"), ready=True,
         options=(Option("count", "How many shorts", choices=(("3", "3"), ("5", "5"), ("8", "8"), ("12", "12")),
                         value="5"),
                  Option("length", "Each one up to", choices=(("30", "30 seconds"), ("45", "45 seconds"),
                                                              ("60", "60 seconds"), ("90", "90 seconds")), value="45"),
                  Option("crop", "Fill the tall frame by", choices=(
                      ("face", "Following the speaker's face"), ("center", "Keeping the middle"),
                      ("fit", "Showing the whole picture (blurred bars)")), value="face"),
                  Option("captions", "Big word-by-word captions", True, "Burned into the video, easy to read "
                         "with the sound off."),
                  Option("title", "Hook title at the top (first seconds)", True),
                  Option("posts", "Social post for each short", True,
                         "A caption with hashtags, plus files for a post scheduler (Postiz, Mixpost or a "
                         "spreadsheet). Joe never posts for you."),
                  Option("language", "Spoken in", choices=HEAR_LANGUAGES, value="english")),
         help="Add a long video with talking in it (a podcast, a class, a stream). Joe writes down every word "
              "with its time, the writing model picks the moments that stand on their own (a strong start, "
              "one complete thought, a clean ending), and FFmpeg cuts each one as a 1080x1920 clip. With a "
              "vision model, Joe finds the speaker's face so the tall frame follows the person. A shorts.md "
              "list says why each moment was picked. About real time to listen, then a minute or two per "
              "clip. Your original video is never changed. Check every clip before posting: the model can "
              "pick a moment that needs context.",
         plan_hint="Make shorts (long video -> vertical clips): TYPE: make-shorts, INPUT: the video file(s), "
                   "OPTIONS: count 3|5|8|12, length 30|45|60|90, crop face|center|fit, captions, title, posts "
                   "(leave out what they don't want), language <name> when not English. FORMAT: what kind of "
                   "moments they want (optional). No CHUNKS.",
         examples=("Cut my podcast into 5 shorts for TikTok", "Make YouTube Shorts from my class recording"),
         extra_label="What moments to look for (optional)", extra_hint="e.g. funny moments, or the best tips"),
    Tool("music", "Music and sound effects", "Audio",
         "Background music and short jingles.", needs=("comfy",), ready=True,
         options=(Option("kind", "Make", choices=(("music", "Music (instrumental)"),
                                                  ("sfx", "Sound effects")), value="music"),
                  Option("length", "Length", hint="Sound effects stop at about 47 seconds.",
                         choices=(("10", "10 seconds"), ("30", "30 seconds"), ("60", "1 minute"),
                                  ("120", "2 minutes"), ("180", "3 minutes")), value="30")),
         help="One piece per line you type, saved as MP3. Music: ACE-Step 1.5 (MIT, about 10 GB, "
              "offered once), instrumental, any style. Sound effects: Stable Audio Open 1.0 (about "
              "5 GB; Stability AI Community License: free under US$1 million revenue a year). Runs "
              "in ComfyUI on the graphics card.",
         plan_hint="Music or sound effects: TYPE: music, no INPUT, FORMAT: one description per line "
                   "(style, mood, instruments, tempo), OPTIONS: kind music|sfx, length 10|30|60|120|180. "
                   "No CHUNKS.",
         examples=("Make 3 calm background tracks for my videos", "A door creak and a doorbell sound effect"),
         extra_label="Describe each piece (one per line)",
         extra_hint="e.g. calm acoustic guitar, warm, slow, for a pottery video"),
    # ---- everyday paperwork (2.2, paperwork.py)
    Tool("pdf-tools", "PDF toolkit", "Files",
         "Join, split, reorder, turn or shrink PDFs, and fill in PDF forms.",
         accepts=(".pdf",),
         options=(Option("do", "What to do", choices=(("merge", "Join them into one PDF"),
                                                     ("split", "Split into pieces"),
                                                     ("pages", "Pick or reorder pages"),
                                                     ("rotate", "Turn pages"),
                                                     ("compress", "Make it smaller"),
                                                     ("fill", "Fill in a form")), value="merge"),
                  Option("shrink", "How small (Make it smaller)",
                         choices=(("safe", "Nothing looks different"),
                                  ("smaller", "Smaller: photos re-saved as JPEG")), value="safe"),
                  Option("turn", "Which way (Turn pages)", choices=(("right", "A quarter turn right"),
                                                                    ("left", "A quarter turn left"),
                                                                    ("upside", "Upside down")), value="right"),
                  Option("lock", "Lock the filled form", False,
                         "Flattens it so the answers can't be changed (for sending a final copy).")),
         needs=("qpdf",), ready=True,
         help="No AI: qpdf (free, Apache license) does the work exactly, on this computer. Join: drop the PDFs in "
              "the order you want. Pick or reorder: say the pages in the box (3, 1, 2 or 1-4, 7 or last). "
              "Split: empty = every page, or every 2, or 1-3, 4-6. Turn: all pages, or say which. Fill in a form: "
              "run it once to get a list of the form's fields, fill it in, paste it in the box and run again. "
              "Locked PDFs need their password first: save an unlocked copy from your PDF reader. Your PDFs are "
              "never changed; new ones are saved next to the results.",
         plan_hint="PDFs: join / split / pick or reorder pages / turn / make smaller / fill in a form: TYPE: pdf-tools, "
                   "INPUT: the PDF file(s) in the order given, OPTIONS: do merge|split|pages|rotate|compress|fill "
                   "(+ turn right|left|upside for rotate, shrink safe|smaller for compress, lock for a final filled "
                   "form), FORMAT: the pages they said (3, 1, 2 / 1-3, 4-6 / every 2) or their form answers as "
                   "'Field: answer' lines, word for word. No CHUNKS.",
         examples=("Join these three PDFs into one", "Take pages 2 and 5 out into their own PDF",
                   "Make this PDF small enough to email", "Fill in this form with my name and address"),
         extra_label="Pages, or your form answers (optional)",
         extra_hint="e.g. 3, 1, 2   or   1-3, 4-6   or   Full name: Jane Smith"),
    Tool("explain-letter", "Explain this letter", "Writing",
         "A bill, lease, insurance or benefits letter in plain words: what to do, by when, and a reply.",
         accepts=TEXT_DOC_EXT + PHOTO_EXT,
         options=(Option("reply", "Draft a reply", True, "A polite reply to fill in and send (never agrees to "
                                                          "pay or admits anything unless you say so)."),
                  Option("calendar", "Deadlines to my calendar", False, "A calendar file (.ics) with each date.")),
         needs=("ollama",), ready=True,
         help="Joe reads the letter (a photo of it works with a vision model) and explains it in everyday words: "
              "what it is, what it means for you, what to do next and questions to ask. Joe lists every date, "
              "amount, phone number and reference number himself and checks each one is really in the letter "
              "(anything that isn't is marked [CHECK]); dates show how many days are left. Common scam signs are "
              "pointed out first. Not legal or money advice: for anything serious, call the number on the letter "
              "or a free advice service.",
         plan_hint="Explain a letter / bill / lease / notice in plain words (what to do, by when, a reply): TYPE: "
                   "explain-letter, INPUT: the letter file(s) or photo(s), OPTIONS: reply (unless they don't want "
                   "one), calendar (only if they want dates in their calendar), FORMAT: what they want to say "
                   "back, word for word (if they said). No CHUNKS.",
         examples=("Explain this letter from my insurance", "What does this bill want me to do and by when?",
                   "Help me understand my lease renewal and write a reply asking for more time"),
         extra_label="What do you want to say back? (optional)",
         extra_hint="e.g. I want to ask for a payment plan"),
    Tool("hide-details", "Hide personal details", "Files",
         "Names, addresses, phone numbers and account numbers hidden in a copy before you share it.",
         accepts=(".txt", ".md", ".markdown", ".docx", ".pdf", ".html", ".htm", ".csv"),
         options=(Option("names", "Let AI find names and addresses too", True,
                         "Joe's own patterns always find emails, phones, card, account and ID numbers; the "
                         "writing model adds people's names and home addresses."),
                  Option("style", "Hide them as", choices=(("labels", "Labels: [NAME 1], [PHONE 1]"),
                                                           ("blocks", "Black blocks: ██████")), value="labels"),
                  Option("key", "Save a private key of the labels", False,
                         "A separate file saying what each label stands for. Keep it to yourself.")),
         needs=("ollama",), ready=True,
         help="Makes a cleaned copy; your file is never changed. Word files stay Word files (the author's name, "
              "reviewer names, the links behind email addresses and picture descriptions are cleaned too; "
              "pictures inside the file, like a signature or a scanned page, are not looked at); text and CSV stay as they are; PDFs and web pages "
              "come back as plain text (blacking out a PDF by drawing boxes leaves the words underneath). The "
              "same person always gets the same label, so the copy still reads well. Type extra words to hide "
              "in the box (one per line), or 'keep: Acme Bakery' for words to leave. Joe can miss things: read "
              "the copy before sharing. For faces and plates in photos, use Privacy blur.",
         plan_hint="Hide / black out / remove personal details (names, addresses, phone numbers, account numbers) "
                   "from documents before sharing: TYPE: hide-details, INPUT: the document(s), OPTIONS: names "
                   "(unless they say patterns only), style labels|blocks (blocks if they say black out), key (only "
                   "if they want a key), FORMAT: extra words to hide or 'keep: ...' words, word for word. No CHUNKS.",
         examples=("Black out the names and account numbers in this statement before I send it",
                   "Remove personal details from my medical letter", "Hide everyone's phone numbers in this list"),
         extra_label="Extra words to hide, or keep: words (optional)",
         extra_hint="e.g. Sam Rivera\nkeep: Acme Bakery"),
    Tool("meeting-minutes", "Meeting minutes", "Audio",
         "A meeting recording (or its transcript) into minutes: decisions, to-dos, who and by when.",
         accepts=AUDIO_EXT + VIDEO_IN_EXT + (".txt", ".md", ".srt", ".vtt", ".docx"),
         options=(Option("language", "Spoken in", choices=HEAR_LANGUAGES, value="english"),
                  Option("transcript", "Keep the transcript too", True),
                  Option("calendar", "To-dos to my calendar", False, "A calendar file (.ics) with each to-do that has a date.")),
         needs=("voice", "ollama"), ready=True,
         help="One step from a recording to minutes: Joe listens (Whisper, on this PC), then the writing model "
              "writes the summary, decisions, to-dos with who and by when, and open questions. Joe can't tell voices "
              "apart: a name is given only when the recording makes it clear (people say names); names and dates "
              "not heard word for word are marked [CHECK]. A transcript or subtitles file works too (no voice "
              "add-on needed). Your recording is never changed or sent anywhere.",
         plan_hint="Meeting minutes / notes with decisions and to-dos from a meeting recording or transcript: TYPE: "
                   "meeting-minutes, INPUT: the recording(s) or transcript(s), OPTIONS: language <what's spoken> "
                   "(english if not said), transcript, calendar (only if they want to-dos in a calendar). No CHUNKS.",
         examples=("Make minutes from this meeting recording", "Who agreed to do what in yesterday's call?",
                   "Turn this Zoom transcript into minutes with to-dos"),
         extra_label="Anything else? (optional)", extra_hint="e.g. focus on the budget decisions"),
    Tool("bank-budget", "Bank statement to budget", "Files",
         "Your bank's CSV sorted into a budget: where the money went, subscriptions and price rises.",
         accepts=SHEET_EXT,
         options=(Option("ai", "Let AI sort shops Joe doesn't know", True,
                         "Joe sorts well-known names himself; the writing model gets only the shop names, never "
                         "your amounts or account numbers."),),
         needs=("ollama",), ready=True,
         help="Download your statement as CSV (or Excel) from your bank's website, one or more months or accounts. "
              "Joe's own code reads it, works out money in and out, spending by category and month, the biggest "
              "payments, and finds regular payments (weekly, monthly, yearly) with their cost a year and any price "
              "rises. All the math is Joe's, never the AI's. You get budget.md to read and two CSVs to open in a "
              "spreadsheet (change any category there). Your statement is never changed and never leaves this "
              "computer.",
         plan_hint="Budget from a bank statement / where does my money go / find my subscriptions: TYPE: bank-budget, "
                   "INPUT: the bank CSV or Excel file(s), OPTIONS: ai (unless they say no AI), else none. No CHUNKS.",
         examples=("Turn my bank statement into a budget", "Which subscriptions am I paying for?",
                   "Where did my money go last month?")),
    Tool("resume-tailor", "Resume tailor", "Writing",
         "Your resume and a job posting in; a matched resume, cover letter and gap list out. Nothing invented.",
         accepts=DOC_EXT,
         options=(Option("letter", "Write a cover letter", True),
                  Option("word", "Word copies too", True, "Needs Pandoc (Setup > System check).")),
         needs=("ollama",), ready=True,
         help="Give your resume and the job posting (paste it in the box, or add it as a second file with 'job' in "
              "its name). Joe lists what the job asks for and finds each one in your resume, quoting the line (each "
              "quote checked word for word). The tailored resume puts your matching experience first in the job's "
              "words, and never adds a job, skill, number or result you don't have: anything that isn't in your "
              "resume is marked [CHECK: not in your resume], and the gaps are listed so you can decide. Your "
              "resume file is never changed.",
         plan_hint="Tailor a resume / CV to a job posting, with a cover letter: TYPE: resume-tailor, INPUT: the resume "
                   "file (and the posting file if they have one), OPTIONS: letter, word (unless they don't want "
                   "them), FORMAT: the job posting, word for word, if they pasted it. No CHUNKS.",
         examples=("Tailor my resume to this job posting", "Write a cover letter for this job from my CV"),
         extra_label="The job posting (paste it here)",
         extra_hint="Paste the whole job posting here, or add it as a file with 'job' in its name"),
    Tool("mail-merge", "Mail merge", "Files",
         "One letter and a spreadsheet of names in: a personal letter for every row out.",
         accepts=(".docx", ".txt", ".md", ".csv", ".tsv", ".xlsx"),
         options=(Option("one", "Also one file with every letter", True, "Ready to print in one go."),
                  Option("blank", "Leave empty cells blank", False,
                         "Off: a row with an empty cell gets [CHECK: no ...] so nothing goes out half-done.")),
         needs=(), ready=True,
         help="No AI, nothing invented. In your letter, put a column name from the spreadsheet in curly brackets "
              "where it should go: Dear {First name}, ... your order {Order number}. (<<Name>> and «Name» work "
              "too, and the letter can be Word, .txt or .md.) Joe makes one letter per row in the letters folder, "
              "keeping your Word formatting, plus one file with all of them. Any {spot} that doesn't match a column "
              "is listed. Your letter and spreadsheet are never changed.",
         plan_hint="Mail merge / personalised letters from a list: TYPE: mail-merge, INPUT: the letter file and the "
                   "spreadsheet (both), OPTIONS: one (unless they want separate files only), blank (only if they "
                   "want empty cells left blank). No CHUNKS.",
         examples=("Make a letter for everyone on this list", "Merge my thank-you note with the customer spreadsheet")),
    Tool("alt-text", "Picture descriptions (alt text)", "Pictures",
         "A short description of each picture, for screen readers, websites and shop listings.",
         accepts=PHOTO_EXT,
         options=(Option("long", "Also a longer description", True),
                  Option("sidecar", "A .txt for each picture", False, "Named like the picture, for upload tools.")),
         needs=("ollama", "vision"), ready=True,
         help=VISION_HELP_TEXT + " Each short description is one sentence of 125 characters or less (what screen "
              "readers handle best), most important thing first, without 'image of'. Joe never names or guesses "
              "who people are. Say what the pictures are for in the box (like: my pottery shop) for better words. "
              "Saved as alt-text.csv (for spreadsheets and shop uploads) and alt-text.md.",
         plan_hint="Alt text / picture descriptions for screen readers, a website or shop listings: TYPE: alt-text, "
                   "INPUT: the picture(s) or folder, OPTIONS: long, sidecar (only if they want a file per picture), "
                   "FORMAT: what the pictures are for, if they said. No CHUNKS.",
         examples=("Write alt text for my website photos", "Describe these pictures for a blind reader"),
         extra_label="What are the pictures for? (optional)", extra_hint="e.g. product photos for my pottery shop"),
    Tool("duplicate-photos", "Duplicate photo finder", "Pictures",
         "Finds copies and near-copies of photos and suggests the best one to keep. Nothing is deleted.",
         accepts=PHOTO_EXT,
         options=(Option("how", "How alike", choices=(("exact", "Exact copies only"),
                                                      ("close", "Copies, also resized or re-saved"),
                                                      ("loose", "Similar shots too (bursts)")), value="close"),
                  Option("sheets", "Side-by-side pictures of each group", True),
                  Option("copy", "Copy the keepers into a clean folder", False,
                         "The best of each group plus every one-of-a-kind photo. Copies only.")),
         needs=("ffmpeg",), ready=True,
         help="No AI. Joe compares every photo's bytes (exact copies) and a tiny fingerprint of how it looks "
              "(near copies), then suggests a keeper for each group: the biggest picture, then the sharpest, then "
              "the one with the plainest name, and says why. Nothing is moved or deleted: you get duplicates.md "
              "with a side-by-side picture of each group, and a CSV, so you decide. Without FFmpeg only exact "
              "copies are found. Drop a whole folder.",
         plan_hint="Find duplicate / similar photos and which to keep: TYPE: duplicate-photos, INPUT: the photo "
                   "folder(s) or files, OPTIONS: how exact|close|loose (close if not said), sheets, copy (only if "
                   "they want the keepers copied out). No CHUNKS.",
         examples=("Find the duplicate photos in my phone dump", "Which of these burst shots should I keep?")),
)}
GROUPS = ("Writing", "Pictures", "Video", "Audio", "Files")


def ready_ids() -> tuple[str, ...]:
    return tuple(t.id for t in TOOLS.values() if t.ready)


def is_tool(type_: str) -> bool:
    return type_ in TOOLS


def catalog() -> list[dict]:
    """What the Tools tab shows."""
    return [{"id": t.id, "name": t.name, "group": t.group, "blurb": t.blurb, "ready": t.ready,
             "accepts": list(t.accepts), "help": t.help, "examples": list(t.examples),
             "needs": list(t.needs), "extra_hint": t.extra_hint, "mark": t.mark,
             "packs": list(_packs_for(t.id)),
             "no_input": t.id in NO_INPUT_OK,
             "extra_label": t.extra_label,
             "options": [{"key": o.key, "label": o.label, "default": o.default, "hint": o.hint,
                          "choices": [list(c) for c in o.choices], "value": o.value, "multi": o.multi}
                         for o in t.options]}
            for t in TOOLS.values()]


def _packs_for(tid: str) -> tuple[str, ...]:
    from .picturetools import TOOL_PACKS
    return TOOL_PACKS.get(tid, ())


def planner_lines() -> str:
    return "\n".join(f"- {t.plan_hint}" for t in TOOLS.values() if t.ready and t.plan_hint)


def option_ok(tool: Tool, token: str) -> bool:
    """Is this OPTIONS entry one the tool knows ('none', a tick box, or 'key value')?"""
    if token == "none":
        return True
    key, _, val = token.partition(" ")
    for o in tool.options:
        if o.key == key:
            return (val in {c[0] for c in o.choices}) if o.choices else not val
    return False


def missing_required(tool: Tool, tokens: list[str]) -> str:
    """A plain problem when a must-pick option (like the language) wasn't given ('' = fine)."""
    for o in tool.options:
        if o.required and not any(t.partition(" ")[0] == o.key and t.partition(" ")[2] for t in tokens):
            if tool.id in ("translate", "dub-video"):
                return "say which language to translate into, e.g. OPTIONS: to spanish (on the Tools tab, tick a language)"
            return f"pick a {o.label.lower()} (OPTIONS: {o.key} ...)"
    return ""


def options_help(tool: Tool) -> str:
    out = []
    for o in tool.options:
        out.append(f"{o.key} {'|'.join(c[0] for c in o.choices)}" if o.choices else o.key)
    return ", ".join(out + ["none"])


def chosen_options(job: "Job") -> set[str]:
    """Tick boxes that are on. With no OPTIONS line, each box's default is used."""
    tool = TOOLS[job.type]
    boxes = [o for o in tool.options if not o.choices]
    if job.options:
        return {t for t in job.options if any(t == o.key for o in boxes)}
    return {o.key for o in boxes if o.default}


def option_values(job: "Job", key: str) -> list[str]:
    """Every pick for a several-picks option ('to' -> ['spanish', 'french']), in order."""
    out = []
    for t in job.options:
        k, _, v = t.partition(" ")
        if k == key and v and v not in out:
            out.append(v)
    return out


def option_value(job: "Job", key: str) -> str:
    """The pick for a pick-one option ('size' -> '1600'), or its default."""
    for t in job.options:
        k, _, v = t.partition(" ")
        if k == key and v:
            return v
    return next((o.value for o in TOOLS[job.type].options if o.key == key), "")


# --------------------------------------------------------------------------- inputs
def tool_exts() -> tuple[str, ...]:
    """Every kind of file a ready tool reads."""
    return tuple(sorted({e for t in TOOLS.values() if t.ready for e in t.accepts}))


def inbox_media(sb, kinds: tuple[str, ...] | None = None, limit: int = 40) -> list[str]:
    """Files waiting in Inbox that tools can use (newest first), as INPUT paths, for the
    describe planner. `kinds` narrows it (default: everything a ready tool reads)."""
    kinds = kinds or tool_exts()
    out = []
    try:
        files = [p for p in sb.inbox.rglob("*") if p.is_file() and p.suffix.lower() in kinds]
    except OSError:
        return []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[:limit]:
        out.append(str(p.relative_to(sb.inbox)).replace("\\", "/"))
    return out


def resolve_inputs(engine: "Engine", job: "Job") -> tuple[list[Path], list[str]]:
    """INPUT entries -> files this tool accepts (folders are expanded). Returns (files, problems)."""
    from .sandbox import SandboxError
    tool = TOOLS[job.type]
    files: list[Path] = []
    problems: list[str] = []
    from . import filing
    for rel in job.inputs:
        try:
            p = engine.sb.resolve_input(filing.translate_input(engine, rel))
        except SandboxError as e:
            problems.append(f"{rel}: {e}")
            continue
        if p.is_dir():
            found = sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in tool.accepts
                           and not any(part.startswith(".") for part in f.relative_to(p).parts)
                           and _inside(engine.sb, f))
            if not found:
                problems.append(f"{rel}: no files Joe can use in that folder")
            files.extend(found)
        elif p.is_file():
            if p.suffix.lower() in tool.accepts:
                files.append(p)
            else:
                problems.append(f"{rel}: {p.suffix or 'that kind of file'} isn't something this tool reads")
        else:
            problems.append(f"{rel}: not found in Inbox")
    seen: set[Path] = set()
    unique = [f for f in files if not (f in seen or seen.add(f))]
    return unique, problems


def _inside(sb, f: Path) -> bool:
    """A file found inside a folder is only used when it really is in the workspace (a shortcut/link
    pointing somewhere else on the computer is skipped)."""
    from .sandbox import SandboxError
    try:
        sb.check(f)
        sb.check_not_private(f)
    except SandboxError:
        return False
    return True


def _key(engine: "Engine", src: Path) -> str:
    """How a file is named in progress notes: its path in Inbox, or (for a file in another
    workspace folder, like Output/...) its path from the workspace."""
    for base in (engine.sb.inbox, engine.sb.root):
        try:
            return str(src.relative_to(base)).replace("\\", "/")
        except ValueError:
            continue
    return src.name


def tool_dir(engine: "Engine", job: "Job", st: "JobState") -> Path:
    """The task's output folder; resuming reuses it, a new run never mixes with an old one."""
    if st.output and st.titles:
        p = engine.sb.resolve(st.output)
        p.mkdir(parents=True, exist_ok=True)
        return p
    from . import filing
    cand = filing.place(engine, job, "folder")                     # Setup > General > HOW JOE FILES HIS WORK
    if cand is None:
        target = engine._under_output(engine.sb.resolve(job.save))  # like text tasks: always inside Output
        if target.suffix:
            target = target.with_suffix("")
        cand, n = target, 2
        while cand.exists() and any(cand.iterdir()):
            cand = target.with_name(f"{target.name}_v{n}")
            n += 1
    cand.mkdir(parents=True, exist_ok=True)
    st.output = str(cand.relative_to(engine.sb.output)).replace("\\", "/")
    return cand


# --------------------------------------------------------------------------- run
def run(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    fn = {"transcribe": run_transcribe, "read-aloud": run_read_aloud,
          "proofread": run_proofread, "photo-batch": run_photo_batch,
          "translate": run_translate, "tidy-sheet": run_tidy_sheet,
          "photo-listing": run_photo_listing, "read-scans": run_read_scans,
          "sort-photos": run_sort_photos, "ask-files": run_ask_files}.get(job.type)
    from . import avtools, writetools
    if job.type in writetools.WRITE_TOOLS:
        fn = writetools.run
    if job.type in avtools.AV_TOOLS:
        fn = avtools.run
    from . import filetools
    if job.type in filetools.FILE_TOOLS:
        fn = filetools.run
    if job.type == "find-book":
        from . import books
        fn = books.run
    if job.type == "make-shorts":
        from . import shorts
        fn = shorts.run
    from . import picturetools
    if job.type in picturetools.COMFY_TOOLS:
        fn = picturetools.run
    from . import community
    if community.is_addon_tool(job.type):
        fn = community.run
    if job.type == "joe-language":
        from . import i18n
        fn = i18n.run
    from . import paperwork
    if job.type in paperwork.PAPER_TOOLS:
        fn = paperwork.run
    if not fn:
        st.status, st.note = "failed", f"the {TOOLS[job.type].name} tool isn't built yet"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    return fn(engine, mission, job, st)


def _finish(engine: "Engine", job: "Job", st: "JobState", total: int, failed: list[str]) -> "JobState":
    from dataclasses import asdict  # noqa: F401  (keeps the import local like the engine)
    done = len(st.titles)
    st.parts_total = total
    st.parts_done = done
    st.status = "done" if done == total and not failed else ("partial" if done else "failed")
    if failed:
        st.note = "; ".join(failed)[:400]
    st.finished = datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"Finished '{job.name}': {done} of {total} done" + (f" ({st.note})" if failed else ""))
    return st


# --------------------------------------------------------------------------- transcribe
NOTES_SYSTEM = """You write clear notes from a transcript of a recording. Use only what is said in
the transcript. Never invent names, numbers, dates or decisions; if something is unclear, write
[CHECK]. Plain, friendly words. Markdown headings and bullet points."""
NOTES_FORMAT = """Write:
## Summary
3-6 sentences.
## Key points
Bullet points.
## Decisions
Bullet points, or "None mentioned."
## To-dos
Bullet points with who and when if said, or "None mentioned."
"""
NOTES_CHUNK_WORDS = 2500


def how_long(seconds: float) -> str:
    """'33 s', '4 min', '1 h 20 min' (no more 'about 1 min' / '0.0 min' for short files)."""
    s = max(0, round(seconds))
    if s < 90:
        return f"{max(1, s)} s"
    m = round(s / 60)
    return f"{m} min" if m < 90 else f"{m // 60} h" + (f" {m % 60} min" if m % 60 else "")


def _ts(seconds: float, srt: bool = False) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    if srt:
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def hearing_model(stt_model: str, language: str) -> str:
    """The Whisper model for a recording: English-only models (*.en) for English, their
    all-languages twin (base.en -> base) for anything else or 'find out by itself'."""
    name = stt_model or "base.en"
    if language != "english" and name.endswith(".en"):
        return name[:-3]
    return name


HEARING_TOOLS = ("transcribe", "make-shorts", "tidy-speech", "edit-words", "dub-video", "b-roll",
                 "meeting-minutes")


def hearing_backend(settings) -> str:
    """'whisper.cpp' or 'faster-whisper' for long recordings (Setup > Voice & Talk > Transcribe with)."""
    from . import whispercpp
    want = getattr(settings.voice, "transcriber", "auto") or "auto"
    if want == "faster-whisper":
        return "faster-whisper"
    if whispercpp.exe():
        return "whisper.cpp"
    return "faster-whisper"


def hear(engine, wav: Path, model: str, lang_code: str, words: bool = False, timeout: float = 3600) -> dict:
    """One 16 kHz WAV -> timed segments (and word times when asked), with whichever transcriber is set."""
    if hearing_backend(engine.s) == "whisper.cpp":
        from . import whispercpp
        return whispercpp.transcribe(wav, model, lang_code, words=words, log=engine.log, timeout=timeout)
    from .addons import VoiceWorker
    worker = engine.voice or VoiceWorker(engine.log)
    req = {"cmd": "transcribe", "audio": str(wav), "stt_model": model, "language": lang_code}
    if words:
        req["words"] = True
    return worker.call(req, timeout=timeout)


def hearing_ready(settings, voice_ok: bool | None = None) -> bool:
    if hearing_backend(settings) == "whisper.cpp":
        return True
    if voice_ok is None:
        from .addons import voice_python
        voice_ok = Path(voice_python()).exists()
    return bool(voice_ok)


def whisper_language(language: str) -> str:
    """Whisper's language code for a pick ('' = let Whisper find out)."""
    return WHISPER_CODES.get(language, "")


def code_language(code: str) -> str:
    """A plain language name from Whisper's code ('es' -> 'Spanish'); '' if unknown."""
    for v, c in WHISPER_CODES.items():
        if c == code:
            return language_name(v)
    return ""


def transcript_text(segments: list[dict], title: str, language: str = "") -> str:
    """Readable transcript: a [mm:ss] stamp at the start of each paragraph. A new paragraph
    starts after a pause of 2+ seconds or about 120 words."""
    out = [f"# {title}", ""] + ([f"Language: {language}", ""] if language else [])
    para: list[str] = []
    start = 0.0
    last_end = None
    words = 0
    for seg in segments:
        text = (seg.get("t") or "").strip()
        if not text:
            continue
        gap = seg["s"] - last_end if last_end is not None else 0
        if para and (gap >= 2.0 or words >= 120):
            out += [f"[{_ts(start)}] " + " ".join(para), ""]
            para, words = [], 0
        if not para:
            start = seg["s"]
        para.append(text)
        words += len(text.split())
        last_end = seg["e"]
    if para:
        out += [f"[{_ts(start)}] " + " ".join(para), ""]
    return "\n".join(out)


def srt_text(segments: list[dict]) -> str:
    blocks = []
    n = 0
    for seg in segments:
        text = (seg.get("t") or "").strip()
        if not text:
            continue
        n += 1
        end = max(seg["e"], seg["s"] + 0.5)
        blocks.append(f"{n}\n{_ts(seg['s'], True)} --> {_ts(end, True)}\n{text}\n")
    return "\n".join(blocks)


def _to_wav(ffmpeg: str | None, src: Path, dest: Path, log) -> Path | None:
    """16 kHz mono WAV for Whisper. A .wav goes straight through when there's no FFmpeg."""
    if not ffmpeg:
        return src if src.suffix.lower() == ".wav" else None
    from .system import no_window_flags
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        p = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1",
                            "-ar", "16000", "-c:a", "pcm_s16le", str(dest)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=7200,
                           creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError) as e:
        log(f"  FFmpeg couldn't read {src.name}: {e}")
        return None
    if p.returncode != 0 or not dest.exists():
        log(f"  FFmpeg couldn't read {src.name}: {(p.stderr or '').strip()[-200:]}")
        return None
    return dest


def _wav_seconds(p: Path) -> float:
    try:
        return max(0.0, (p.stat().st_size - 44) / 32000)       # 16 kHz, 16-bit, mono
    except OSError:
        return 0.0


def _notes(engine: "Engine", job: "Job", st: "JobState", title: str, transcript: str,
           write_in: str = "English") -> str:
    """Notes from the transcript; long recordings are noted in pieces, then combined.
    `write_in` is the language the notes are written in."""
    words = transcript.split()
    pieces = [" ".join(words[i:i + NOTES_CHUNK_WORDS])
              for i in range(0, len(words), NOTES_CHUNK_WORDS)] or [""]
    extra = (job.format.strip() + "\n") if job.format.strip() else ""
    rules = (job.rules.strip() + "\n") if job.rules.strip() else ""
    if write_in and write_in != "English":
        rules += (f"Write the notes in {write_in}, headings too (Summary, Key points, Decisions, "
                  f"To-dos, translated into {write_in}).\n")
    if len(pieces) == 1:
        r = engine._chat(job, 0, "transcribe-notes", NOTES_SYSTEM + "\n" + rules,
                         f"Recording: {title}\n\n{NOTES_FORMAT}{extra}\nTRANSCRIPT:\n{pieces[0]}", st)
        return r.text.strip()
    partial = []
    for i, piece in enumerate(pieces):
        engine._progress(f"{job.name}: notes for {title}, piece {i + 1}/{len(pieces)}")
        r = engine._chat(job, i, "transcribe-notes", NOTES_SYSTEM + "\n" + rules,
                         f"Recording: {title} (piece {i + 1} of {len(pieces)})\n"
                         "Write bullet-point notes of everything important in this piece.\n\n"
                         f"TRANSCRIPT PIECE:\n{piece}", st)
        partial.append(r.text.strip())
    r = engine._chat(job, len(pieces), "transcribe-notes", NOTES_SYSTEM + "\n" + rules,
                     f"Recording: {title}\nThese are notes from each piece of one long recording, "
                     f"in order. Combine them.\n\n{NOTES_FORMAT}{extra}\nNOTES:\n" + "\n\n".join(partial), st)
    return r.text.strip()


def run_transcribe(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .doctor import ffmpeg_exe
    from .engine import PartFailed, Stopped
    from .mission import slug

    files, problems = resolve_inputs(engine, job)
    for pr in problems:
        engine.log(f"  INPUT: {pr}")
    if not files:
        st.status, st.note = "failed", ("no recordings to transcribe" + (f" ({problems[0]})" if problems else
                                        "; add them with INPUT: (files or a folder in Inbox)"))
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    if not hearing_ready(engine.s) and engine.voice is None:
        st.status, st.note = "failed", "transcribing needs Joe's voice add-on or whisper.cpp (Setup > System check)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    ffmpeg = ffmpeg_exe(engine.s.comfy.ffmpeg)
    if not ffmpeg and any(f.suffix.lower() != ".wav" for f in files):
        engine.log("  FFmpeg isn't installed, so only .wav recordings can be read "
                   "(Setup > System check installs it).")
    folder = tool_dir(engine, job, st)
    opts = chosen_options(job)
    lang = option_value(job, "language") or "english"
    if lang not in WHISPER_CODES and lang != "auto":
        lang = "english"
    model = hearing_model(engine.s.voice.stt_model, lang)
    notes_in = option_value(job, "notes-in") or "same"
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}': {len(files)} recording(s) "
               f"-> {st.output} (hearing: {model}, "
               f"{'finding the language' if lang == 'auto' else language_name(lang)})")
    if not model.endswith(".en"):
        engine.log(f"  Other languages use Whisper's all-languages model ({model}); the first "
                   "time, it downloads once from Hugging Face (only the model, never your recording).")
    notes_ok = None                                    # checked once, only if notes are wanted
    failed: list[str] = []
    tmp = engine.meta / "tmp"
    try:
        for i, src in enumerate(files):
            key = _key(engine, src)
            if key in st.titles:
                continue                                # done in an earlier run
            if engine.stop.is_set():
                raise Stopped()
            engine._progress(f"{job.name}: {i + 1}/{len(files)} {src.name}")
            engine.log(f"  {i + 1}/{len(files)} {src.name}: reading the sound...")
            wav = _to_wav(ffmpeg, src, tmp / (slug(src.stem) + ".wav"), engine.log)
            if not wav:
                failed.append(f"{src.name}: couldn't read the sound")
                continue
            secs = _wav_seconds(wav)
            engine.log(f"  {src.name}: transcribing {how_long(secs)} of sound...")
            t0 = datetime.now()
            r = hear(engine, wav, model, whisper_language(lang),
                     timeout=max(900.0, secs * 4 + 600) + (0 if model.endswith(".en") else 1800))
            if wav != src:
                try:
                    wav.unlink()
                except OSError:
                    pass
            if not r.get("ok"):
                failed.append(f"{src.name}: {r.get('error', 'transcribing failed')}"[:200])
                engine.log(f"  {src.name}: {r.get('error', 'transcribing failed')}")
                continue
            segs = r.get("segments") or []
            stem = unique_stem(files, i)
            heard = code_language(r.get("language") or "") or (
                language_name(lang) if lang != "auto" else "")
            if lang == "auto" and heard:
                engine.log(f"  {src.name}: sounds like {heard}")
            body = transcript_text(segs, src.stem, "" if heard in ("", "English") and lang == "english" else heard)
            atomic_write_text(folder / f"{stem}.txt", body)
            made = [f"{stem}.txt"]
            if "subtitles" in opts:
                atomic_write_text(folder / f"{stem}.srt", srt_text(segs))
                made.append(f"{stem}.srt")
            words = sum(count_words(s.get("t", "")) for s in segs)
            took = (datetime.now() - t0).total_seconds()
            engine._record(job=job.job_id, part=i + 1, kind="transcribe", model=model, ok=True,
                           seconds=round(took, 1), audio_seconds=round(secs, 1), words=words)
            if "notes" in opts and words:
                if notes_ok is None:
                    notes_ok = engine._text_ready(st)
                    if not notes_ok:
                        st.status, st.note = "running", ""
                        engine.log("  Notes skipped: the writing model isn't available.")
                if notes_ok:
                    try:
                        notes = _notes(engine, job, st, src.stem,
                                       " ".join(s.get("t", "").strip() for s in segs),
                                       "English" if notes_in == "english" else (heard or "English"))
                        atomic_write_text(folder / f"{stem}-notes.md", f"# Notes: {src.stem}\n\n{notes}\n")
                        made.append(f"{stem}-notes.md")
                        st.flags.extend({"item": src.stem, "flag": f} for f in find_flags(notes))
                    except PartFailed as e:
                        failed.append(f"{src.name}: notes skipped ({e})")
            st.titles.append(key)
            st.media_files.extend(made)
            st.items += 1
            st.words += words
            engine._save_state(job, st)
            engine.log(f"  {src.name}: {words} words in {how_long(took)} -> {', '.join(made)}")
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {len(files)} recording(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    return _finish(engine, job, st, len(files), failed)


# --------------------------------------------------------------------------- documents
DOC_LIMIT = 3_000_000                 # characters read from one document (a whole book)
RAW_TEXT_EXT = (".txt", ".md", ".markdown")


def document_text(src: Path, log) -> str:
    """All the words in a document. Plain text and Markdown come back exactly as written
    (so a proofread copy changes nothing but the fixes); Word, PDF and web pages are
    read with the same code as Talk attachments. Raises ValueError if it can't be read."""
    if src.suffix.lower() in RAW_TEXT_EXT:
        raw = src.read_bytes()
        if b"\x00" in raw[:4096]:
            raise ValueError("that file isn't plain text")
        return raw.decode("utf-8-sig", "replace").replace("\r\n", "\n")
    from .attach import extract
    text = extract(src, log, limit=DOC_LIMIT)["text"]
    if src.suffix.lower() == ".docx":                 # one Word paragraph per line -> a blank
        text = re.sub(r"\n+", "\n\n", text)          # line between, so copies keep paragraphs
    return text


def _guess_words(f: Path) -> int:
    """A quick word count for time guesses, without reading the whole document."""
    try:
        size = f.stat().st_size
    except OSError:
        return 0
    ext = f.suffix.lower()
    if ext == ".docx":
        try:
            from .attach import _docx_text
            return count_words(_docx_text(f))
        except Exception:                               # noqa: BLE001 (a guess only)
            return size // 20
    if ext == ".pdf":
        return max(200, size // 60)
    if ext in (".html", ".htm"):
        return size // 12
    return size // 6


# --------------------------------------------------------------------------- read aloud
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+|www\.\S+")
_FLAG = re.compile(r"\[(?:CHECK|TODO|TK)\b[^\]]*\]", re.I)
_BULLET = re.compile(r"^([-*+•]|\d+[.)])\s+")
_CHAPTER = re.compile(r"^(?:#{1,2}[ \t]+\S[^\n]*|(?:chapter|part)[ \t]+(?:\d+|[ivxlc]+|one|two|three|four|"
                      r"five|six|seven|eight|nine|ten|eleven|twelve)\b[^\n]{0,80})$", re.I | re.M)
SPEECH_PIECE = 4500                   # characters per call to the voice helper (it takes 6000)
LISTEN_WPM = 160                      # words per minute of speech, for time guesses


def speakable(text: str) -> str:
    """Writing -> words worth saying: no Markdown symbols, links, code blocks or [CHECK]
    marks; titles and list lines end with a full stop so the voice pauses."""
    text = re.sub(r"(?s)```.*?```", " ", text)
    out: list[str] = []
    for line in text.splitlines():
        ln = line.strip()
        if not ln:
            out.append("")
            continue
        if re.fullmatch(r"[-*_=|:+\s]{3,}", ln):        # rules and table separator lines
            continue
        heading = bool(re.match(r"#{1,6}\s", ln))
        ln = re.sub(r"^#{1,6}\s*", "", ln)
        ln = re.sub(r"^>\s*", "", ln)
        listed = bool(_BULLET.match(ln))
        ln = _BULLET.sub("", ln)
        if ln.count("|") >= 2:                           # a table row: say the cells
            ln = ", ".join(c.strip() for c in ln.strip("|").split("|") if c.strip())
            listed = True
        ln = _MD_LINK.sub(r"\1", ln)
        ln = _URL.sub("", ln)
        ln = _FLAG.sub("", ln)
        ln = re.sub(r"[*`~]+|(?<!\w)_+|_+(?!\w)", "", ln)
        ln = re.sub(r"\s{2,}", " ", ln).strip()
        if not ln:
            continue
        if (heading or listed) and ln[-1] not in ".!?:;,":
            ln += "."
        out += ["", ln, ""] if heading else [ln]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def speech_pieces(text: str, size: int = SPEECH_PIECE) -> list[str]:
    """Paragraphs grouped into pieces the voice helper can say in one go."""
    out: list[str] = []
    cur = ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        while len(para) > size:                          # a huge paragraph: cut at a sentence
            cut = max(para.rfind(". ", 0, size), para.rfind("? ", 0, size), para.rfind("! ", 0, size))
            if cut < size // 3:
                cut = para.rfind(" ", 0, size)
            if cut <= 0:
                cut = size - 1
            if cur:
                out.append(cur)
                cur = ""
            out.append(para[:cut + 1].strip())
            para = para[cut + 1:].strip()
        if cur and len(cur) + len(para) + 2 > size:
            out.append(cur)
            cur = para
        else:
            cur = (cur + "\n\n" + para).strip()
    if cur:
        out.append(cur)
    return out


def split_sections(text: str) -> list[tuple[str, str]]:
    """(title, text) per chapter, split at '# Title' / '## Title' / 'Chapter 3' lines.
    Fewer than two such lines = one section."""
    marks = [m.start() for m in _CHAPTER.finditer(text)]
    if len(marks) < 2:
        return [("", text)]
    out = []
    if text[:marks[0]].strip():
        out.append(("Opening", text[:marks[0]]))
    for a, b in zip(marks, marks[1:] + [len(text)]):
        part = text[a:b]
        out.append((part.splitlines()[0].lstrip("#").strip(), part))
    return out


def _wav_ok(p: Path) -> bool:
    try:
        return p.stat().st_size > 44
    except OSError:
        return False


def merge_wavs(parts: list[Path], dest: Path, pause: float = 0.45) -> float:
    """Join WAV pieces (same format) with a short pause between them. Returns seconds."""
    import wave
    fmt = None
    frames = 0
    with wave.open(str(dest), "wb") as out:
        for i, p in enumerate(parts):
            with wave.open(str(p), "rb") as w:
                f = (w.getnchannels(), w.getsampwidth(), w.getframerate())
                if fmt is None:
                    fmt = f
                    out.setnchannels(f[0])
                    out.setsampwidth(f[1])
                    out.setframerate(f[2])
                elif f != fmt:
                    raise ValueError(f"{p.name} is a different kind of WAV")
                if i:
                    gap = int(fmt[2] * pause)
                    out.writeframes(b"\x00" * gap * fmt[0] * fmt[1])
                    frames += gap
                n = w.getnframes()
                out.writeframes(w.readframes(n))
                frames += n
    return frames / fmt[2] if fmt else 0.0


def to_mp3(ffmpeg: str, wav: Path, mp3: Path, title: str, log) -> bool:
    from .system import no_window_flags
    try:
        p = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(wav), "-codec:a", "libmp3lame",
                            "-q:a", "4", "-metadata", f"title={title[:120]}",
                            "-metadata", "artist=Read aloud by Joe", str(mp3)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600,
                           creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError) as e:
        log(f"  FFmpeg couldn't make the MP3: {e}")
        return False
    if p.returncode != 0 or not mp3.exists():
        log(f"  FFmpeg couldn't make the MP3: {(p.stderr or '').strip()[-200:]}")
        return False
    return True


def _voice_missing(engine: "Engine", job: "Job", st: "JobState", what: str) -> bool:
    from .addons import voice_python
    if not Path(voice_python()).exists() and engine.voice is None:
        st.status, st.note = "failed", f"{what} needs Joe's voice add-on (Setup > System check)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return True
    return False


def _no_files(engine: "Engine", job: "Job", st: "JobState", what: str) -> "JobState | None":
    files, problems = resolve_inputs(engine, job)
    for pr in problems:
        engine.log(f"  INPUT: {pr}")
    if files:
        return None
    st.status, st.note = "failed", (f"no {what}" + (f" ({problems[0]})" if problems else
                                    "; add them with INPUT: (files or a folder in Inbox)"))
    engine.log(f"'{job.name}' failed: {st.note}")
    return st


def run_read_aloud(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    import hashlib
    import shutil
    import wave

    from .addons import VOICES, VoiceWorker
    from .doctor import ffmpeg_exe
    from .engine import Stopped
    from .mission import slug

    if (bad := _no_files(engine, job, st, "documents to read")) is not None:
        return bad
    if _voice_missing(engine, job, st, "reading aloud"):
        return st
    files, _ = resolve_inputs(engine, job)
    ffmpeg = ffmpeg_exe(engine.s.comfy.ffmpeg)
    if not ffmpeg:
        engine.log("  FFmpeg isn't installed, so Joe saves WAV files (much bigger) instead of MP3 "
                   "(Setup > System check installs it).")
    folder = tool_dir(engine, job, st)
    opts = chosen_options(job)
    worker = engine.voice or VoiceWorker(engine.log)
    v = engine.s.voice
    voice = v.voice if v.voice in VOICES else "am_adam"
    if v.voice == "mine":
        engine.log(f"  Your own voice isn't used for reading aloud yet, so Joe reads with {voice}.")
    speed = float(v.speed or 1.0)
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}': {len(files)} document(s) "
               f"-> {st.output} (voice: {voice})")
    failed: list[str] = []
    work = engine.meta / "tmp" / "read-aloud" / job.job_id
    try:
        for i, src in enumerate(files):
            key = _key(engine, src)
            if key in st.titles:
                continue
            if engine.stop.is_set():
                raise Stopped()
            engine._progress(f"{job.name}: {i + 1}/{len(files)} {src.name}")
            try:
                raw = document_text(src, engine.log)
            except (ValueError, OSError) as e:
                failed.append(f"{src.name}: {e}"[:200])
                engine.log(f"  {src.name}: {e}")
                continue
            sections = split_sections(raw) if "chapters" in opts else [("", raw)]
            plan = [(title, pcs) for title, body in sections if (pcs := speech_pieces(speakable(body)))]
            if not plan:
                failed.append(f"{src.name}: no words to read")
                engine.log(f"  {src.name}: no words to read")
                continue
            total = sum(len(p) for _, p in plan)
            words = sum(count_words(x) for _, p in plan for x in p)
            engine.log(f"  {i + 1}/{len(files)} {src.name}: {words} words, about "
                       f"{how_long(words / LISTEN_WPM * 60)} of listening"
                       + (f" in {len(plan)} tracks" if len(plan) > 1 else ""))
            stem = unique_stem(files, i)
            sig = hashlib.sha1(f"{raw}|{voice}|{speed}|{sorted(opts)}".encode("utf-8", "replace")).hexdigest()[:10]
            tmp = work / f"{stem}-{sig}"                 # finished pieces survive a stop
            tmp.mkdir(parents=True, exist_ok=True)
            t0 = datetime.now()
            made: list[str] = []
            audio = 0.0
            n = 0
            broke = ""
            for si, (title, pcs) in enumerate(plan):
                wavs = []
                for pi, text in enumerate(pcs):
                    if engine.stop.is_set():
                        raise Stopped()
                    n += 1
                    w = tmp / f"s{si + 1:03d}-p{pi + 1:04d}.wav"
                    if not _wav_ok(w):
                        engine._progress(f"{job.name}: {src.name}, piece {n}/{total}")
                        r = worker.call({"cmd": "tts", "text": text, "out": str(w), "voice": voice,
                                         "speed": speed}, timeout=max(600.0, len(text) * 0.5))
                        if not r.get("ok") or not _wav_ok(w):
                            broke = r.get("error") or "the voice didn't make any sound"
                            break
                    wavs.append(w)
                if broke:
                    break
                name = stem if len(plan) == 1 else \
                    f"{stem}-{si + 1:02d}" + (f"-{slug(title)[:40]}" if slug(title) else "")
                merged = tmp / f"{name}.wav"
                try:
                    audio += merge_wavs(wavs, merged)
                except (OSError, ValueError, EOFError, wave.Error) as e:
                    broke = f"couldn't join the pieces: {e}"
                    break
                label = (title or src.stem) if len(plan) > 1 else src.stem
                if ffmpeg and to_mp3(ffmpeg, merged, folder / f"{name}.mp3", label, engine.log):
                    made.append(f"{name}.mp3")
                else:
                    shutil.move(str(merged), str(folder / f"{name}.wav"))
                    made.append(f"{name}.wav")
            if broke:
                failed.append(f"{src.name}: {broke}"[:200])
                engine.log(f"  {src.name}: {broke}")
                continue                                 # pieces kept: a re-run carries on
            took = (datetime.now() - t0).total_seconds()
            engine._record(job=job.job_id, part=i + 1, kind="read-aloud", model=f"kokoro:{voice}",
                           ok=True, seconds=round(took, 1), audio_seconds=round(audio, 1), words=words)
            shutil.rmtree(tmp, ignore_errors=True)
            st.titles.append(key)
            st.media_files.extend(made)
            st.items += 1
            st.words += words
            engine._save_state(job, st)
            engine.log(f"  {src.name}: {how_long(audio)} of speech in {how_long(took)} "
                       f"-> {', '.join(made)}")
    except Stopped:
        st.status, st.note = "stopped", (f"stopped after {len(st.titles)} of {len(files)} document(s); "
                                         "finished pieces are kept, so the next run carries on")
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    return _finish(engine, job, st, len(files), failed)


# --------------------------------------------------------------------------- proofread
PROOF_SYSTEM = """You are a careful proofreader. You fix real mistakes only: spelling, grammar,
punctuation, wrong or missing words, repeated words.{clarity} You never rewrite the writing in
your own style: keep the writer's voice, tone, word choices, spelling style and formatting.
Never add facts. Never change names, web addresses, email addresses or words spelled out the way
they are spoken (like "dot com"): leave them exactly as written. Don't change a verb's tense
unless it is clearly a mistake. Reply with ONLY a JSON array, nothing before or after it."""
PROOF_CLARITY = (" You may also fix sentences that are confusing or awkward, changing as few "
                 "words as you can.")
PROOF_ASK = """Proofread the text between <<< and >>>.
For each fix, give one object:
  {"find": "the exact words from the text, copied exactly, enough words to be unique",
   "replace": "the corrected words",
   "why": "a few plain words, e.g. spelling"}
Only list words that need changing: never list a sentence that is already correct.
If something might be wrong but you aren't sure, put the same words in find and replace and say
in "why" what might be wrong, starting with "unsure:". If there is nothing to fix, reply [].
"""
PROOF_WORDS = 600                     # words per model call
MAX_FIND = 400                        # longer "find"s are rewrites, not fixes: never applied


def proof_chunks(text: str, words: int = PROOF_WORDS) -> list[str]:
    """Paragraph groups of about `words` words; "".join(chunks) == text exactly."""
    bits = re.split(r"(\n[ \t]*\n)", text)
    out: list[str] = []
    cur, n = "", 0
    for b in bits:
        w = count_words(b)
        if cur and n + w > words and b.strip():
            out.append(cur)
            cur, n = "", 0
        cur += b
        n += w
    if cur:
        out.append(cur)
    return out


def proof_halves(engine, job, ci: int, system: str, wish: str, chunk: str, st) -> list[dict] | None:
    """Proofread a part that keeps failing as two smaller halves (split at a paragraph)."""
    paras = chunk.strip().split("\n\n")
    if len(paras) < 2:
        return None
    from .engine import PartFailed
    mid = len(paras) // 2
    out: list[dict] = []
    for half in ("\n\n".join(paras[:mid]), "\n\n".join(paras[mid:])):
        try:
            r = engine._chat(job, ci, "proofread", system,
                             f"{wish}{PROOF_ASK}\n<<<\n{half}\n>>>\n\nReply with ONLY the JSON array.", st)
        except PartFailed:
            return None
        got = parse_changes(r.text)
        if got is None:
            return None
        out += got
    return out


def parse_changes(raw: str) -> list[dict] | None:
    """The model's JSON list of fixes, or None if the reply isn't one."""
    import json
    raw = re.sub(r"(?s)<think>.*?</think>", "", raw or "")
    raw = re.sub(r"```[\w-]*", "", raw)
    a, b = raw.find("["), raw.rfind("]")
    if a < 0 or b < a:
        return None
    body = raw[a:b + 1]
    arr = None
    for text in (body, re.sub(r'\\(?![\\"/bfnrtu])', r"\\\\", body)):   # stray backslashes (C:\Users)
        try:
            arr = json.loads(text, strict=False)
            break
        except json.JSONDecodeError:
            continue
    if arr is None:                                # one broken entry: keep the ones that parse
        arr = []
        for m in re.finditer(r"\{[^{}]*\}", body):
            try:
                arr.append(json.loads(re.sub(r'\\(?![\\"/bfnrtu])', r"\\\\", m.group(0)), strict=False))
            except json.JSONDecodeError:
                pass
        if not arr and re.search(r"\{", body):
            return None
    if not isinstance(arr, list):
        return None
    return [{"find": o["find"], "replace": o["replace"], "why": str(o.get("why") or "").strip()[:120]}
            for o in arr if isinstance(o, dict) and isinstance(o.get("find"), str)
            and isinstance(o.get("replace"), str) and o["find"].strip()]


_QUOTES = {"'": "['‘’]", '"': "[\"“”]", "‘": "['‘’]",
           "’": "['‘’]", "“": "[\"“”]", "”": "[\"“”]",
           "-": "[-–—]", "–": "[-–—]", "—": "[-–—]"}


def loose_find(text: str, find: str, ignore_case: bool = False):
    """Where `find` is in `text` when only spacing, line breaks, curly vs straight quotes
    or dash kinds differ (the model retypes the words it quotes). One match only."""
    parts = []
    for ch in find.strip():
        if ch.isspace():
            if not parts or parts[-1] != r"\s+":
                parts.append(r"\s+")
        else:
            parts.append(_QUOTES.get(ch, re.escape(ch)))
    if not parts:
        return None
    found = list(re.finditer("".join(parts), text, re.I if ignore_case else 0))
    return found[0] if len(found) == 1 else None


_DOUBT = re.compile(r"unsure|not sure|might|maybe|possibly|check|unclear|ambiguous|confirm|verify|\?")
_LABEL_ONLY = re.compile(r"^\s*(?:spelling|grammar|punctuation|capitali[sz]ation|typo|style|clarity|"
                         r"wording|word choice|repeated words?|missing words?)\s*[.:]?\s*$", re.I)


# "unsure: possibly missing word" with no word named: noise (big test: 3 of 3 were fine sentences)
_VAGUE_MISSING = re.compile(r"^\s*(?:unsure:\s*)?(?:possibly|maybe|perhaps|might be|could be)?\s*"
                            r"(?:an?\s+)?missing\s+(?:an?\s+)?words?\b(?!\s*['\"‘“])", re.I)


def is_doubt(why: str) -> bool:
    """A no-change entry worth showing: it says what might be wrong (not just 'spelling')."""
    why = (why or "").strip()
    if _VAGUE_MISSING.match(why):
        return False
    return bool(why) and not _LABEL_ONLY.match(why) and bool(_DOUBT.search(why.lower()) or len(why) > 25)


def _same_case(original: str, new: str) -> str:
    """`new` with its first letter in the case `original` has (the model often lowercases the
    start of what it quotes)."""
    if original[:1].isalpha() and new[:1].isalpha():
        return (new[0].upper() if original[0].isupper() else new[0].lower()) + new[1:]
    return new


_WEBBY = re.compile(r"(?i)https?://|www\.|@|\b[\w-]+\.(?:com|org|net|edu|gov|io|ai|co|uk|us|info|app|dev)\b|"
                    r"\bdot\s+(?:com|org|net|edu|gov|io|ai|co)\b")


def touches_name(find: str, replace: str) -> bool:
    """A fix that would change a web address, an email, a spoken-out address ('dot com') or a
    name: proofreading turned 'Sunny Day Cafe dot com' into 'SunnyDayCafeO.com'. Those are left alone."""
    if find == replace:
        return False
    if _WEBBY.search(find) and " ".join(_WEBBY.findall(find)).lower() != " ".join(_WEBBY.findall(replace)).lower():
        return True
    if _WEBBY.search(find) or _WEBBY.search(replace):
        fw = re.findall(r"\S+", find)
        def webby(ws):
            return [w.rstrip(".,;:!?)\"'’”") for w in ws if _WEBBY.search(w)]
        if webby(fw) != webby(re.findall(r"\S+", replace)):
            return True
    words = re.findall(r"[A-Za-z][\w'’-]*", find)
    rwords = set(re.findall(r"[A-Za-z][\w'’-]*", replace))
    for n, w in enumerate(words):
        if n == 0 or w == "I" or not w[0].isupper():
            continue                                     # first word: a sentence start, not a name
        before = find[:find.find(w)].rstrip()
        if before.endswith((".", "!", "?", ":", "\n")):
            continue
        if w not in rwords:
            return True
    return False


def apply_changes(text: str, changes: list[dict], first_par: int = 1) -> tuple[str, list, list, list]:
    """Apply exact-match fixes. Returns (text, applied, noted, missed); each change gets a
    paragraph number ("par"). Nothing is changed that isn't on the applied list."""
    applied, noted, missed = [], [], []
    for c in changes:
        f, r = c["find"], c["replace"]
        pos = text.find(f)
        if pos < 0 and f != r:
            m = loose_find(text, f)
            if m:
                pos, f = m.start(), m.group(0)
        if pos < 0 and f != r:
            m = loose_find(text, f, ignore_case=True)
            if m:
                found = m.group(0)
                rest = text[m.start():m.start() + len(r)]
                if found.lower() == r.lower() or " ".join(rest.split()).lower() == " ".join(r.split()).lower():
                    continue                      # the text already says that: nothing to fix
                pos, f, r = m.start(), found, _same_case(found, r)
                c = dict(c, replace=r)
        par = first_par + (len(re.findall(r"\n[ \t]*\n", text[:pos])) if pos >= 0 else 0)
        c = dict(c, par=par if pos >= 0 else 0)
        if f != r and touches_name(f, r):
            noted.append(dict(c, why=(c.get("why") or "suggested") + f" → {_q(r)}; not changed: names and "
                                     "web addresses are left as written"))
            continue
        if f == r:
            if is_doubt(c.get("why", "")):
                noted.append(c)                   # a real question for the reader
            # else: the model listed a correct sentence ("spelling") with nothing to change: drop it
        elif len(f) > MAX_FIND:
            missed.append(dict(c, reason="too much to change at once"))
        elif pos < 0:
            missed.append(dict(c, reason="couldn't find those exact words"))
        else:
            text = text[:pos] + r + text[pos + len(f):]
            applied.append(c)
    return text, applied, noted, missed


def _q(s: str) -> str:
    s = " ".join(s.split())
    return "“" + (s if len(s) <= 300 else s[:297] + "...") + "”"


def changes_report(title: str, applied: list, noted: list, missed: list, copy_name: str,
                   skipped: list[int]) -> str:
    n = len(applied)
    lines = [f"# Proofread: {title}", "",
             f"{n} change{'' if n == 1 else 's'}. Your original file was not changed."
             + (f" The corrected copy is {copy_name}." if copy_name and n else ""), ""]
    if skipped:
        lines += [f"Joe couldn't check part(s) {', '.join(map(str, skipped))} of this document "
                  "(the model's answer didn't make sense). Those parts are unchanged.", ""]
    lines += ["## Changes", ""]
    lines += [f"{i}. Paragraph {c['par']}" + (f" ({c['why']})" if c["why"] else "") +
              f": {_q(c['find'])} → {_q(c['replace'])}" for i, c in enumerate(applied, 1)] or ["None needed."]
    if noted:
        lines += ["", "## Worth a look (not changed)", ""]
        lines += ["- " + (f"Paragraph {c['par']}: " if c["par"] else "") + _q(c["find"]) +
                  (f": {c['why']}" if c["why"] else "") for c in noted]
    if missed:
        lines += ["", "## Suggestions Joe couldn't apply (check these yourself)", ""]
        lines += [f"- {_q(c['find'])} → {_q(c['replace'])}" + (f" ({c['why']})" if c["why"] else "") +
                  f": {c['reason']}" for c in missed]
    return "\n".join(lines) + "\n"


def run_proofread(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .addons import export_document, pandoc_exe
    from .engine import PartFailed, Stopped

    if (bad := _no_files(engine, job, st, "documents to proofread")) is not None:
        return bad
    files, _ = resolve_inputs(engine, job)
    if not engine._text_ready(st):
        engine._save_state(job, st)
        return st
    folder = tool_dir(engine, job, st)
    opts = chosen_options(job)
    system = PROOF_SYSTEM.replace("{clarity}", PROOF_CLARITY if "clarity" in opts else "")
    if job.rules.strip():
        system += "\n" + job.rules.strip()
    wish = f"The writer asked: {job.format.strip()}\n" if job.format.strip() else ""
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}': {len(files)} document(s) "
               f"-> {st.output}" + (" (also clearer wording)" if "clarity" in opts else ""))
    failed: list[str] = []
    try:
        for i, src in enumerate(files):
            key = _key(engine, src)
            if key in st.titles:
                continue
            if engine.stop.is_set():
                raise Stopped()
            try:
                text = document_text(src, engine.log)
            except (ValueError, OSError) as e:
                failed.append(f"{src.name}: {e}"[:200])
                engine.log(f"  {src.name}: {e}")
                continue
            if not text.strip():
                failed.append(f"{src.name}: no words to check")
                continue
            chunks = proof_chunks(text)
            words = count_words(text)
            engine.log(f"  {i + 1}/{len(files)} {src.name}: {words} words in {len(chunks)} part(s)")
            fixed: list[str] = []
            applied, noted, missed, skipped = [], [], [], []
            par = 1
            for ci, chunk in enumerate(chunks):
                if engine.stop.is_set():
                    raise Stopped()
                engine._progress(f"{job.name}: {src.name}, part {ci + 1}/{len(chunks)}")
                changes = None
                if chunk.strip():
                    ask = f"{wish}{PROOF_ASK}\n<<<\n{chunk.strip()}\n>>>"
                    try:
                        for attempt in range(2):
                            r = engine._chat(job, ci, "proofread", system, ask if not attempt else
                                             ask + "\n\nReply with ONLY the JSON array.", st)
                            changes = parse_changes(r.text)
                            if changes is not None:
                                break
                            st.retries += 1
                    except PartFailed as e:
                        engine.log(f"  {src.name} part {ci + 1}: {e}")
                    if changes is None:                  # last try: the part in two halves
                        changes = proof_halves(engine, job, ci, system, wish, chunk, st)
                    if changes is None:
                        skipped.append(ci + 1)
                        changes = []
                new, a, nt, m = apply_changes(chunk, changes, par)
                fixed.append(new)
                applied += a
                noted += nt
                missed += m
                par += len(re.findall(r"\n[ \t]*\n", chunk))
            stem = unique_stem(files, i)
            ext = src.suffix.lower() if src.suffix.lower() in RAW_TEXT_EXT else ".md"
            made = []
            copy_name = ""
            if "copy" in opts:
                copy_name = f"{stem}-proofread{ext}"
                atomic_write_text(folder / copy_name, "".join(fixed))
                made.append(copy_name)
                if src.suffix.lower() == ".docx":
                    pandoc = pandoc_exe(engine.s.pandoc)
                    if pandoc:
                        made += [p.name for p in export_document(folder / copy_name, ["docx"], pandoc, engine.log, settings=engine.s, cache=engine.meta / "templates")]
                    else:
                        engine.log("  Pandoc isn't installed, so the corrected copy is text, not Word.")
            atomic_write_text(folder / f"{stem}-changes.md",
                              changes_report(src.stem, applied, noted, missed, copy_name, skipped))
            made.insert(0, f"{stem}-changes.md")
            st.flags.extend({"item": src.stem, "flag": f"[CHECK] {c['why'] or 'worth a look'}: {c['find'][:80]}"}
                            for c in noted[:20])
            if skipped:
                failed.append(f"{src.name}: couldn't check part(s) {', '.join(map(str, skipped))}")
            st.titles.append(key)
            st.media_files.extend(made)
            st.items += 1
            st.words += words
            engine._save_state(job, st)
            engine.log(f"  {src.name}: {len(applied)} change(s), {len(noted)} to look at, "
                       f"{len(missed)} not applied -> {', '.join(made)}")
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {len(files)} document(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    return _finish(engine, job, st, len(files), failed)


# --------------------------------------------------------------------------- photo batch
MARK_OPACITY = 0.55                   # watermarks are faint: there to claim, not to ruin the photo


def jpeg_orientation(p: Path) -> int:
    """The EXIF 'which way is up' number (1-8) from a JPEG, or 1. Phones store photos
    sideways and set this, so copies must be turned the same way."""
    import struct
    try:
        with open(p, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                return 1
            while True:
                head = f.read(4)
                if len(head) < 4 or head[0] != 0xFF:
                    return 1
                marker, size = head[1], struct.unpack(">H", head[2:])[0]
                if marker == 0xE1:
                    data = f.read(size - 2)
                    if not data.startswith(b"Exif\x00\x00"):
                        continue
                    t = data[6:]
                    e = "<" if t[:2] == b"II" else ">"
                    off = struct.unpack(e + "I", t[4:8])[0]
                    n = struct.unpack(e + "H", t[off:off + 2])[0]
                    for i in range(n):
                        ent = t[off + 2 + i * 12: off + 14 + i * 12]
                        if struct.unpack(e + "H", ent[:2])[0] == 0x0112:
                            v = struct.unpack(e + "H", ent[8:10])[0]
                            return v if 1 <= v <= 8 else 1
                    return 1
                if marker in (0xDA, 0xD9):                  # picture data starts: no EXIF
                    return 1
                f.seek(size - 2, 1)
    except (OSError, struct.error, IndexError):
        return 1


_TURN = {2: "hflip", 3: "hflip,vflip", 4: "vflip", 5: "transpose=0", 6: "transpose=1",
         7: "transpose=3", 8: "transpose=2"}


def image_size(ffmpeg: str, p: Path) -> tuple[int, int] | None:
    from .system import no_window_flags
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-noautorotate", "-i", str(p)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", r.stderr or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def fit_size(w: int, h: int, longest: int | None) -> tuple[int, int]:
    """Shrink so the longest side is at most `longest` (never enlarge)."""
    if not longest or max(w, h) <= longest:
        return w, h
    k = longest / max(w, h)
    return max(1, round(w * k)), max(1, round(h * k))


def unique_stem(files: list[Path], i: int) -> str:
    """File i's name for its results; two 'notes.txt' (or notes.txt and notes.md) never share one."""
    from .mission import slug
    from .picturetools import unique_stems
    return unique_stems([{"stem": slug(f.stem)} for f in files])[i]["stem"]


def _ff_path(p: Path | str) -> str:
    """A path inside an FFmpeg filter: forward slashes, ':' and quotes escaped."""
    s = str(p).replace("\\", "/").replace(":", "\\:")
    # inside '...' nothing is escaped, and a filter graph is read twice: close the quote, add a
    # twice-escaped ' (\\\'), open it again. Checked with FFmpeg on a path like O'Brien.
    return "'" + s.replace("'", "'" + "\\\\\\'" + "'") + "'"


def _spot(corner: str, w: str, h: str, m: str) -> tuple[str, str]:
    """x, y expressions for a mark of size w x h with margin m."""
    x = {"left": m, "right": f"W-{w}-{m}"}.get(corner.split("-")[-1], f"(W-{w})/2")
    y = {"top": m, "bottom": f"H-{h}-{m}"}.get(corner.split("-")[0], f"(H-{h})/2")
    return x, y


def photo_command(ffmpeg: str, src: Path, dest: Path, size: tuple[int, int], turn: int,
                  fmt: str, mark_text_file: Path | None, logo: Path | None, font: Path | None,
                  corner: str) -> list[str]:
    """One FFmpeg call: turn the right way up, shrink, flatten see-through parts onto white
    for JPG, add a faint watermark if asked, leave hidden details (GPS, camera) out."""
    W, H = size
    cmd = [ffmpeg, "-y", "-v", "error", "-noautorotate", "-i", str(src)]
    chain = [f"[0:v]{_TURN[turn] + ',' if turn in _TURN else ''}scale={W}:{H}:flags=lanczos,format=rgba[a]"]
    last, n = "a", 1
    if fmt == "jpg":                                       # no see-through in JPG: white behind
        cmd += ["-f", "lavfi", "-i", f"color=c=white:s={W}x{H}:d=1"]
        chain.append(f"[{n}:v][{last}]overlay=format=auto,format=rgba[b]")
        last, n = "b", n + 1
    m = max(8, round(min(W, H) / 40))
    if logo:
        cmd += ["-i", str(logo)]
        lw = max(16, round(min(W, H) * 0.22))
        x, y = _spot(corner, "w", "h", str(m))
        chain.append(f"[{n}:v]scale={lw}:-1,format=rgba,colorchannelmixer=aa={MARK_OPACITY}[lg]")
        chain.append(f"[{last}][lg]overlay=x={x}:y={y}[c]")
        last, n = "c", n + 1
    elif mark_text_file and font:
        fs = max(12, round(min(W, H) / 20))
        x, y = _spot(corner, "tw", "th", str(m))
        chain.append(f"[{last}]drawtext=fontfile={_ff_path(font)}:textfile={_ff_path(mark_text_file)}"
                     f":expansion=none:fontsize={fs}:fontcolor=white@{MARK_OPACITY}:borderw={max(1, fs // 14)}"
                     f":bordercolor=black@{MARK_OPACITY * 0.6}:x={x}:y={y}[c]")
        last = "c"
    pix = {"jpg": "yuvj444p", "png": "rgba", "webp": "yuva420p"}.get(fmt, "rgba")
    if fmt == "bmp":
        pix = "bgr24"
    elif fmt == "tiff":
        pix = "rgba"
    chain.append(f"[{last}]format={pix}[out]")
    cmd += ["-filter_complex", ";".join(chain), "-map", "[out]", "-map_metadata", "-1",
            "-frames:v", "1", "-update", "1"]
    if fmt == "jpg":
        cmd += ["-q:v", "2"]
    elif fmt == "webp":
        cmd += ["-c:v", "libwebp", "-quality", "82"]
    elif fmt == "png":
        cmd += ["-compression_level", "9"]
    return cmd + [str(dest)]


def run_photo_batch(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .doctor import ffmpeg_exe
    from .engine import Stopped
    from .mission import slug
    from .sandbox import SandboxError
    from .system import font_file, no_window_flags

    if (bad := _no_files(engine, job, st, "photos to work on")) is not None:
        return bad
    files, _ = resolve_inputs(engine, job)
    ffmpeg = ffmpeg_exe(engine.s.comfy.ffmpeg)
    if not ffmpeg:
        st.status, st.note = "failed", "photo tools need FFmpeg (Setup > System check installs it)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    size_opt = option_value(job, "size")
    longest = int(size_opt) if size_opt.isdigit() else None
    fmt_opt = option_value(job, "format")
    corner = option_value(job, "corner") or "bottom-right"
    opts = chosen_options(job)
    logo = None
    text_file = None
    font = None
    mark = job.watermark.strip()
    if mark:
        if mark.lower().endswith(".png"):
            try:
                logo = engine.sb.resolve_input(mark)
            except SandboxError:
                logo = None
            if not logo or not logo.is_file():
                st.status, st.note = "failed", f"the watermark logo {mark} isn't in Inbox"
                engine.log(f"'{job.name}' failed: {st.note}")
                return st
            files = [f for f in files if f != logo]           # the logo isn't one of the photos
        else:
            font = font_file()
            if not font:
                engine.log("  No font found on this computer, so the watermark text is left off.")
    folder = tool_dir(engine, job, st)
    if mark and not logo and font:
        text_file = engine.meta / "tmp" / f"mark-{job.job_id}.txt"
        text_file.parent.mkdir(parents=True, exist_ok=True)
        text_file.write_text(mark, encoding="utf-8")
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}': {len(files)} photo(s) -> {st.output} "
               f"({'keep size' if not longest else f'{longest} px'}, {fmt_opt}"
               + (f", watermark {corner}" if mark else "") + ")")
    failed: list[str] = []
    used = {p.name.lower() for p in folder.iterdir()} if folder.exists() else set()
    base = slug(job.name) or "photo"
    t0 = datetime.now()
    try:
        for i, src in enumerate(files):
            key = _key(engine, src)
            if key in st.titles:
                continue
            if engine.stop.is_set():
                raise Stopped()
            engine._progress(f"{job.name}: {i + 1}/{len(files)} {src.name}")
            ext = src.suffix.lower().lstrip(".")
            fmt = {"jpeg": "jpg", "tif": "tiff"}.get(ext, ext) if fmt_opt == "same" else fmt_opt
            stem = f"{base}-{i + 1:0{max(2, len(str(len(files))))}d}" if "rename" in opts \
                else (slug(src.stem) or f"photo-{i + 1}")
            name, n = f"{stem}.{fmt}", 2
            while name.lower() in used:
                name, n = f"{stem}_{n}.{fmt}", n + 1
            dims = image_size(ffmpeg, src)
            if not dims:
                failed.append(f"{src.name}: couldn't open the picture")
                engine.log(f"  {src.name}: couldn't open the picture")
                continue
            turn = jpeg_orientation(src) if ext in ("jpg", "jpeg") else 1
            w, h = (dims[1], dims[0]) if turn >= 5 else dims
            out = fit_size(w, h, longest)
            cmd = photo_command(ffmpeg, src, folder / name, out, turn, fmt, text_file, logo, font, corner)
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                                   creationflags=no_window_flags())
                ok = p.returncode == 0 and (folder / name).exists()
                err = (p.stderr or "").strip().splitlines()[-1:] if not ok else []
            except (OSError, subprocess.SubprocessError) as e:
                ok, err = False, [str(e)]
            if not ok:
                failed.append(f"{src.name}: {(err or ['FFmpeg failed'])[0][:160]}")
                engine.log(f"  {src.name}: FFmpeg failed: {(err or ['?'])[0][:200]}")
                continue
            used.add(name.lower())
            before, after = src.stat().st_size, (folder / name).stat().st_size
            st.titles.append(key)
            st.media_files.append(name)
            st.items += 1
            engine._save_state(job, st)
            engine.log(f"  {src.name} ({dims[0]}x{dims[1]}, {before // 1024} KB) -> {name} "
                       f"({out[0]}x{out[1]}, {after // 1024} KB)")
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {len(files)} photo(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    finally:
        if text_file:
            try:
                text_file.unlink()
            except OSError:
                pass
    engine._record(job=job.job_id, part=1, kind="photo-batch", model="ffmpeg", ok=True,
                   seconds=round((datetime.now() - t0).total_seconds(), 1), photos=len(st.titles))
    return _finish(engine, job, st, len(files), failed)


# --------------------------------------------------------------------------- translate
TRANSLATE_SYSTEM = """You are a careful translator. Translate the writer's text into {lang}.
Keep the meaning, tone and formatting exactly: the same paragraphs, Markdown headings, lists,
bold and tables. Keep names, brands, numbers, prices, dates, email addresses and links as they
are. Never add, explain or leave anything out. If a phrase can't be translated well (a joke,
an idiom, a word you don't know), translate it as well as you can and put [CHECK] right after it.
Reply with ONLY the translation."""
TRANSLATE_ASK = "Translate the text between <<< and >>> into {lang}.\n\n<<<\n{text}\n>>>"
TRANSLATE_WORDS = 400                 # words per model call (translations run long)
_PREAMBLE = re.compile(r"^\s*(?:sure|here(?:'s| is)|translation|okay|ok)\b[^\n]{0,80}:\s*\n", re.I)


def clean_translation(raw: str) -> str:
    """The model's reply without thinking, fences, a 'Here is the translation:' line or
    the <<< >>> marks it was shown."""
    t = re.sub(r"(?s)<think>.*?</think>", "", raw or "")
    t = _PREAMBLE.sub("", t.strip(), count=1)
    t = re.sub(r"^\s*```[\w-]*\n|\n```\s*$", "", t.strip())
    t = re.sub(r"^\s*<<<\s*\n?|\n?\s*>>>\s*$", "", t)
    return t.strip()


def language_name(v: str) -> str:
    return dict(LANGUAGES).get(v, v.capitalize())


def translation_note(lang: str, model: str) -> str:
    return (f"> Translated into {lang} by Joe on this computer ({model or 'the writing model'}). "
            "Machine translations make mistakes: have someone who speaks the language check it "
            "before you publish it. Unsure bits are marked [CHECK].\n\n")


def run_translate(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .addons import export_document, pandoc_exe
    from .engine import PartFailed, Stopped
    from .mission import slug

    if (bad := _no_files(engine, job, st, "documents to translate")) is not None:
        return bad
    files, _ = resolve_inputs(engine, job)
    langs = option_values(job, "to")
    if not langs:
        st.status, st.note = "failed", "no language picked (OPTIONS: to spanish)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    if not engine._text_ready(st):
        engine._save_state(job, st)
        return st
    folder = tool_dir(engine, job, st)
    wish = f"The writer asked: {job.format.strip()}\n" if job.format.strip() else ""
    total = len(files) * len(langs)
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}': {len(files)} document(s) into "
               f"{', '.join(language_name(x) for x in langs)} -> {st.output}")
    failed: list[str] = []
    model = getattr(engine, "text_model", "") or engine.s.ollama.text_model
    try:
        for i, src in enumerate(files):
            rel = _key(engine, src)
            todo = [x for x in langs if f"{rel} -> {x}" not in st.titles]
            if not todo:
                continue
            try:
                text = document_text(src, engine.log)
            except (ValueError, OSError) as e:
                failed += [f"{src.name}: {e}"[:200]]
                engine.log(f"  {src.name}: {e}")
                continue
            if not text.strip():
                failed.append(f"{src.name}: no words to translate")
                continue
            chunks = proof_chunks(text, TRANSLATE_WORDS)
            words = count_words(text)
            stem = unique_stem(files, i)
            ext = src.suffix.lower() if src.suffix.lower() in RAW_TEXT_EXT else ".md"
            for lang in todo:
                if engine.stop.is_set():
                    raise Stopped()
                name = language_name(lang)
                system = TRANSLATE_SYSTEM.replace("{lang}", name)
                if job.rules.strip():
                    system += "\n" + job.rules.strip()
                engine.log(f"  {src.name} -> {name}: {words} words in {len(chunks)} part(s)")
                out: list[str] = []
                broke = ""
                for ci, chunk in enumerate(chunks):
                    if engine.stop.is_set():
                        raise Stopped()
                    body = chunk.strip()
                    if not body:
                        out.append(chunk)
                        continue
                    lead = chunk[:len(chunk) - len(chunk.lstrip())]
                    trail = chunk[len(chunk.rstrip()):]
                    engine._progress(f"{job.name}: {src.name} -> {name}, part {ci + 1}/{len(chunks)}")
                    got = ""
                    try:
                        for attempt in range(2):
                            ask = wish + TRANSLATE_ASK.format(lang=name, text=body)
                            if attempt:
                                ask += "\n\nReply with ONLY the translated text, nothing else."
                            r = engine._chat(job, ci, "translate", system, ask, st)
                            got = clean_translation(r.text)
                            # far shorter than the text = something left out (by letters, not
                            # words: Chinese and Japanese don't put spaces between words)
                            if got and len(got) >= len(body) * 0.2:
                                break
                            st.retries += 1
                    except PartFailed as e:
                        broke = str(e)
                        break
                    if not got:
                        broke = f"part {ci + 1} came back empty"
                        break
                    out.append(lead + got + trail)
                if broke:
                    failed.append(f"{src.name} -> {name}: {broke}"[:200])
                    engine.log(f"  {src.name} -> {name}: {broke}")
                    continue
                done = "".join(out)
                fname = f"{stem}-{slug(lang)}{ext}"
                atomic_write_text(folder / fname, translation_note(name, model) + done
                                  + ("" if done.endswith("\n") else "\n"))
                made = [fname]
                if src.suffix.lower() == ".docx":
                    pandoc = pandoc_exe(engine.s.pandoc)
                    if pandoc:
                        made += [p.name for p in export_document(folder / fname, ["docx"], pandoc, engine.log, settings=engine.s, cache=engine.meta / "templates")]
                flags = find_flags(done)
                st.flags.extend({"item": f"{src.stem} ({name})", "flag": f} for f in flags[:30])
                st.titles.append(f"{rel} -> {lang}")
                st.media_files.extend(made)
                st.items += 1
                st.words += count_words(done)
                engine._save_state(job, st)
                engine.log(f"  {src.name} -> {name}: {', '.join(made)}"
                           + (f" ({len(flags)} [CHECK] mark(s) to look at)" if flags else ""))
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {total} translation(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    return _finish(engine, job, st, total, failed)


# --------------------------------------------------------------------------- tidy a spreadsheet
SHEET_ROWS = 40                       # rows per model call
_SPLIT = re.compile(r"split\s+(?:the\s+)?[\"']?(.+?)[\"']?\s+(?:column\s+)?into\s+(.+?)\s*(?:[.;\n]|$)", re.I)
_CATS = re.compile(r"categor(?:y|ies)\s*(?:are|:|=)\s*(.+?)\s*(?:[.;\n]|$)", re.I)
SPELL_SYSTEM = """You fix spelling mistakes in spreadsheet cells. Fix only clearly misspelled
ordinary words. Never change numbers, codes, prices, dates, emails, links, people's names or
brand names, and never reword anything. Reply with ONLY a JSON array, nothing else."""
SPELL_ASK = """Rows of a spreadsheet as JSON (row = the row number):
{rows}

List each fix as {{"row": <row number>, "column": "<column name>", "find": "the misspelled
word(s) exactly as written", "replace": "the fixed word(s)"}}. If nothing needs fixing, reply []."""
CAT_SYSTEM = """You sort spreadsheet rows into categories. Use only what the row says; never guess
beyond it. Reply with ONLY JSON, nothing else."""
FILL_SYSTEM = """You split one spreadsheet column into new columns. Copy the words exactly as they
are written in the cell; never invent, look up or correct anything. If a part isn't there,
leave it "". Reply with ONLY a JSON array, nothing else."""


def parse_json_list(raw: str, of=dict) -> list | None:
    """A JSON array from a model reply (of dicts, or of strings), or None."""
    import json
    raw = re.sub(r"(?s)<think>.*?</think>", "", raw or "")
    raw = re.sub(r"```[\w-]*", "", raw)
    a, b = raw.find("["), raw.rfind("]")
    if a < 0 or b < a:
        return None
    try:
        arr = json.loads(raw[a:b + 1])
    except json.JSONDecodeError:
        return None
    return [x for x in arr if isinstance(x, of)] if isinstance(arr, list) else None


def tidy_cell(v: str) -> str:
    return re.sub(r"[ \t ]{2,}", " ", v.replace(" ", " ").replace("\r", "")).strip()


def match_case(header: list[str], rows: list[list[str]]) -> list[str]:
    """In columns of repeated short labels (Category, Color...), make the same word look the same:
    "mugs", "Mugs" and "MUGS" all become the most common way it's written. Returns what changed."""
    from collections import Counter
    changed: list[str] = []
    for c in range(len(header)):
        vals = [r[c].strip() for r in rows if c < len(r) and r[c].strip()]
        if len(vals) < 4 or any(re.search(r"\d", v) or len(v) > 30 for v in vals):
            continue
        if len({v.casefold() for v in vals}) > 0.7 * len(vals):
            continue
        count = Counter(vals)
        best: dict[str, str] = {}
        for v in vals:                                   # most common form; first seen wins a tie
            k = v.casefold()
            if k not in best or count[v] > count[best[k]]:
                best[k] = v
        n = 0
        for r in rows:
            if c < len(r) and r[c].strip() and best[r[c].strip().casefold()] != r[c].strip():
                r[c] = best[r[c].strip().casefold()]
                n += 1
        if n:
            changed.append(f"{header[c]}: {n} cell{'' if n == 1 else 's'}")
    return changed


def real_spelling_fix(find: str, rep: str) -> bool:
    """A spelling fix, not a capital letter, a plural or a written-out short form (those aren't
    spelling, and the model applied them to some rows but not others)."""
    a, b = find.strip().casefold(), rep.strip().casefold()
    return bool(a and b) and a != b and not a.startswith(b) and not b.startswith(a)


def dedupe_rows(rows: list[list[str]]) -> tuple[list[int], list[int]]:
    """(kept, dropped) row indexes. Rows that match after ignoring case and spacing are
    duplicates; the first one stays."""
    seen: set[tuple] = set()
    kept, dropped = [], []
    for i, r in enumerate(rows):
        key = tuple(" ".join(c.split()).casefold() for c in r)
        (dropped if key in seen else kept).append(i)
        seen.add(key)
    return kept, dropped


def text_columns(header: list[str], rows: list[list[str]]) -> list[int]:
    """Columns that hold ordinary words (not numbers, codes, emails or links)."""
    out = []
    for c in range(len(header)):
        vals = [r[c] for r in rows if r[c].strip()][:500]
        if not vals:
            continue
        wordy = sum(1 for v in vals if re.search(r"[^\W\d_]{3,}", v) and "@" not in v
                    and not re.match(r"(https?://|www\.)", v.strip(), re.I))
        if wordy >= len(vals) * 0.6:
            out.append(c)
    return out


def split_request(fmt: str, header: list[str]) -> tuple[int, list[str]] | None:
    """'split Name into First name, Last name' -> (column index, new names)."""
    m = _SPLIT.search(fmt or "")
    if not m:
        return None
    want = m.group(1).strip().lower()
    col = next((i for i, h in enumerate(header) if h.lower() == want), None)
    if col is None:
        return None
    parts = [x.strip(" \"'") for x in re.split(r",|\band\b|/", m.group(2)) if x.strip(" \"'")]
    return (col, parts[:6]) if len(parts) >= 2 else None


def given_categories(fmt: str) -> list[str]:
    m = _CATS.search(fmt or "")
    return [x.strip(" \"'") for x in re.split(r",|/|\bor\b", m.group(1)) if x.strip(" \"'")][:30] if m else []


def _ask_list(engine: "Engine", job: "Job", st: "JobState", part: int, kind: str, system: str,
              ask: str, of=dict) -> list | None:
    from .engine import PartFailed
    try:
        for attempt in range(2):
            r = engine._chat(job, part, kind, system, ask if not attempt else
                             ask + "\n\nReply with ONLY the JSON array.", st)
            got = parse_json_list(r.text, of)
            if got is not None:
                return got
            st.retries += 1
    except PartFailed as e:
        engine.log(f"  {kind}: {e}")
    return None


def tidy_report(title: str, notes: list[str], dropped: list[tuple[int, str]], fixes: list[str],
                cats: dict[str, int], unsure: list[str], out_name: str) -> str:
    L = [f"# Tidied: {title}", "", f"The tidy copy is {out_name}. Your original file was not changed.", ""]
    L += [f"- {n}" for n in notes] + [""]
    if dropped:
        L += [f"## Duplicate rows removed ({len(dropped)})", ""]
        L += [f"- Row {r}: {_q(v)}" for r, v in dropped[:300]]
        L += ([f"- ...and {len(dropped) - 300} more"] if len(dropped) > 300 else []) + [""]
    if fixes:
        L += [f"## Spelling fixed ({len(fixes)})", ""] + [f"- {f}" for f in fixes[:500]] + [""]
    if cats:
        L += ["## Categories", ""] + [f"- {k}: {v} row{'' if v == 1 else 's'}"
                                      for k, v in sorted(cats.items(), key=lambda x: -x[1])] + [""]
    if unsure:
        L += [f"## Worth a look ({len(unsure)})", ""] + [f"- {u}" for u in unsure[:300]] + [""]
    return "\n".join(L)


def run_tidy_sheet(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .engine import Stopped
    from .sheets import SheetError, read_table, write_csv

    if (bad := _no_files(engine, job, st, "spreadsheets to tidy")) is not None:
        return bad
    files, _ = resolve_inputs(engine, job)
    opts = chosen_options(job)
    needs_model = bool(opts & {"spelling", "categorize", "split"})
    if needs_model and not engine._text_ready(st):
        engine._save_state(job, st)
        return st
    folder = tool_dir(engine, job, st)
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}': {len(files)} spreadsheet(s) "
               f"-> {st.output} ({', '.join(sorted(opts)) or 'no changes picked'})")
    failed: list[str] = []
    rules = ("\n" + job.rules.strip()) if job.rules.strip() else ""
    try:
        for i, src in enumerate(files):
            key = _key(engine, src)
            if key in st.titles:
                continue
            if engine.stop.is_set():
                raise Stopped()
            try:
                header, rows, cut = read_table(src)
            except (SheetError, OSError, ValueError) as e:
                failed.append(f"{src.name}: {e}"[:200])
                engine.log(f"  {src.name}: {e}")
                continue
            engine.log(f"  {i + 1}/{len(files)} {src.name}: {len(rows)} rows, {len(header)} columns")
            notes = [f"{len(rows)} rows and {len(header)} columns read."]
            if cut:
                notes.append("The sheet was longer than Joe reads at once; only the first rows were tidied.")
            unsure: list[str] = []
            fixes: list[str] = []
            cats: dict[str, int] = {}
            rownum = list(range(2, len(rows) + 2))          # the original row numbers
            if "spaces" in opts:
                n = 0
                for r in rows:
                    for c, v in enumerate(r):
                        t = tidy_cell(v)
                        if t != v:
                            r[c] = t
                            n += 1
                header = [tidy_cell(h) for h in header]
                notes.append(f"Extra spaces tidied in {n} cell{'' if n == 1 else 's'}.")
                same = match_case(header, rows)
                if same:
                    notes.append("Same words written the same way (" + "; ".join(same) + ").")
            dropped: list[tuple[int, str]] = []
            if "dupes" in opts:
                kept, gone = dedupe_rows(rows)
                dropped = [(rownum[g], " | ".join(x for x in rows[g] if x)[:120]) for g in gone]
                rows = [rows[k] for k in kept]
                rownum = [rownum[k] for k in kept]
                notes.append(f"{len(gone)} duplicate row{'' if len(gone) == 1 else 's'} removed.")
            batches = [list(range(a, min(a + SHEET_ROWS, len(rows)))) for a in range(0, len(rows), SHEET_ROWS)]
            where = {n: k for k, n in enumerate(rownum)}        # original row number -> index now
            if "spelling" in opts and rows:
                tcols = text_columns(header, rows)
                if not tcols:
                    notes.append("Spelling: no columns of ordinary words to check.")
                for bi, idx in enumerate(batches if tcols else []):
                    if engine.stop.is_set():
                        raise Stopped()
                    engine._progress(f"{job.name}: {src.name}, spelling {bi + 1}/{len(batches)}")
                    got = _ask_list(engine, job, st, bi, "tidy-spelling", SPELL_SYSTEM + rules,
                                    SPELL_ASK.format(rows=_rows_json_numbered(header, rows, idx, tcols, rownum)))
                    if got is None:
                        unsure.append(f"Spelling wasn't checked for rows {rownum[idx[0]]}-{rownum[idx[-1]]} "
                                      "(the model's answer didn't make sense).")
                        continue
                    pos = {rownum[k]: k for k in idx}
                    for f in got:
                        k = pos.get(f.get("row"))
                        col = next((c for c in tcols if header[c] == f.get("column")), None)
                        find, rep = str(f.get("find") or ""), str(f.get("replace") or "")
                        if k is None or col is None or not find or len(find) > 120 \
                                or not real_spelling_fix(find, rep):
                            continue
                        cell = rows[k][col]
                        if find in cell and not re.search(r"\d", find):
                            rows[k][col] = cell.replace(find, rep, 1)
                            fixes.append(f"Row {rownum[k]}, {header[col]}: {_q(find)} → {_q(rep)}")
                notes.append(f"Spelling: {len(fixes)} fix{'' if len(fixes) == 1 else 'es'}.")
            if "split" in opts and rows:
                req = split_request(job.format, header)
                if not req:
                    notes.append("Split: nothing split. Say which column in 'Anything else?', e.g. "
                                 "\"split Name into First name, Last name\".")
                else:
                    col, new = req
                    vals: dict[int, list[str]] = {}
                    for bi, idx in enumerate(batches):
                        if engine.stop.is_set():
                            raise Stopped()
                        engine._progress(f"{job.name}: {src.name}, splitting {bi + 1}/{len(batches)}")
                        ask = (f"Split the \"{header[col]}\" column into: {', '.join(new)}.\n"
                               f"Rows as JSON:\n{_rows_json_numbered(header, rows, idx, [col], rownum)}\n\n"
                               f"Reply with one object per row: {{\"row\": <row number>, "
                               + ", ".join(f'"{n}": "..."' for n in new) + "}")
                        got = _ask_list(engine, job, st, bi, "tidy-split", FILL_SYSTEM + rules, ask)
                        for f in got or []:
                            if f.get("row") in where:
                                vals[where[f["row"]]] = [str(f.get(n) or "").strip() for n in new]
                    missing = [rownum[k] for k in range(len(rows)) if k not in vals and rows[k][col].strip()]
                    header = header[:col + 1] + new + header[col + 1:]
                    rows = [r[:col + 1] + vals.get(k, [""] * len(new)) + r[col + 1:] for k, r in enumerate(rows)]
                    notes.append(f"Split {header[col]} into {', '.join(new)} (the original column is kept).")
                    if missing:
                        unsure.append(f"Rows not split (check by hand): {', '.join(map(str, missing[:60]))}"
                                      + (" ..." if len(missing) > 60 else ""))
            if "categorize" in opts and rows:
                wanted = given_categories(job.format)
                cols = [c for c in range(len(header))]
                if not wanted:
                    sample = list(range(0, len(rows), max(1, len(rows) // 60)))[:60]
                    got = _ask_list(engine, job, st, 0, "tidy-categories", CAT_SYSTEM + rules,
                                    "Here are sample rows of a spreadsheet as JSON:\n"
                                    + _rows_json_numbered(header, rows, sample, cols, rownum) +
                                    "\n\nSuggest 3 to 8 short category names (one or two words each) that "
                                    "together fit every row. Reply with a JSON array of strings.", of=str)
                    wanted = [w.strip() for w in (got or []) if w.strip()][:12]
                if not wanted:
                    unsure.append("No categories were added: Joe couldn't come up with a list. Give one in "
                                  "'Anything else?', e.g. \"categories: mugs, bowls, vases\".")
                else:
                    lower = {w.lower(): w for w in wanted}
                    picked: dict[int, str] = {}
                    for bi, idx in enumerate(batches):
                        if engine.stop.is_set():
                            raise Stopped()
                        engine._progress(f"{job.name}: {src.name}, categories {bi + 1}/{len(batches)}")
                        ask = (f"Categories: {', '.join(wanted)}\nPut each row in exactly one of these "
                               "categories. If none fits, use \"Other\".\nRows as JSON:\n"
                               f"{_rows_json_numbered(header, rows, idx, cols, rownum)}\n\n"
                               "Reply with one object per row: {\"row\": <row number>, \"category\": \"...\"}")
                        got = _ask_list(engine, job, st, bi, "tidy-categorize", CAT_SYSTEM + rules, ask)
                        for f in got or []:
                            if f.get("row") in where:
                                c = str(f.get("category") or "").strip()
                                picked[where[f["row"]]] = lower.get(c.lower(), "Other" if c.lower() == "other" else c)
                    name = "Category" if "category" not in {h.lower() for h in header} else "Joe's category"
                    header = header + [name]
                    for k, r in enumerate(rows):
                        c = picked.get(k, "")
                        r.append(c)
                        if not c:
                            unsure.append(f"Row {rownum[k]}: no category given")
                        elif c not in wanted and c != "Other":
                            unsure.append(f"Row {rownum[k]}: category {_q(c)} isn't on the list [CHECK]")
                        cats[c or "(none)"] = cats.get(c or "(none)", 0) + 1
                    notes.append(f"Added a \"{name}\" column: {', '.join(wanted)}.")
            stem = unique_stem(files, i)
            out_name = f"{stem}-tidy.csv"
            write_csv(folder / out_name, header, rows)
            atomic_write_text(folder / f"{stem}-changes.md",
                              tidy_report(src.stem, notes, dropped, fixes, cats, unsure, out_name))
            st.flags.extend({"item": src.stem, "flag": f"[CHECK] {u}"} for u in unsure[:30])
            st.titles.append(key)
            st.media_files.extend([out_name, f"{stem}-changes.md"])
            st.items += 1
            engine._save_state(job, st)
            engine.log(f"  {src.name}: {len(rows)} rows -> {out_name}"
                       + (f" ({len(unsure)} thing(s) worth a look)" if unsure else ""))
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {len(files)} spreadsheet(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    return _finish(engine, job, st, len(files), failed)


def _rows_json_numbered(header: list[str], rows: list[list[str]], idx: list[int], cols: list[int],
                        rownum: list[int]) -> str:
    """Rows as JSON for the model, numbered as in the person's original sheet."""
    import json
    return json.dumps([{"row": rownum[i], **{header[c]: rows[i][c] for c in cols}} for i in idx],
                      ensure_ascii=False)


# --------------------------------------------------------------------------- vision tools (shared)
RAW_IMAGE_MAX = 6_000_000             # without FFmpeg, photos bigger than this can't be sent


def find_vision_model(engine: "Engine") -> str | None:
    from .attach import vision_model
    from .doctor import ollama_models
    return vision_model(ollama_models(engine.services))


def picture_b64(ffmpeg: str | None, src: Path, tmp: Path, longest: int) -> str:
    """The photo, upright and shrunk to `longest` px, as base64 JPEG for the vision model.
    Raises ValueError when it can't be prepared."""
    import base64
    ext = src.suffix.lower()
    if ffmpeg:
        from .system import no_window_flags
        dims = image_size(ffmpeg, src)
        if not dims:
            raise ValueError("couldn't open the picture")
        turn = jpeg_orientation(src) if ext in (".jpg", ".jpeg") else 1
        w, h = (dims[1], dims[0]) if turn >= 5 else dims
        tmp.parent.mkdir(parents=True, exist_ok=True)
        cmd = photo_command(ffmpeg, src, tmp, fit_size(w, h, longest), turn, "jpg", None, None, None, "")
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, creationflags=no_window_flags())
        except (OSError, subprocess.SubprocessError) as e:
            raise ValueError(f"couldn't prepare the picture: {e}") from e
        if p.returncode != 0 or not tmp.exists():
            raise ValueError("couldn't prepare the picture")
        try:
            return base64.b64encode(tmp.read_bytes()).decode()
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
    if ext not in (".jpg", ".jpeg", ".png", ".webp") or src.stat().st_size > RAW_IMAGE_MAX:
        raise ValueError("big or unusual pictures need FFmpeg to shrink them first (Setup > System check)")
    return base64.b64encode(src.read_bytes()).decode()


def parse_json_object(raw: str) -> dict | None:
    import json
    raw = re.sub(r"(?s)<think>.*?</think>", "", raw or "")
    raw = re.sub(r"```[\w-]*", "", raw)
    a, b = raw.find("{"), raw.rfind("}")
    if a < 0 or b < a:
        return None
    try:
        o = json.loads(raw[a:b + 1])
    except json.JSONDecodeError:
        return None
    return o if isinstance(o, dict) else None


def _look(engine: "Engine", job: "Job", st: "JobState", part: int, kind: str, system: str,
          ask: str, image: str, model: str) -> dict | None:
    """Ask the vision model about one picture; a JSON object back (asked twice), or None."""
    from .engine import PartFailed
    try:
        for attempt in range(2):
            r = engine._chat(job, part, kind, system, ask if not attempt else
                             ask + "\n\nReply with ONLY the JSON object.", st, images=[image], model=model)
            o = parse_json_object(r.text)
            if o is not None:
                return o
            st.retries += 1
    except PartFailed as e:
        engine.log(f"  {kind}: {e}")
    return None


def _s(v, n: int = 2000) -> str:
    if isinstance(v, list):
        v = ", ".join(str(x).strip() for x in v if str(x).strip())
    return " ".join(str(v if v is not None else "").split())[:n]


def _vision_start(engine: "Engine", job: "Job", st: "JobState", what: str):
    """Shared start for the picture tools: files, the vision model, FFmpeg, the folder.
    Returns (files, model, ffmpeg, folder) or a finished JobState when it can't start."""
    from .doctor import ffmpeg_exe
    if (bad := _no_files(engine, job, st, what)) is not None:
        return bad
    files, _ = resolve_inputs(engine, job)
    if not engine.services.handoff("text"):
        st.status, st.note = "failed", "Ollama is not running and could not be started"
        engine.log(st.note)
        return st
    model = find_vision_model(engine)
    if not model:
        st.status, st.note = "failed", ("this needs a vision model (one that can look at pictures). "
                                        "Setup (F10) > System check offers a free one")
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    ffmpeg = ffmpeg_exe(engine.s.comfy.ffmpeg)
    folder = tool_dir(engine, job, st)
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}': {len(files)} picture(s) "
               f"-> {st.output} (looking with {model})")
    return files, model, ffmpeg, folder


def _read_rows(p: Path) -> tuple[list[str], list[list[str]]]:
    """An earlier run's CSV (to carry on after a stop), or nothing."""
    try:
        from .sheets import read_csv
        return read_csv(p)
    except Exception:                                   # noqa: BLE001 (a fresh start is fine)
        return [], []


# --------------------------------------------------------------------------- B6 listings from photos
LISTING_SYSTEM = """You write shop listings from product photos. Describe only what you can see:
the kind of item, colors, shapes, finish, patterns, how many. Never invent materials, sizes,
weights, prices, brands or care instructions; if the writer would need one, write [CHECK].
Plain, warm, honest words. Reply with ONLY a JSON object, nothing else."""
LISTING_ASK = """{wish}Write a listing for the product in this photo (file: {name}).
JSON keys:
 "title": up to 70 characters, what the item is (no shop or maker names unless given above),
 "description": 2-4 sentences,
 "tags": up to 13 short tags a shopper would type to find it (the item, color, style, use;
         not tone words like "warm" or "friendly"), as a list,
 "alt_text": one sentence describing the photo for people who can't see it."""
LISTING_COLS = ["File", "Title", "Description", "Tags", "Alt text"]


def run_photo_listing(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .engine import Stopped
    from .sheets import write_csv
    got = _vision_start(engine, job, st, "product photos")
    if not isinstance(got, tuple):
        return got
    files, model, ffmpeg, folder = got
    opts = chosen_options(job)
    wish = f"About these products: {job.format.strip()}\n" if job.format.strip() else ""
    system = LISTING_SYSTEM + (("\n" + job.rules.strip()) if job.rules.strip() else "")
    sheet = folder / "listings.csv"
    _, rows = _read_rows(sheet)
    failed: list[str] = []
    try:
        for i, src in enumerate(files):
            key = _key(engine, src)
            if key in st.titles:
                continue
            if engine.stop.is_set():
                raise Stopped()
            engine._progress(f"{job.name}: {i + 1}/{len(files)} {src.name}")
            try:
                img = picture_b64(ffmpeg, src, engine.meta / "tmp" / f"look-{job.job_id}.jpg", 1280)
            except (ValueError, OSError) as e:
                failed.append(f"{src.name}: {e}"[:200])
                engine.log(f"  {src.name}: {e}")
                continue
            o = _look(engine, job, st, i, "photo-listing", system,
                      LISTING_ASK.format(wish=wish, name=src.name), img, model)
            if not o or not _s(o.get("title")):
                failed.append(f"{src.name}: the model's answer didn't make sense")
                engine.log(f"  {src.name}: the model's answer didn't make sense")
                continue
            row = [src.name, _s(o.get("title"), 140), _s(o.get("description")),
                   _s(o.get("tags"), 600), _s(o.get("alt_text"), 300)]
            rows = [r for r in rows if r and r[0] != src.name] + [row]
            if "csv" in opts:
                write_csv(sheet, LISTING_COLS, rows)
            if "doc" in opts:
                doc = ["# Listings", "", "Written by Joe from your photos. Check every [CHECK] and add "
                       "sizes, materials and prices yourself.", ""]
                for r in rows:
                    doc += [f"## {r[1]}", "", f"*{r[0]}*", "", r[2], "", f"**Tags:** {r[3]}", "",
                            f"**Alt text:** {r[4]}", ""]
                atomic_write_text(folder / "listings.md", "\n".join(doc))
            st.flags.extend({"item": src.name, "flag": f} for f in find_flags(" ".join(row)))
            st.titles.append(key)
            st.items += 1
            st.words += count_words(" ".join(row[1:]))
            engine._save_state(job, st)
            engine.log(f"  {src.name}: {row[1]}")
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {len(files)} photo(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    st.media_files = [n for n, on in (("listings.csv", "csv" in opts), ("listings.md", "doc" in opts)) if on]
    return _finish(engine, job, st, len(files), failed)


# --------------------------------------------------------------------------- B7 read scans and receipts
SCAN_SYSTEM = """You read text from pictures of documents, receipts, forms and signs. Copy exactly
what is written: never guess, fix, translate or fill in anything. Write [CHECK] where you
can't read something clearly. Reply with ONLY a JSON object, nothing else."""
SCAN_ASK = {
    "text": """Copy all the text in this picture (file: {name}), in reading order, keeping
headings, lists and line breaks. JSON: {{"text": "the text, in Markdown"}}""",
    "receipts": """This is a receipt or invoice (file: {name}). JSON keys:
 "date": as written (or "" if not shown), "store": the shop or company name,
 "total": the total paid exactly as written, "tax": tax as written or "",
 "currency": the currency symbol or code if shown,
 "items": a list of {{"name": "...", "price": "..."}} exactly as written.""",
    "table": """Copy the table in this picture (file: {name}) exactly. JSON: {{"columns": [the
column names], "rows": [[one list of cells per row, as written]]}}""",
}
RECEIPT_COLS = ["File", "Date", "Store", "Total", "Tax", "Currency", "Items"]


def run_read_scans(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .engine import Stopped
    from .sheets import write_csv
    got = _vision_start(engine, job, st, "scans or receipts")
    if not isinstance(got, tuple):
        return got
    files, model, ffmpeg, folder = got
    mode = option_value(job, "as") or "text"
    wish = f"Note: {job.format.strip()}\n" if job.format.strip() else ""
    system = SCAN_SYSTEM + (("\n" + job.rules.strip()) if job.rules.strip() else "")
    receipts = folder / "receipts.csv"
    items_csv = folder / "receipt-items.csv"
    _, rec_rows = _read_rows(receipts)
    _, item_rows = _read_rows(items_csv)
    failed: list[str] = []
    made: list[str] = []
    try:
        for i, src in enumerate(files):
            key = _key(engine, src)
            if key in st.titles:
                continue
            if engine.stop.is_set():
                raise Stopped()
            engine._progress(f"{job.name}: {i + 1}/{len(files)} {src.name}")
            try:                                          # reading needs more detail than describing
                img = picture_b64(ffmpeg, src, engine.meta / "tmp" / f"look-{job.job_id}.jpg", 2000)
            except (ValueError, OSError) as e:
                failed.append(f"{src.name}: {e}"[:200])
                engine.log(f"  {src.name}: {e}")
                continue
            o = _look(engine, job, st, i, "read-scans", system,
                      wish + SCAN_ASK[mode].format(name=src.name), img, model)
            stem = unique_stem(files, i)
            if mode == "text" and o and _s(o.get("text")):
                text = str(o.get("text")).strip()
                atomic_write_text(folder / f"{stem}.md", f"# {src.stem}\n\n{text}\n")
                made.append(f"{stem}.md")
                st.words += count_words(text)
                st.flags.extend({"item": src.name, "flag": f} for f in find_flags(text))
            elif mode == "receipts" and o and (_s(o.get("total")) or _s(o.get("store"))):
                its = [x for x in (o.get("items") or []) if isinstance(x, dict)]
                rec_rows = [r for r in rec_rows if r and r[0] != src.name] + [[
                    src.name, _s(o.get("date"), 40), _s(o.get("store"), 120), _s(o.get("total"), 40),
                    _s(o.get("tax"), 40), _s(o.get("currency"), 10), str(len(its))]]
                item_rows = [r for r in item_rows if r and r[0] != src.name] + \
                    [[src.name, _s(x.get("name"), 200), _s(x.get("price"), 40)] for x in its]
                write_csv(receipts, RECEIPT_COLS, rec_rows)
                write_csv(items_csv, ["File", "Item", "Price"], item_rows)
                if not _s(o.get("total")):
                    st.flags.append({"item": src.name, "flag": "[CHECK] no total found"})
                st.flags.extend({"item": src.name, "flag": f} for f in find_flags(json_text(o)))
            elif mode == "table" and o and isinstance(o.get("rows"), list) and o["rows"]:
                cols = [_s(c, 200) for c in (o.get("columns") or [])]
                rows = [[_s(c, 500) for c in r] for r in o["rows"] if isinstance(r, list)]
                width = max([len(cols)] + [len(r) for r in rows])
                cols = (cols + [f"Column {k + 1}" for k in range(len(cols), width)])[:width]
                write_csv(folder / f"{stem}.csv", cols, [r + [""] * (width - len(r)) for r in rows])
                made.append(f"{stem}.csv")
                st.flags.extend({"item": src.name, "flag": f} for f in find_flags(json_text(o)))
            else:
                # Not a table / receipt after all (a sign, a note)? Read it as plain text instead of
                # giving up (end test: a store-hours sign in a "table" batch came back empty).
                t = None
                if mode != "text":
                    t = _look(engine, job, st, i, "read-scans", system,
                              wish + SCAN_ASK["text"].format(name=src.name), img, model)
                if t and _s(t.get("text")):
                    text = str(t.get("text")).strip()
                    atomic_write_text(folder / f"{stem}.md", f"# {src.stem}\n\n{text}\n")
                    made.append(f"{stem}.md")
                    st.words += count_words(text)
                    st.flags.append({"item": src.name, "flag": f"[CHECK] no {mode} found, read as plain text"})
                    engine.log(f"  {src.name}: no {mode} in it, read as plain text")
                else:
                    failed.append(f"{src.name}: nothing could be read (is it a clear photo?)")
                    engine.log(f"  {src.name}: nothing could be read")
                    continue
            st.titles.append(key)
            st.items += 1
            engine._save_state(job, st)
            engine.log(f"  {src.name}: read")
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {len(files)} picture(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    if mode == "text" and st.titles:                       # everything in one file too
        parts = []
        for f in sorted(folder.glob("*.md")):
            if f.name != "all-text.md":
                parts.append(f.read_text(encoding="utf-8").strip())
        atomic_write_text(folder / "all-text.md", "\n\n---\n\n".join(parts) + "\n")
    st.media_files = (["receipts.csv", "receipt-items.csv"] if mode == "receipts" else
                      sorted(p.name for p in folder.iterdir() if p.is_file()))
    return _finish(engine, job, st, len(files), failed)


def json_text(o) -> str:
    import json
    return json.dumps(o, ensure_ascii=False)


# --------------------------------------------------------------------------- B8 sort my photos
SORT_SYSTEM = """You sort photos by what is in them. Describe only what you can see; never guess
names of people or places. Reply with ONLY a JSON object, nothing else."""
SORT_ASK = """{wish}Look at this photo (file: {name}).
{cats}
JSON keys: "category": the one category, "tags": up to 8 short tags (a list),
"caption": one short sentence saying what the photo shows."""


def run_sort_photos(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    import shutil
    from .engine import Stopped
    from .sheets import write_csv
    got = _vision_start(engine, job, st, "photos to sort")
    if not isinstance(got, tuple):
        return got
    files, model, ffmpeg, folder = got
    opts = chosen_options(job)
    given = given_categories(job.format)
    wish = f"Note: {job.format.strip()}\n" if job.format.strip() else ""
    system = SORT_SYSTEM + (("\n" + job.rules.strip()) if job.rules.strip() else "")
    catalog = folder / "photo-list.csv"
    _, rows = _read_rows(catalog)
    used = sorted({r[1] for r in rows if len(r) > 1 and r[1]})
    failed: list[str] = []
    try:
        for i, src in enumerate(files):
            key = _key(engine, src)
            if key in st.titles:
                continue
            if engine.stop.is_set():
                raise Stopped()
            engine._progress(f"{job.name}: {i + 1}/{len(files)} {src.name}")
            try:
                img = picture_b64(ffmpeg, src, engine.meta / "tmp" / f"look-{job.job_id}.jpg", 1024)
            except (ValueError, OSError) as e:
                failed.append(f"{src.name}: {e}"[:200])
                engine.log(f"  {src.name}: {e}")
                continue
            if given:
                cats = f"Pick the category from this list: {', '.join(given)}. If none fits, use \"Other\"."
            else:
                cats = ("Pick a short category (one or two words, plural, like \"Dogs\" or \"Beach days\")"
                        + (f". Reuse one of these if it fits: {', '.join(used)}." if used else "."))
            o = _look(engine, job, st, i, "sort-photos", system,
                      SORT_ASK.format(wish=wish, name=src.name, cats=cats), img, model)
            cat = _s((o or {}).get("category"), 40).strip(" .")
            if not cat:
                failed.append(f"{src.name}: the model's answer didn't make sense")
                engine.log(f"  {src.name}: the model's answer didn't make sense")
                continue
            pool = given or used                         # same words, same folder ("dogs" = "Dogs")
            cat = next((c for c in pool if c.lower() == cat.lower()), cat if not given else
                       ("Other" if cat.lower() == "other" else cat))
            if given and cat not in given and cat != "Other":
                st.flags.append({"item": src.name, "flag": f"[CHECK] category {cat} isn't on your list"})
            if cat not in used:
                used.append(cat)
            row = [src.name, cat, _s(o.get("tags"), 300), _s(o.get("caption"), 300)]
            rows = [r for r in rows if r and r[0] != src.name] + [row]
            write_csv(catalog, ["File", "Category", "Tags", "Caption"], rows)
            if "folders" in opts:
                sub = folder / (re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", cat).strip(" .") or "Other")
                sub.mkdir(exist_ok=True)
                dest, n = sub / src.name, 2
                while dest.exists():
                    dest = sub / f"{src.stem}_{n}{src.suffix}"
                    n += 1
                shutil.copy2(src, dest)                  # a copy: the original stays where it was
            st.titles.append(key)
            st.items += 1
            engine._save_state(job, st)
            engine.log(f"  {src.name}: {cat}")
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {len(files)} photo(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    st.media_files = ["photo-list.csv"]
    engine.log(f"  {len(used)} categories: {', '.join(used[:12])}")
    return _finish(engine, job, st, len(files), failed)


# --------------------------------------------------------------------------- B10 ask my files
EMBED_MODEL = "nomic-embed-text"      # small (about 270 MB), good at finding the right passage
_EMBED_HINT = re.compile(r"embed|bge-|minilm|arctic-embed|e5-", re.I)
ASK_CHUNK_WORDS = 220                 # words per searchable piece
ASK_TOP = 8                           # pieces shown to the writing model per question
ANSWER_SYSTEM = """You answer questions using ONLY the numbered excerpts from the person's own
documents. Say which excerpts you used with their EXCERPT numbers, like [2] or [1][4], right
after the sentence (never a section or page number from inside the text). When an excerpt
answers the question, just give the answer: don't also say the documents don't say it. Only when
none of them answers it, say plainly that the documents don't seem to say, and what they do say
that comes closest. Never use outside knowledge, never guess numbers, dates or names.
Plain, friendly English."""
SUMMARY_SYSTEM = """You summarize one of the person's documents using only what it says. Every
bullet must be something the document actually states. Never add outside facts, typical
terms, or anything "usually" true. A short document gets only a few bullets. Plain, friendly
English, Markdown bullet points."""
_WORD = re.compile(r"[^\W_]+", re.U)
_STOP = set("""a an and are as at be but by for from has have i if in into is it its of on or our
so that the their them then there these they this to was we were what when where which who why
will with you your do does did can how about""".split())


def embed_model_in(models: list[dict]) -> str | None:
    for m in models:
        if _EMBED_HINT.search(m["name"]):
            return m["name"]
    return None


def find_embed_model(engine: "Engine") -> str | None:
    from .doctor import ollama_models
    return embed_model_in(ollama_models(engine.services))


def questions_from(fmt: str) -> list[str]:
    """One question per line (or per '?'), from the form's box / FORMAT."""
    out = []
    for line in re.split(r"\n|(?<=\?)\s+", fmt or ""):
        q = line.strip(" -*•\t")
        if len(q) >= 3:
            out.append(q[:500])
    return out[:20]


def ask_chunks(name: str, text: str, words: int = ASK_CHUNK_WORDS) -> list[dict]:
    """Searchable pieces of a document: paragraphs grouped to about `words` words."""
    out, cur, n = [], [], 0
    for p in (x.strip() for x in re.split(r"\n\s*\n", text)):
        if not p:
            continue
        ws = p.split()
        if len(ws) > words * 2:                          # a giant paragraph: cut by words
            if cur:
                out.append("\n\n".join(cur))
                cur, n = [], 0
            out += [" ".join(ws[a:a + words]) for a in range(0, len(ws), words)]
            continue
        if cur and n + len(ws) > words:
            out.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(p)
        n += len(ws)
    if cur:
        out.append("\n\n".join(cur))
    return [{"file": name, "n": i + 1, "text": t} for i, t in enumerate(out)]


def _stem(w: str) -> str:
    """A rough word root, so 'refunds' finds 'refund' and 'cancelling' finds 'cancel'."""
    for end in ("ing", "ed", "es", "s"):
        if len(w) > len(end) + 3 and w.endswith(end) and not w.endswith("ss"):
            w = w[:-len(end)]
            break
    return w[:-1] if len(w) > 4 and w[-1] == w[-2] else w


def _terms(text: str) -> list[str]:
    return [_stem(w) for w in (x.casefold() for x in _WORD.findall(text)) if w not in _STOP and len(w) > 1]


def keyword_scores(question: str, chunks: list[dict]) -> list[float]:
    """BM25: how well each piece matches the question's words (no model needed)."""
    import math
    q = set(_terms(question))
    docs = [_terms(c["text"]) for c in chunks]
    if not q or not docs:
        return [0.0] * len(chunks)
    avg = sum(len(d) for d in docs) / len(docs) or 1
    df = {t: sum(1 for d in docs if t in set(d)) for t in q}
    out = []
    for d in docs:
        tf = {}
        for w in d:
            if w in q:
                tf[w] = tf.get(w, 0) + 1
        s = 0.0
        for t, f in tf.items():
            idf = math.log(1 + (len(docs) - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * len(d) / avg))
        out.append(s)
    return out


def _cos(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def best_chunks(question: str, chunks: list[dict], vectors: list[list[float]] | None,
                qvec: list[float] | None, top: int = ASK_TOP) -> list[int]:
    """The pieces most likely to answer the question: meaning (search model) and words (BM25)."""
    kw = keyword_scores(question, chunks)
    top_kw = max(kw) or 1.0
    score = []
    for i in range(len(chunks)):
        s = kw[i] / top_kw
        if vectors and qvec:
            s = 0.35 * s + _cos(vectors[i], qvec)
        score.append(s)
    order = sorted(range(len(chunks)), key=lambda i: -score[i])
    return [i for i in order[:top] if score[i] > 0]


def _embed_all(engine: "Engine", model: str, texts: list[str]) -> list[list[float]]:
    """Search vectors, cached on disk so asking again (or more questions) is quick."""
    import hashlib
    import json
    cache_p = engine.meta / "search" / f"{re.sub(r'[^a-z0-9]+', '-', model.lower())}.jsonl"
    cache: dict[str, list[float]] = {}
    try:
        for line in cache_p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("\t")
            cache[k] = json.loads(v)
    except (OSError, ValueError):
        pass
    keys = [hashlib.sha1(t.encode("utf-8", "replace")).hexdigest() for t in texts]
    todo = [i for i, k in enumerate(keys) if k not in cache]
    new = []
    for a in range(0, len(todo), 32):
        batch = todo[a:a + 32]
        engine._progress(f"Getting {len(todo)} piece(s) ready to search: {a + len(batch)}/{len(todo)}")
        vecs = engine.client.embed([texts[i] for i in batch], model)
        for i, v in zip(batch, vecs):
            cache[keys[i]] = v
            new.append(f"{keys[i]}\t{json.dumps(v)}")
    if new:
        cache_p.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_p, "a", encoding="utf-8") as f:
            f.write("\n".join(new) + "\n")
    return [cache[k] for k in keys]


def tidy_citations(answer: str, n: int, texts: list[str] | None = None) -> tuple[str, list[int]]:
    """Drop citations to excerpts that don't exist (like a section number), and say which
    excerpts to list under the answer: the ones it cited, else the ones that share the most
    words with the answer (`texts`), else the top three."""
    cited: list[int] = []

    def keep(m):
        k = int(m.group(1))
        if 1 <= k <= n:
            if k - 1 not in cited:
                cited.append(k - 1)
            return m.group(0)
        return ""
    answer = re.sub(r"\[(\d+)\]", keep, answer)
    answer = re.sub(r"[ \t]+([.,;:!?])", r"\1", answer)
    answer = re.sub(r"[ \t]{2,}", " ", answer)
    if not cited and texts:
        a = set(_terms(answer))
        a |= set(re.findall(r"\d+(?:[.,]\d+)?", answer))
        score = [len(a & (set(_terms(t)) | set(re.findall(r"\d+(?:[.,]\d+)?", t)))) for t in texts[:n]]
        top = max(score, default=0)
        if top:
            cited = [i for i, sc in enumerate(score) if sc >= max(2, top * 0.6)][:3] or [score.index(top)]
    return answer.strip(), sorted(cited) or list(range(min(3, n)))


def best_line(text: str, question: str, words: int = 45, answer: str = "") -> str:
    """The sentence in an excerpt that best fits the question (and the answer given), for the
    person to check."""
    q = set(_terms(question))
    a = set(_terms(answer)) | set(re.findall(r"\d+(?:[.,]\d+)?", answer))
    sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", text) if x.strip()]
    if not sents:
        return ""
    best = max(sents, key=lambda x: len(q & set(_terms(x))) + 2 * len(
        a & (set(_terms(x)) | set(re.findall(r"\d+(?:[.,]\d+)?", x)))))
    ws = best.split()
    return " ".join(ws[:words]) + ("\u2026" if len(ws) > words else "")


def grounded(summary: str, source: str, need: float = 0.6) -> tuple[str, list[str]]:
    """Keep the bullet points the document backs up. A bullet is dropped when most of its
    words aren't in the document, or it has a number the document doesn't have."""
    have = set(_terms(source))
    nums = set(re.findall(r"\d+(?:[.,]\d+)?", source))
    kept, dropped = [], []
    for line in summary.splitlines():
        if re.match(r"\s*[-*\u2022]\s+", line):
            t = [w for w in _terms(line) if len(w) > 3]
            bad_num = any(n not in nums for n in re.findall(r"\d+(?:[.,]\d+)?", line))
            if bad_num or (len(t) >= 2 and sum(w in have for w in t) / len(t) < need):
                dropped.append(re.sub(r"^\s*[-*\u2022]\s+", "", line).strip())
                continue
        kept.append(line)
    return "\n".join(kept).strip(), dropped


def run_ask_files(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .engine import PartFailed, Stopped

    if (bad := _no_files(engine, job, st, "documents to read")) is not None:
        return bad
    files, _ = resolve_inputs(engine, job)
    opts = chosen_options(job)
    questions = questions_from(job.format)
    if not questions:
        opts = opts | {"summaries"}
    if not engine._text_ready(st):
        engine._save_state(job, st)
        return st
    folder = tool_dir(engine, job, st)
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}': {len(files)} document(s), "
               f"{len(questions)} question(s)" + (", summaries" if "summaries" in opts else "")
               + f" -> {st.output}")
    failed: list[str] = []
    texts: dict[str, str] = {}
    chunks: list[dict] = []
    for src in files:
        name = _key(engine, src)
        try:
            t = document_text(src, engine.log)
        except (ValueError, OSError) as e:
            failed.append(f"{src.name}: {e}"[:200])
            engine.log(f"  {src.name}: {e}")
            continue
        if t.strip():
            texts[name] = t
            chunks += ask_chunks(name, t)
    if not texts:
        st.status, st.note = "failed", "none of the documents could be read" + (f" ({failed[0]})" if failed else "")
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    words = sum(count_words(t) for t in texts.values())
    engine.log(f"  Read {len(texts)} document(s): {words} words in {len(chunks)} searchable piece(s)")
    total = len(questions) + (len(texts) if "summaries" in opts else 0)
    try:
        if questions:
            emodel = find_embed_model(engine)
            vectors = None
            how = "words only"
            if emodel and len(chunks) > ASK_TOP:
                try:
                    vectors = _embed_all(engine, emodel, [c["text"] for c in chunks])
                    how = f"meaning and words ({emodel})"
                except Exception as e:                   # noqa: BLE001 (keyword search still works)
                    engine.log(f"  The search model didn't work ({e}); searching by words only.")
            elif not emodel and len(chunks) > ASK_TOP:
                engine.log("  No search model installed, so Joe searches by words only (Setup > System "
                           f"check offers {EMBED_MODEL}, about 270 MB, for better answers).")
            answers_p = folder / "answers.md"
            done_md = answers_p.read_text(encoding="utf-8") if answers_p.exists() and st.titles else \
                f"# Answers from your files\n\nFrom {len(texts)} document(s), searched by {how}. Every answer " \
                "comes only from your documents; check the excerpts before you rely on it.\n"
            for qi, q in enumerate(questions):
                if f"Q: {q}" in st.titles:
                    continue
                if engine.stop.is_set():
                    raise Stopped()
                engine._progress(f"{job.name}: question {qi + 1}/{len(questions)}")
                qvec = None
                if vectors is not None:
                    try:
                        qvec = engine.client.embed([q], emodel)[0]
                    except Exception:                    # noqa: BLE001
                        qvec = None
                pick = best_chunks(q, chunks, vectors, qvec) if len(chunks) > ASK_TOP else list(range(len(chunks)))
                if not pick:
                    answer = "Joe couldn't find anything about this in your documents."
                else:
                    ex = "\n\n".join(f"EXCERPT [{k + 1}] ({chunks[i]['file']}, part {chunks[i]['n']})\n{chunks[i]['text']}"
                                     for k, i in enumerate(pick))
                    try:
                        r = engine._chat(job, qi, "ask-files", ANSWER_SYSTEM + (("\n" + job.rules.strip())
                                         if job.rules.strip() else ""),
                                         f"QUESTION: {q}\n\nEXCERPTS:\n{ex}", st)
                        answer = r.text.strip()
                    except PartFailed as e:
                        failed.append(f"question {qi + 1}: {e}"[:200])
                        continue
                answer, shown = tidy_citations(answer, len(pick), [chunks[i]["text"] for i in pick])
                src_lines = "\n".join(
                    f"- [{k + 1}] {chunks[pick[k]]['file']}, part {chunks[pick[k]]['n']}: \u201c"
                    + best_line(chunks[pick[k]]["text"], q, answer=answer) + "\u201d" for k in shown)
                done_md += f"\n## {q}\n\n{answer}\n\n" + (f"**Excerpts used:**\n{src_lines}\n" if pick else "")
                atomic_write_text(answers_p, done_md)
                st.titles.append(f"Q: {q}")
                st.items += 1
                st.words += count_words(answer)
                engine._save_state(job, st)
                engine.log(f"  Answered: {q[:80]}")
            if questions:
                st.media_files = sorted(set(st.media_files) | {"answers.md"})
        if "summaries" in opts:
            sum_p = folder / "summaries.md"
            md = sum_p.read_text(encoding="utf-8") if sum_p.exists() and st.titles else "# Summaries\n"
            for di, (name, text) in enumerate(texts.items()):
                if f"S: {name}" in st.titles:
                    continue
                if engine.stop.is_set():
                    raise Stopped()
                engine._progress(f"{job.name}: summary {di + 1}/{len(texts)}")
                ws = text.split()
                pieces = [" ".join(ws[a:a + 2500]) for a in range(0, len(ws), 2500)] or [""]
                try:
                    if len(pieces) == 1:
                        body = engine._chat(job, di, "ask-summary", SUMMARY_SYSTEM,
                                            f"Document: {name}\nWrite a short summary: one bullet per fact it states, at most 8, "
                                            f"then one line: 'Worth knowing:' anything like dates, amounts or "
                                            f"deadlines.\n\nDOCUMENT:\n{pieces[0]}", st).text.strip()
                    else:
                        notes = [engine._chat(job, di, "ask-summary", SUMMARY_SYSTEM,
                                              f"Document: {name} (piece {k + 1} of {len(pieces)}). Bullet points "
                                              f"of everything important.\n\nTEXT:\n{p}", st).text.strip()
                                 for k, p in enumerate(pieces)]
                        body = engine._chat(job, di, "ask-summary", SUMMARY_SYSTEM,
                                            f"Document: {name}. These are notes on each piece, in order. Write "
                                            "one short summary (one bullet per fact, at most 8), then 'Worth knowing:'.\n\n"
                                            + "\n\n".join(notes), st).text.strip()
                except PartFailed as e:
                    failed.append(f"{name}: summary skipped ({e})"[:200])
                    continue
                body, dropped = grounded(body, text)
                if dropped:
                    engine.log(f"  {name}: left out {len(dropped)} line(s) the document doesn't say")
                    body += ("\n\n*Joe left these out because the document doesn't say them "
                             "(the model added them):*\n" + "\n".join(f"- ~~{d}~~" for d in dropped))
                md += f"\n## {name}\n\n{body}\n"
                atomic_write_text(sum_p, md)
                st.titles.append(f"S: {name}")
                st.items += 1
                st.words += count_words(body)
                engine._save_state(job, st)
            st.media_files = sorted(set(st.media_files) | {"summaries.md"})
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {total} answer(s)/summaries"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    return _finish(engine, job, st, total, failed)


# --------------------------------------------------------------------------- uploads
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def upload_target(sb, tool_id: str, name: str) -> Path:
    """Where a file dropped on a tool's form goes: Inbox/tools/<tool>/<name> (never overwrites)."""
    folder = sb.inbox / "tools" / tool_id
    folder.mkdir(parents=True, exist_ok=True)
    clean = _BAD.sub("_", Path(name or "file").name).strip(" .")[:120] or "file"
    target = folder / clean
    stem, ext, n = target.stem, target.suffix, 2
    while target.exists():
        target = folder / f"{stem}_{n}{ext}"
        n += 1
    sb.check(target)
    return target


def mission_for(tool_id: str, files: list[str], options: list[str], name: str = "",
                extra: str = "", mark: str = "") -> str:
    """The mission a Tools-tab form runs (also shown under ADVANCED)."""
    tool = TOOLS[tool_id]
    task = (name or tool.name).replace("\n", " ").strip()[:80]
    lines = [f"TASK: {task}  TYPE: {tool.id}"] + (["INPUT: " + ", ".join(files)] if files else [])
    if tool.options:
        lines.append("OPTIONS: " + (", ".join(options) if options else "none"))
    if extra.strip():
        sep = " | " if tool.id in ("music", "social-graphic", "pdf-tools", "hide-details") else " "   # one piece / line per |
        lines.append("FORMAT: " + sep.join(x.strip() for x in extra.strip().splitlines() if x.strip()))
    if mark.strip() and tool.mark:
        lines.append("WATERMARK: " + " ".join(mark.split())[:120])
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- planning
# Rough minutes of sound per MB, to guess run time before a file is opened.
_MIN_PER_MB = {".wav": 0.5, ".flac": 1 / 5, ".mp4": 1 / 8, ".mov": 1 / 10, ".mkv": 1 / 8,
               ".webm": 1 / 6, ".avi": 1 / 10, ".m4v": 1 / 8, ".wmv": 1 / 8, ".3gp": 1 / 3}


def plan_info(engine_sb, job: "Job", speeds: dict) -> dict:
    """For App.check(): files found, a time guess, and problems that would stop the task."""
    from .sandbox import SandboxError
    tool = TOOLS[job.type]
    files: list[Path] = []
    problems: list[str] = []
    for rel in job.inputs:
        try:
            p = engine_sb.resolve_input(rel)
        except SandboxError as e:
            problems.append(f"{rel}: {e}")
            continue
        if p.is_dir():
            files += [f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in tool.accepts]
        elif p.is_file() and p.suffix.lower() in tool.accepts:
            files.append(p)
        else:
            problems.append(f"{rel}: not found in Inbox, or not a kind of file this tool reads")
    secs = 0.0
    if job.type == "transcribe":
        for f in files:
            try:
                mb = f.stat().st_size / 1e6
            except OSError:
                continue
            audio_min = mb * _MIN_PER_MB.get(f.suffix.lower(), 1.0)
            secs += audio_min * 60 * speeds.get("transcribe", 0.8)
            if "notes" in chosen_options(job):
                secs += max(1, audio_min / 20) * speeds.get("part", 25.0)
    elif job.type == "read-aloud":
        for f in files:
            secs += _guess_words(f) / LISTEN_WPM * 60 * speeds.get("read-aloud", 0.5)
    elif job.type == "tidy-sheet":
        opts = chosen_options(job)
        for f in files:
            try:
                from .sheets import read_table
                n = len(read_table(f)[1])
            except Exception:                           # noqa: BLE001 (a guess only)
                n = 200
            calls = -(-n // SHEET_ROWS)
            secs += 1 + calls * (("spelling" in opts) + ("categorize" in opts) + ("split" in opts))                 * speeds.get("part", 25.0)
    elif job.type in ("photo-listing", "read-scans", "sort-photos"):
        secs += len(files) * speeds.get("vision", 20.0) * (1.5 if job.type == "read-scans" else 1)
    elif job.type == "ask-files":
        qs = len(questions_from(job.format))
        words = sum(_guess_words(f) for f in files)
        secs += qs * speeds.get("part", 25.0) + words / 4000 * 3
        if "summaries" in chosen_options(job) or not qs:
            secs += sum(max(1, _guess_words(f) // 2500) for f in files) * speeds.get("part", 25.0)
    elif job.type == "translate":
        n_lang = max(1, len(option_values(job, "to")))
        for f in files:
            secs += max(1, -(-_guess_words(f) // TRANSLATE_WORDS)) * n_lang * speeds.get("part", 25.0) * 1.3
    elif job.type == "photo-batch":
        mark = job.watermark.strip().lower()
        files = [f for f in files if not (mark.endswith(".png") and
                                          str(f).replace("\\", "/").lower().endswith(mark))]
        secs += len(files) * speeds.get("photo", 1.5)
    elif job.type == "proofread":
        for f in files:
            secs += max(1, -(-_guess_words(f) // PROOF_WORDS)) * speeds.get("part", 25.0)
    elif job.type in PAPER_GUESS:
        from . import paperwork
        secs += paperwork.guess_seconds(job, files, speeds)
    elif job.type in COMFY_GUESS_S:
        from .picturetools import pieces_from
        n = len(pieces_from(job.format)) if job.type == "music" else len(files)
        if job.type == "illusion-art":
            n = max(1, n) * int(option_value(job, "versions") or 4)
        elif job.type == "restyle-video":
            n = max(1, n) * max(1, int(option_value(job, "length") or 5) // 5)
        elif job.type == "character-spin":
            n = 3 if option_value(job, "views") == "quick" else 6
        secs += n * speeds.get(job.type, COMFY_GUESS_S[job.type])
    return {"files": len(files), "seconds": secs, "problems": problems}


PAPER_GUESS = ("pdf-tools", "explain-letter", "hide-details", "meeting-minutes", "bank-budget", "resume-tailor",
               "mail-merge", "alt-text", "duplicate-photos")             # paperwork.PAPER_TOOLS
# Picture editor: about 4.5 min a picture on a 12 GB card (its request is read on the processor),
# measured in the showcase test 2026-11-09; a turnaround is per view. Learned speeds replace these.
COMFY_GUESS_S = {"remove-bg": 8.0, "edit-picture": 270.0, "restore-photo": 150.0,
                 "animate-photo": 240.0, "music": 60.0, "fix-spot": 270.0, "merge-pictures": 270.0,
                 "relight": 270.0, "restyle": 270.0, "redraw": 270.0, "make-bigger": 270.0,
                 "character-scenes": 270.0, "character-spin": 280.0, "sketch-to-picture": 40.0,
                 "illusion-art": 40.0, "make-3d": 120.0, "restyle-video": 600.0}


def needs_problem(settings, job: "Job") -> str:
    """Why this tool can't run on this PC yet ('' = fine)."""
    tool = TOOLS[job.type]
    from . import picturetools
    uses_comfy = "comfy" in tool.needs or (job.type == "restore-photo"
                                           and not picturetools.restore_is_true(job))
    if job.type == "restore-photo" and not uses_comfy:
        from .doctor import ffmpeg_exe
        if not ffmpeg_exe(settings.comfy.ffmpeg):
            return f"Task '{job.name}': restoring photos needs FFmpeg. Setup (F10) > System check installs it."
    if uses_comfy and tool.ready:
        from .doctor import comfy_models_dir
        try:
            mdir = comfy_models_dir(settings)
        except Exception:                               # noqa: BLE001 (finder trouble = not found)
            mdir = None
        kind = option_value(job, "kind") if job.type == "music" else ""
        if not mdir:
            return (f"Task '{job.name}': {tool.name.lower()} needs ComfyUI. Setup (F10) > "
                    "System check installs it.")
        if "sdxl" in tool.needs and not sdxl_installed(mdir):
            return (f"Task '{job.name}': {tool.name.lower()} needs an SDXL picture model. Setup (F10) > "
                    "Models offers one.")
        missing = [p for p in picturetools.needed_packs(job.type, {kind} if kind else set())
                   if not picturetools.pack_ready(mdir, p)]
        if missing:
            return (f"Task '{job.name}': {tool.name.lower()} needs "
                    + " and ".join(picturetools.pack_offer(p, mdir) for p in missing)
                    + ". Setup (F10) > System check > DOWNLOAD, or the button on the Tools form.")
    if "qpdf" in tool.needs:
        from .paperwork import qpdf_exe
        if not qpdf_exe():
            return (f"Task '{job.name}': the PDF toolkit needs qpdf (free). Setup (F10) > System check > "
                    "qpdf > INSTALL.")
    if job.type == "meeting-minutes" and job.inputs and all(
            Path(i).suffix.lower() in (".txt", ".md", ".srt", ".vtt", ".docx") for i in job.inputs):
        return ""                                       # a transcript needs no ears
    if "voice" in tool.needs:
        from .addons import voice_python
        if tool.id in HEARING_TOOLS and hearing_ready(settings):
            pass
        elif not Path(voice_python()).exists():
            return (f"Task '{job.name}': {tool.name.lower()} needs Joe's voice add-on first. "
                    "Setup (F10) > System check > \"Joe's voice\" > SET UP.")
    return ""


def paperwork_qpdf() -> str | None:
    from .paperwork import qpdf_exe
    return qpdf_exe()


def sdxl_installed(mdir) -> bool:
    from . import comfy
    return any(m.family == "sdxl" and m.folder == "checkpoints" for m in comfy.scan_models(mdir))


# --------------------------------------------------------------------------- readiness
def tool_status(have: dict) -> list[dict]:
    """For the TOOLS badge: each tool, whether it can run on this PC now, and what's missing.
    have: voice, vision (None = Ollama off), ollama, ffmpeg, comfy, packs {id: {ready, offer}}."""
    from .picturetools import needed_packs
    out = []
    packs = have.get("packs") or {}
    for t in TOOLS.values():
        if not t.ready:
            continue
        why = ""
        if "voice" in t.needs and not have.get("voice") and not (t.id in HEARING_TOOLS and have.get("whispercpp")):
            why = "needs Joe's voice add-on (about 500 MB)"
        elif "ollama" in t.needs and not have.get("ollama"):
            why = "needs Ollama and a writing model"
        elif "vision" in t.needs and not have.get("vision"):
            why = ("needs a vision model" if have.get("vision") is False
                   else "needs Ollama running with a vision model")
        elif t.needs == ("ffmpeg",) and not have.get("ffmpeg"):
            why = "needs FFmpeg"
        elif "qpdf" in t.needs and not have.get("qpdf"):
            why = "needs qpdf (a free PDF program)"
        elif "comfy" in t.needs:
            if not have.get("comfy"):
                why = "needs ComfyUI"
            elif "sdxl" in t.needs and have.get("sdxl") is False:
                why = "needs an SDXL picture model"
            elif "ffmpeg" in t.needs and not have.get("ffmpeg"):
                why = "needs FFmpeg"
            else:
                missing = [p for p in needed_packs(t.id) if not (packs.get(p) or {}).get("ready")]
                if missing:
                    why = "needs " + " and ".join((packs.get(p) or {}).get("short", p) for p in missing)
        out.append({"id": t.id, "name": t.name, "ok": not why, "why": why})
    return out
