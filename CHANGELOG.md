# Changelog

## [1.06] — 2026-08-27

### Fixed
- **"Hey Jarvis" never worked.** Chrome refuses to start speech recognition
  without a real user gesture, and it was being started on page load — so it
  failed silently every time. Now armed on your first click or keypress, with
  a **live WAKE indicator** in the left rail (ON / OFF / MIC BLOCKED /
  UNSUPPORTED) and a manual ENABLE button, so it can never be silently dead
  again. A blocked microphone now says so explicitly and tells you how to fix it.
- **Boot sound never played** — same root cause. `AudioContext` starts
  suspended and can't make sound until a user gesture; the sound was fired on
  load and discarded. Now queued and released on first interaction.
- **CPU stuck at 0%.** `psutil.cpu_percent(interval=None)` measures "since the
  last call", which is an unreliable window under Flask's threaded server. Now
  measured over a real 0.15s interval every poll.

### Added
- **Proper JARVIS personality.** Composed, dry, British in register, addresses
  you as "sir" the way a capable aide does — at the start of a report, when
  confirming an instruction, when delivering something you won't like. Will
  state a disagreement plainly and then do it anyway.
- **File attachments.** Paperclip button or drag-and-drop onto the transcript.
  Text files are inlined as context; images go to the vision model. 400KB cap,
  with the attachment shown as a chip before sending and a thumbnail after.
- **Typewriter reveal** on Jarvis's replies, with a blinking caret.
- **Images develop in** — a generated image resolves from blurred to sharp
  with a scan line passing over it, rather than popping in.
- **Dedicated stop button** beside the mic — appears only while thinking or
  speaking, and cancels the audio, the in-flight request, *and* the typewriter
  in one press.
- **Chat sessions** in the left rail: new, select, pin (pinned sort to top),
  auto-titled from your first message, with message counts. Switching sessions
  also clears short-term context so conversations don't bleed together.
- **Cursor-reactive orb** — the orb drifts toward your pointer, the bloom
  drifts further for parallax depth.
- **Live clock, stat bars, input-level equaliser** that speeds up and brightens
  while listening, and a footer diagnostics strip.
- **`JarvisInstaller.py`** — a real GUI installer that downloads the latest
  version straight from GitHub, installs Python via winget if missing, installs
  dependencies, and creates a Desktop shortcut. Build it with
  `build_installer_exe.bat`.

- **Proper Windows installer wizard** (`jarvis_installer.iss`, built with
  `build_setup.bat`). Full Inno Setup wizard: language selection across 16
  languages, licence page, choice of install location, optional desktop and
  quick-launch shortcuts, progress bar, launch-on-finish, and a real
  uninstaller registered in Add/Remove Programs. Detects Python across the
  usual install locations and warns up front if it's missing rather than
  failing partway through. `config.py` installs with `onlyifdoesntexist`, so
  upgrading never overwrites your API keys.
- **`LICENSE.txt`** — MIT, with a note that API keys stay on your machine and
  provider costs are your own.

### Changed
- **Full visual rebuild** on a three-column console layout: system rail, orb
  stage, transcript. Much larger bloom, four rings at different speeds with
  single bright edges, five-stop gradient core with a blurred double. Stats as
  labelled bars instead of boxes; transcript with left-rules instead of chat
  bubbles. Masked grid background and scanlines. IBM Plex Mono + Space Grotesk.
- Theme buttons renamed NORMAL / FUNNY / SERIOUS, since they set personality
  mode as well as palette.

---

## [1.05] — 2026-08-20

### Fixed
- **Generated images now actually display.** Root cause: `image_gen.py`
  worked out the correct image format but never passed it back to the
  browser, which was hardcoded to assume PNG. When the model returned
  anything else, the browser couldn't decode it and showed nothing. The
  real format is now threaded through end-to-end, plus a visible fallback
  message if an image genuinely fails to decode.
- Provider clients were cached per *provider*, not per *key* — which would
  have silently reused the first key's connection for every key, making
  key rotation do nothing. Caching is now keyed by the actual key.

### Added
- **Any AI provider, auto-detected.** Works with a Gemini, OpenAI, or
  Anthropic key — new `llm.py` reads the key's format (`AIza…`, `sk-…`,
  `sk-ant-…`) and routes to the right provider automatically. Each has its
  own model fallback list, so rate limits still fall through to a backup
  model. The header and settings panel show which provider is live.
- **Multiple API keys with automatic fallback.** The setup screen takes one
  key per line. If a key runs out of quota, gets revoked, or stops working,
  Jarvis moves to the next one automatically and keeps going.
  - Keys can be from **different providers** — an exhausted Gemini key can
    fall over to an OpenAI or Anthropic key, each using its own correct
    API format and model list.
  - **Remembers which key worked.** Once it falls through to a working key,
    the next request starts there instead of re-trying the dead one every
    single time.
  - **Doesn't waste keys on real bugs.** Rate limits and auth/billing
    errors trigger rotation; a malformed-request error stops immediately,
    since that would fail identically on every key.
  - The settings panel shows the full chain, e.g. "3 keys stored, falling
    back in order: Gemini → Gemini → Claude."
- **Themes**: Dark (default), Light, and Oppenheimer (red, high-contrast).
  Switchable in the settings panel, saved across restarts. The whole
  interface is now driven by CSS variables rather than fixed colors.
- **"Open in Terminal"** button on code blocks — saves the code to a file
  and opens a terminal already sitting in that folder. It deliberately does
  **not** run the code: this app has broad PC control, so automatic
  execution of generated code is a real risk, not a convenience. Read it
  first, run it yourself.
- **Installer launching**: if you ask for an app that isn't installed,
  Jarvis now also checks your Downloads folder for an installer you've
  already downloaded and opens it. You still click through the setup
  wizard yourself — nothing installs silently, and nothing is downloaded
  from the internet on your behalf.

- **Theme = personality.** The theme picker now changes how Jarvis talks,
  not just how it looks:
  - **Dark** — normal. Standard personality.
  - **Light** — funny mode. Jokes, playfulness, riffing, while still doing
    the actual task properly.
  - **Oppenheimer (red)** — serious mode. No banter, precise and economical.
    Answer, execute, move on.
- **`build_installer.bat` now does everything itself** — installs Python via
  winget if it's missing, installs all dependencies and PyInstaller, builds
  the exe, and installs Inno Setup to build a proper installer. If the build
  fails it automatically retries without `--noconsole` so the real error is
  visible instead of the window vanishing.

- **Coding capabilities.** Jarvis can now check whether a dev tool is
  installed (`python`, `node`, `git`, `vscode`, `java`, `docker`, `rust`,
  `go`), and if something's missing it **asks** rather than assuming. Say
  yes and it opens a terminal with the install command ready — you press
  Enter to confirm, or close the window to cancel. Nothing installs
  silently.
- **Real project files.** "Save this as a project" writes the code to
  `Desktop\JarvisProjects\<name>\` as a proper file with the right
  extension, then opens it in VS Code (or Explorer if VS Code isn't
  installed). Existing files get numbered rather than overwritten.
- **Seven more PC capabilities**: media controls (play/pause/next/previous),
  window management (minimize/maximize/snap/switch/close), open any folder,
  search for and open files by name, create folders, and read or write the
  clipboard.

- **Persistent chat history.** Conversations now survive restarts — saved
  to `%APPDATA%\Jarvis\jarvis_history.json` (last 500 exchanges). The
  transcript restores when you reopen the app instead of starting blank,
  and Jarvis can search past sessions: "what did I say about the drone
  build last week". "Forget everything about me" wipes this too.
- **Ego.** Personality reworked toward confident, dry, a bit smug — the
  swagger points at how good Jarvis is, never at the user.

- **"How I got there" panel.** Every reply now has a collapsible trace —
  click it to see the action Jarvis chose, the inputs it extracted, what
  actually came back, which AI provider answered, and how much
  conversation context was in play. Shows sources too when a step has any.
- **Interactive faceplate.** The orb now has a two-piece faceplate that
  splits open on click, revealing the core. Opens automatically when Jarvis
  is listening, thinking, or speaking. Original design — not a
  reproduction of any existing character's suit.
- **`SUPABASE_LOGIN_SETUP.md`** — full walkthrough for Google login via
  Supabase, including the cross-PC settings sync table and RLS policy.

- **Google login via Supabase, actually wired in.** Sign in from the
  settings panel — Account section. Fully optional: if `SUPABASE_URL` isn't
  set in `config.py`, the app works exactly as before and the login button
  just says "not configured." `requirements.txt` now includes `supabase`.
- Refined the boot greeting for more presence: "Initializing complete.
  Connection established. Systems online."

### Fixed (post-1.05 patch)
- **Settings panel was rendering underneath the main content.** `header`
  and `main` had the same z-index, so as sibling stacking contexts at a
  tie, DOM order won and `main` painted over the settings dropdown
  regardless of its own z-index. `header` now explicitly outranks `main`.
- **Removed the faceplate** — it defaulted to fully covering the orb
  instead of enhancing it. Gone entirely rather than patched.
- **Removed the armor-rail icon** — wasn't landing visually. Removed
  clean rather than left half-working.
- **Removed the scanline/shimmer/sheen sweep animations** across the left
  panel, header, and stat boxes — read as glitchy lines cutting across
  CPU/RAM/the orb rather than a polish effect. The orb's own breathing,
  ring, and sonar animations are untouched.

### Changed

- Setup screen accepts any provider's key, not just Gemini.
- Existing single-key setups migrate automatically on first launch; nothing
  needs re-entering.
- Image generation stays on Gemini regardless of chat provider (it's the
  one with a free tier). Set `IMAGE_GEMINI_API_KEY` in `config.py` to keep
  images working while chatting through OpenAI/Anthropic.

### Notes
- Only the Gemini path has had real end-to-end use. OpenAI and Anthropic
  support is built against each provider's current documented API and
  covered by tests, but if something misbehaves, `llm.py` is the first
  place to look.

---

## [1.0.0] — 2026-07-14

Initial release.

### Core
- Voice-controlled PC assistant with a structured action schema for
  reliable command execution.
- Web-based HUD — animated orb (idle/listening/thinking/speaking), live
  transcript, CPU/RAM/temp/OS stats, settings panel.
- "Hey Jarvis" wake word plus push-to-talk. Speech recognition runs in the
  browser engine, not a bundled Python library.
- Neural text-to-speech (edge-tts) instead of the robotic Windows default.
- Custom app icon and a real Windows installer via PyInstaller + Inno Setup.

### PC control
- Open/close apps (curated list, then Start Menu shortcut search).
- Cursor movement, click, double-click, scroll, type text, press key.
- Volume, brightness, screenshot, lock/sleep/shutdown/restart with a
  10-second spoken cancel window.
- Open URLs, pull up YouTube search results, report system stats.

### Generation
- Image generation, shown inline and saved to `%APPDATA%\Jarvis\`.
- Code responses render in a monospace box with a COPY button.

### Memory and personality
- Permanent facts (name, preferences, language, profanity level) plus
  rolling short-term conversation history within a session.
- Adjustable profanity level and English/Hindi switching.
- Reply length adapts to the question instead of being hard-capped.

### Reliability
- Automatic model fallback on rate-limit errors.
- Fixed a startup race where the process exited right after opening the
  browser, killing the server.
- Fixed a `sys.stdout is None` crash in `--noconsole` builds.
