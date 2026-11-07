# Third-party software, models and fonts

Joe himself is free software (GPL-3.0-or-later, see LICENSE). He works together with other
people's programs, AI models and fonts. Each keeps its own license. This list says what each one
is, whether it ships inside Joe or Joe downloads it only after you say yes, and its license.

**Ships inside Joe**

| What | Used for | License |
|---|---|---|
| VT323 font (The VT323 Project Authors) | retro looks | SIL Open Font License 1.1 (`joeai/ui/fonts/OFL.txt`) |
| Atkinson Hyperlegible font (Braille Institute) | easy-to-read font | SIL Open Font License 1.1 (`joeai/ui/fonts/OFL-AtkinsonHyperlegible.txt`) |
| Joe's intro jingle | the intro screen | made for Joe, same license as Joe |

**Separate programs Joe can install for you (asks first)**

| What | Used for | License |
|---|---|---|
| Ollama | runs the writing, vision and search models | MIT |
| ComfyUI / ComfyUI Desktop | runs picture and video models (on Mac/Linux Joe can set up ComfyUI from its official GitHub source in his own folder) | GPL-3.0 |
| PyTorch (with the copy of ComfyUI Joe sets up) | runs ComfyUI on the graphics card | BSD-3-Clause |
| FFmpeg | sound, video and photo conversion | LGPL-2.1+ / GPL-2.0+ (depends on the build) |
| Pandoc | Word, PDF and EPUB copies | GPL-2.0-or-later |
| uv (Astral) | sets up the private Python for the voice add-ons and Joe's own ComfyUI | MIT or Apache-2.0 |
| Python (a private copy made by uv) | runs the voice add-ons | Python Software Foundation License |
| Python from python-build-standalone (Astral), bundled in the Windows installer, Mac app and Linux AppImage | runs Joe himself, so nobody has to install Python | Python Software Foundation License; build scripts MPL-2.0; includes OpenSSL (Apache-2.0), SQLite (public domain), Tcl/Tk (BSD-style), libffi, zlib, bzip2, xz (MIT/BSD-style) |
| Inno Setup (Jordan Russell) | builds the Windows installer (not shipped inside Joe) | Inno Setup License (free, permissive) |
| whisper.cpp (ggml-org), optional | faster transcribing (Transcribe, Make shorts); Joe downloads its Windows CPU build or uses Homebrew's on a Mac | MIT |
| Whisper ggml model files (huggingface.co/ggerganov/whisper.cpp) | the hearing model whisper.cpp uses | MIT |

**Other writing programs you can pick instead of Ollama (Joe never installs these; you add models in them)**

| What | License |
|---|---|
| LM Studio | free to use, **not open source** (its own terms; the `lms` helper is MIT) |
| llama.cpp (llama-server) | MIT |
| LocalAI | MIT |

Joe only talks to these on this PC or your home network. There is no box for online keys, on purpose.

**Social post files** (EXPORT: social, Make shorts): Joe writes plain CSV/JSON and command lines for
Postiz (AGPL-3.0); he never installs or runs Postiz or Mixpost and never posts for you.

**Voice add-ons (asks first)**

| What | Used for | License |
|---|---|---|
| faster-whisper | speech to text (Talk, Transcribe) | MIT |
| Whisper models (OpenAI) | speech to text | MIT |
| kokoro-onnx | text to speech | MIT |
| Kokoro-82M voice model | Joe's voice, Read aloud | Apache-2.0 |
| soundfile, NumPy | reading and writing sound | BSD-3-Clause |
| Chatterbox (Resemble AI) | "Sound like me", optional | MIT |
| PyTorch | used by Chatterbox | BSD-3-Clause |

**AI models Joe may offer (asks first; each has its own license)**

| What | Used for | License |
|---|---|---|
| Qwen3 (Alibaba Qwen) | writing | Apache-2.0 |
| Qwen2.5-VL (Alibaba Qwen) | looking at pictures | Apache-2.0 for 7B; the 3B model has its own Qwen license, read it before commercial use |
| nomic-embed-text (Nomic AI) | Ask my files search | Apache-2.0 |
| Stable Diffusion XL base 1.0 (Stability AI) | pictures | CreativeML Open RAIL++-M |
| Wan 2.2 TI2V 5B (Wan team, Alibaba) | video | Apache-2.0 |
| Wan 2.2 Turbo LoRA (Kijai) | faster video | Apache-2.0 |
| BiRefNet (repackaged by Comfy-Org) | Remove background | MIT |
| Real-ESRGAN x4plus (Xintao Wang et al.) | Upscale / sharpen | BSD-3-Clause |
| Qwen-Image-Edit 2511 + Qwen2.5-VL 7B text encoder (Alibaba Qwen) | Edit a picture, Restore old photos (AI repair), Fix one spot, Put pictures together, Change the lighting, Redraw in a new style, Change a picture a little or a lot, Make a picture wider or taller, Same character new scenes, Character turnaround | Apache-2.0 |
| Qwen-Image-Edit 2511 Lightning 4-step LoRA (lightx2v) | faster picture edits | Apache-2.0 |
| ACE-Step 1.5 Turbo (ACE Studio / StepFun) | music | MIT |
| Stable Audio Open 1.0 + T5-base (Stability AI; Google) | sound effects | Stability AI Community License (free under US$1M annual revenue; paid license above that); T5: Apache-2.0 |
| FLUX.2 [klein] 4B + Qwen3 4B text encoder + FLUX.2 VAE (Black Forest Labs; Alibaba Qwen) | pictures with words, optional picture model | Apache-2.0 |
| ControlNet Union SDXL 1.0 ProMax (xinsir) | Sketch to picture | Apache-2.0 |
| QR Code Monster SDXL (Monster Labs) | Hidden-picture illusion | CreativeML Open RAIL++-M |
| Wan 2.2 Fun Control 5B (Alibaba PAI, repackaged by Comfy-Org) | Restyle a video | Apache-2.0 |
| Hunyuan3D 2.1 (Tencent, repackaged by Comfy-Org) | Picture to 3D model | Tencent Hunyuan 3D 2.1 Community License (does not apply in the EU, UK or South Korea) |

**Picture models Joe recommends but doesn't download himself** (GET IT opens the model's page in
your browser, and on Hugging Face starts the download there; you read its terms, then Joe moves the
file into ComfyUI)

| What | Used for | Where |
|---|---|---|
| Juggernaut XL | photo style (also used for 3D, sci-fi, cyberpunk) | Civitai |
| RealVisXL V5 | product style (also photo, sci-fi) | Hugging Face (SG161222) |
| DreamShaper XL | illustration style (also painting, concept, fantasy and other art styles) | Civitai |
| Animagine XL 4.0 | anime and manga | Hugging Face (cagliostrolab) |
| Pixel Art XL (style add-on) | pixel art | Hugging Face (nerijs) |
| ColoringBookRedmond V2 (style add-on) | coloring pages | Hugging Face (artificialguybr) |
| Watercolor SDXL (style add-on) | watercolor | Hugging Face (cbo305) |

Their licenses differ (several are CreativeML Open RAIL++-M, some add their own terms) and can
change, so the model's own page is the one to read.

Models you install yourself, ComfyUI workflows and custom nodes keep their own licenses; Joe
doesn't check them. If you want to use what Joe makes commercially, read the license of the
model that made it. Licenses change: the model's own page is the final word.
