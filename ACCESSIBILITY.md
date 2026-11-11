# Accessibility

Joe should be usable by everyone, including people who use screen readers, keyboards, larger text or high contrast. This page says honestly what works today and what doesn't yet.

## Where it runs

Joe's interface runs in your web browser (Edge, Chrome, Firefox, Safari) on Windows, macOS and Linux, and can talk and listen when the voice add-on is installed.

## Seeing the screen (Setup > Display & sound)

- **High contrast:** two themes made for low vision: *High contrast (dark)*, white and yellow on black, and *High contrast (light)*, black on white. Every box and button gets a solid border, the dimmed "hint" text is shown at full strength, and the keyboard focus gets a thick outline. If your computer is set to ask for more contrast (Windows: Contrast themes; Mac: Increase contrast), the *Modern (follows day and night)* look turns high contrast by itself. Windows' own contrast themes (forced colors) win over Joe's colors.
- **Large text:** *Normal*, *Large* or *Larger* makes everything bigger: text, buttons, boxes and the tab bar, which wraps onto a second line when it has to. *Text size* (14 to 48) fine-tunes it on top. Your browser's own zoom (Ctrl and +) works too.
- **Easy-to-read font:** Atkinson Hyperlegible, made by the Braille Institute so letters like I, l and 1 never look alike.

## Screen readers

- Joe tells your screen reader (NVDA, JAWS, Narrator, VoiceOver, Orca) what's happening while he works, without anything showing on the screen: a run starting, each task finished, progress at 25, 50 and 75 percent, and the run's end. A failed task is announced straight away (as an alert). Setup > Display & sound > *Screen reader announcements*: progress and finished/failed jobs (the default), only finished and failed jobs, or off.
- Short messages that pop up at the bottom ("Saved", "Setup finished") are read out too.
- Tabs, Setup pages and every button are real buttons with plain-word names, and every screen works from the keyboard (F1 lists the keys).

## Moving through results by voice (Talk, F4)

After Joe answers with a list, or when you ask about the morning report, you can say (or type): "read the third one", "next", "go back", "again", "skip to the CHECK items", "how many are there?", "read the list" or "read them all". Add "in the report" to move through the morning report. Joe reads the words exactly as written (no AI in between), so it's instant. Anything else you say goes to Joe as usual.

## Motion

Joe's face in Talk (F4) blinks and moves his mouth while he speaks. If your computer is set to reduce motion, or you pick "Still" in Setup > Voice & Talk > "Joe's face in Talk", he still changes face for each state (listening, thinking, talking, happy, worried, sleepy) but nothing blinks or flaps. "Off" hides him. The face is decorative and hidden from screen readers; everything he says is in the chat as text. The opening screen is skipped when your computer asks for less motion.

## Known limitations

- The retro looks (green, amber, white screens) use a terminal style with glow and scanlines; their contrast is lower than the high contrast themes. Pick a high contrast theme if text is hard to read.
- Pictures Joe makes have no automatic descriptions in the Files tab yet (the "Picture descriptions" tool on the Tools tab writes them for pictures you choose).
- The step-by-step builder (F6) and some Setup pages have long forms; a screen reader reads them in order, but there are no landmarks inside a page yet.
- Progress inside a single long step (one big video, one long download) is announced only when the step ends, not while it runs.
- Voice navigation understands English commands only.
- Nobody who relies on a screen reader has tested Joe yet. If you do, your report is very welcome.

## Report a barrier

If something is hard or impossible for you to use, please [open an issue](https://github.com/sirgijoe/joe-ai/issues/new/choose) and say what you were trying to do and what got in the way, plus your device and any assistive technology you use. Accessibility problems are treated as bugs.
