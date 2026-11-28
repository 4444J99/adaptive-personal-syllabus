# ADR 010 — The learner loop stays CLI: width-aware terminal text for the phone case

- Status: accepted (bounded decision for #56, MTR-024)
- Decided: 2026-11-28, in PR `work/mentor/accessible-interface` (ranked-queue loop)
- Context: #56, implementation plan posted 2026-11-18 (comment 6988701195),
  re-verified live at main `6965aa8e` before building. Parent epic #27,
  control plan #21, Wave 3. Depends on #51 (merged via PR #97 at
  `b888f586`) and #52 (merged via PR #91) — the dependency gates the plan
  recorded as "both planned" are fully satisfied, so the delivery half of
  #56 is unblocked. #57 (install-and-verify) stays planned; per the plan,
  the constrained-device test runs from a checkout until then, and this
  decision says so.
- Evidence base: live tree at `6965aa8e` (post-#98 merge, 0 open PRs),
  verified through the GitHub API, a source-tarball read, a step-1
  inventory via the installed CLI (synthetic corpus/profile/plan), and a
  step-6 SIGKILL probe (24 kills mid-write). The full loop completes in
  ~0.6s per command (`corpus ingest`, `profile init --phone-only
  --medium audio`, `plan generate`, `plan show`, `plan encounter`,
  `plan artifact`, `plan encounter-complete`, `ledger verify`,
  `chamber run`). A phone-only profile gets `access_adjustment:
  phone_safe` plus the phone-route step and voice-memo / no-response
  routes (desktop profile: 1 encounter step; phone profile: 3).
  The SIGKILL probe left no half-written plan rows and no partial
  receipts across 24 kills; `ledger verify` stayed ok with a matching
  checkpoint, and both interrupted commands resumed cleanly — #52's
  crash-consistency property holds at this head.

## Decision 1 — CLI-as-is: no TUI, web, or audio-first platform

The loop's interface stays the Click CLI; no TUI wrapper, web surface,
or mobile app is built for #56. Reasoning: the issue forbids
preselecting a technology and requires "no unnecessary parallel
platform", and the observed evidence gives no platform a job to do —
the loop already completes end to end on a phone-shaped terminal
(40 columns, the narrowest SSH portrait width observed), with the
phone-only encounter adaptation already in place
(`profile init --phone-only`, `encounter.py` phone route,
`plan encounter` single-encounter view with `worked_explanation` /
`no_response_now` routes). A TUI wrapper would duplicate an interaction
model that already works, and the ONWARD 0.2 TUI suggestion stays a
suggestion ("Do not build a full TUI yet") until an observed failure of
the CLI justifies it. Counterexample that would overturn this: a
learner-facing step that cannot be typed, read, or completed through
the CLI on the observed terminal — none was found; every command in
the loop exits 0 at 40 columns.

## Decision 2 — Width-aware wrapping for learner-facing terminal text

Learner-facing text printed to the terminal wraps to the live terminal
width when stdout is a terminal that reports it (minimum 20 columns):
`plan encounter` text output, `plan show` / `plan generate` text and
md renderings. The width comes from the terminal itself
(`os.get_terminal_size` on stdout), never from the environment: the
repo's public-surface contract (ADR 005, #42) forbids `os.environ` /
`getenv` in src modules, and the tty reports the width directly — a
phone SSH session's stdout is a terminal, so the observed device case
is covered without any environment read. Reasoning: at a 40-column
terminal the encounter text is byte-identical to the 80-column run
(821 chars, longest line 144 chars) — Click help wraps, but
learner-facing `click.echo` output does not, so on a phone SSH session
every encounter step needs horizontal scrolling. That is the one
observed defect on the constrained device, and wrapping at the echo
boundary is the smallest change that fixes it: the renderers stay pure
(their tests are unchanged), the wrap applies only where text is
printed for a human, and the word sequence is preserved exactly.
Structural lines pass through unwrapped (headings, `**...**` metadata
lines that carry fingerprints, blank lines); list items wrap with a
two-space continuation indent so markdown lists stay valid. Piped
output has no terminal width, so it stays unwrapped — the historical
bytes, which the round-trip tests pin — because the wrap is a display
behavior for a known terminal, not a change to what the commands emit.
JSON formats stay unwrapped — they are machine output, and wrapping
them would break parsers. Artifact file bytes stay unchanged — a
markdown working sheet is read in a viewer that soft-wraps, and the
bytes are authorization-bound (ADR 009), so rewrapping them would
change the sha256 identity the publish step enforces.

## Decision 3 — The device inventory is an explicit open input, not an assumption

No record of the intended learner's actual devices exists anywhere in
the repo: no learner record names a device, and the profile schema
expresses devices only as `access_conditions.phone_only: true/false`
plus `medium` and `source_available`. Per the plan's own fallback, the
decision proceeds only for the devices actually observed in step 3 —
this VM's terminal at 40 columns (a phone SSH portrait simulation) and
at 80 columns — and the untested list is explicit: real phones
(iPhone/Android, any SSH client), tablets, screen readers, and any
audio-only playback device. Reasoning: "available devices" is the
question's central term and it is currently undefined; any interface
choice made for a named device would be a guess, and the plan forbids
guessing. The inventory must come from Anthony or from a learner
record before any device-specific claim is made.

## Decision 4 — Interruption recovery is already proven; no new recovery code

The issue's interruption-recovery acceptance leg is satisfied by #52's
merged work, not by new code in this PR. Reasoning: the step-6 probe
killed `plan generate` and `plan encounter-complete` mid-write 24
times (SIGKILL at 0.02–0.5s delays on a 300-document corpus); after
the kills `ledger verify` reported ok with a matching checkpoint, the
database held only the baseline plan row (no half-written plans), the
ledger held zero partial `encounter.receipt` events, and both commands
resumed cleanly. A dropped connection therefore loses at most the
in-flight command, never the learner's state — which is exactly what
the acceptance leg requires. Re-proving it with new recovery code
would duplicate #52.

## Rejected alternatives, with counterexamples

- **TUI wrapper around `core:cli` primitives (ONWARD 0.2).** The
  leading candidate in the plan, rejected on the observed evidence:
  the loop completes on the constrained device already, so the wrapper
  would be a parallel platform with no failing step to fix — and the
  issue's acceptance leg forbids exactly that. Counterexample that
  would revive it: a step that cannot be completed through the CLI on
  the observed terminal (Decision 1's overturn condition).
- **Web surface.** No observed need: every learner-facing step runs
  locally in under a second with no network, and a web surface would
  add a server, a deployment, and a second product path for a loop
  that already completes. Counterexample: a learner who cannot run the
  CLI at all — no such learner is named in any record.
- **Audio-first app.** The audio medium already exists as a profile
  option (`--medium audio`) with read-aloud guidance in the encounter
  steps, and the phone route already offers a voice-memo response
  under two minutes. A separate audio app would duplicate that. The
  plan's "which interactions require visual notation/practice rather
  than audio" question is answered by the existing medium rules:
  notation, diagrams, code, and literary form require an inspectable
  page (README), which the encounter steps already say.
- **Wrapping artifact bytes or JSON output.** Artifact bytes are
  authorization-bound (ADR 009) and read in soft-wrapping viewers;
  JSON is machine output. Wrapping either would change bytes other
  consumers depend on, for no learner benefit.

## Remaining uncertainty

- No real phone has been observed: the 40-column result is a terminal
  simulation, not a phone SSH session, and real-phone behavior (client
  wrapping, font, input method) is untested until #57's install story
  lets a learner run the loop on a device.
- The wrap floor is 20 columns: below that, prose cannot wrap
  usefully, and the CLI makes no promise. No terminal narrower than 40
  columns was observed.
- `plan artifact` still requires a wing selected at `profile init`
  time; a profile created without `--wing` fails the artifact step
  with "Wing is not selected in this plan", and the README quickstart's
  first example omits `--wing`. That is a documentation gap, not a
  code defect, and it is out of this PR's lease scope.
