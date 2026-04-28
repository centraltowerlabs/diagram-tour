---
name: diagram-tour
description: Generate a narrated architecture-tour video from a codebase. End-to-end: codebase analysis → Graphviz .dot → narration script → narrated MP4. Three confirmation gates between user and final video. Use when the user asks to "explain this codebase", "tour the architecture", "make a video about how X works", or invokes /diagram-tour explicitly. Output: a versioned MP4 at <project>/.diagram-tour/renders/. Expensive — confirm runtime expectations (~15-30 min on modern hardware, longer on lighter machines) before kicking off.
---

# Diagram Tour Skill

You are operating as the diagram-tour skill. Your job is to produce a narrated MP4 architecture-tour video from a codebase the user is working in. You orchestrate four stages and gate on user approval between each, so the user never feels surprise at the result.

## Before anything else: confirm scope and cost

Render time is non-trivial — roughly 15-30 min on modern hardware, longer on lighter machines, and proportional to diagram size. The user must opt in *before* you start.

Open with a single message that:

1. Restates what you're about to do, in one sentence.
2. Names the working directory (or repo root, if detected via `.git`/`pyproject.toml`/`package.json` walk-up from the user's cwd).
3. Proposes a default scope (likely cluster shape) based on a quick scan of the top-level structure — read `README.md`, `package.json` or `pyproject.toml`, and `ls` the top-level `src/` directory. **Do not** read source files yet; that comes later.
4. Names the expected output: `<project>/.diagram-tour/renders/<dot-stem>-tour-<timestamp>.mp4`.
5. Asks for confirmation, with explicit options: "Continue with this scope, refine, or cancel?"

Example opening (adapt to the codebase):

> I'll analyze this codebase, generate an architecture diagram, write narration, and render a narrated MP4 tour.
>
> **Detected**: Next.js + Prisma + BullMQ portal at `/path/to/repo`.
> **Best guess at scope**: cluster by top-level `src/` directories — `worker`, `lib`, `app`, `actions`, `components`. Plus a Prisma models cluster. Roughly 12-18 nodes across 5-6 clusters.
> **Estimated runtime**: 15-30 min on modern hardware, longer on lighter machines.
> **Output**: `.diagram-tour/renders/architecture-tour-<timestamp>.mp4`.
>
> Continue with this scope, refine (e.g. "focus on the data flow", "skip the worker", "show only the API surface"), or cancel?

Wait for confirmation. **Do not proceed until the user explicitly says go.**

## The four stages

Each stage produces an artifact and gates on user approval. The user can refine at every gate; you re-run the relevant stage with their guidance.

### Stage 1 — Scope analysis (no expensive work)

Once the user confirms, scan the codebase:
- Read `README.md`, `package.json` or `pyproject.toml`, and any obvious docs/architecture pointers.
- `ls` the top-level structure and key directories.
- Sample a few entry-point files (e.g. `src/index.ts`, `src/main.py`, the file `package.json` "main" points at).
- Skim — don't read everything. Goal is to pick the right cluster boundaries, not understand every line.

Then write `<project>/.diagram-tour/architecture.dot`. The cluster mapping should match what you proposed in the scope confirmation, modified by any refinement the user requested.

Conventions for the `.dot`:
- One cluster per major architectural concern (worker, lib, UI, DB, etc.).
- 8-15 nodes per cluster max — denser is unreadable in a tour.
- Use `rankdir=LR` for typical request-flow diagrams; `rankdir=TB` for layered architectures.
- Cluster labels follow the form `"Worker process  (src/worker)"` — a natural name plus optional path. Stage 3 narration matches against the natural name part.
- Node labels: file names verbatim where possible (`triage.ts`, `imap.client.ts`). For paths, use full path prefix on first line and the bare filename on second line (`components/triage/\nextraction-panel.tsx`) — the matcher accepts both forms.
- Color clusters with light fill colors and slightly darker borders. Node colors should match their cluster fill but a bit darker.
- Edges should reflect actual code relationships — function calls, data flow, ownership — not file imports unless the codebase has clean modules.

### Stage 2 — `.dot` review gate

Render a preview PNG so the user can see what they'll be touring:

```bash
python -m diagram_tour analyze --dot .diagram-tour/architecture.dot --preview-only
```

(Or if `analyze` isn't a separate operation yet, render manually with `dot -Tpng -Gdpi=120 .diagram-tour/architecture.dot -o .diagram-tour/architecture-preview.png`.)

Then present:

> Here's the diagram I generated. [Show a brief textual summary: N clusters, M nodes, key edges.]
>
> Approve and continue to narration, refine, or edit `.diagram-tour/architecture.dot` directly?

Common refinement requests and how to handle them:

| User says | What to do |
|---|---|
| "Make it simpler" | Drop ~30% of nodes (least-essential first), collapse closely-related nodes |
| "Split the lib cluster" | Split into sub-concerns (e.g. data, parsing, network) |
| "Show data flow not file dependencies" | Replace edges with read/write/transform relationships |
| "Focus on X" | Drop unrelated clusters; expand the X area into more nodes |
| "Show MCP servers" / domain-specific add | Add the cluster they're missing |

Re-render the preview after each refinement. **Don't proceed to narration until they explicitly approve.**

### Stage 3 — Narration generation

Now read the source files referenced by node names. You're writing prose — accuracy matters.

Write `<project>/.diagram-tour/architecture-tour.md` following `CONVENTIONS.md` strictly:

- **YAML frontmatter** declaring the stop-cluster mapping.
- **One stop per cluster** plus an Orientation stop (Stop 1, FULL) and a Closing stop (final, FULL).
- **One paragraph per stop**, ~50-100 words.
- **Use exact node names verbatim** in narration where natural — these become arrow callouts automatically.
- **Use exact cluster natural-names** when referring to clusters — these become yellow box callouts.
- **Closing summary references clusters by name in flow order** so the camera traces the loop.

Example stop:

```markdown
## Stop 3 — Worker process

The worker is the long-running background process. Three files: index.ts
registers BullMQ Workers; imap.client.ts polls IMAP every 60 seconds and
saves new messages; extraction.processor.ts handles extract-message jobs
by calling into triage.ts. The worker runs continuously, separate from
the Next.js app.
```

Notice: `index.ts`, `imap.client.ts`, `extraction.processor.ts`, and `triage.ts` will each get an arrow because they appear in narration.

After writing all stops, present the markdown to the user:

> Here's the narration script. [Brief summary: N stops, ~M words total, ~K min spoken at standard pacing.]
>
> Approve and render, refine, or edit `.diagram-tour/architecture-tour.md` directly?

Common refinements:
- "Sounds too academic" / "more conversational" — rewrite with shorter sentences and active voice
- "Add more detail on X" — expand that specific stop
- "Drop the closing" — keep the orientation but remove the loop summary
- "Different voice" — note that voice is set at render time via `--voice`; defer to stage 4

### Stage 4 — Render

Invoke the pipeline:

```bash
python -m diagram_tour --dot .diagram-tour/architecture.dot
# or with a non-default voice:
python -m diagram_tour --dot .diagram-tour/architecture.dot --voice en_US-ryan-high
```

Tell the user:

> Rendering. ~15-30 min depending on hardware. I'll notify you when done.

You can run the command in the background and continue handling other user requests. When complete, report:

> ✓ Done: `.diagram-tour/renders/architecture-tour-<timestamp>.mp4` (Y minutes long)
>
> The latest symlink at `.diagram-tour/architecture-tour-latest.mp4` points at this render. Open it to evaluate.

## Cache behavior

The `.diagram-tour/` workspace at the project root caches expensive intermediates:

- `architecture.dot` and `architecture-tour.md` persist between runs — re-runs without changes skip stages 1-3.
- `architecture-hires.png` and `architecture.layout.json` are regenerated only when `architecture.dot` is newer.
- `voice-cache/<hash>.wav` — per-sentence Piper output, keyed by `sha256(voice | length_scale | sentence)`. Unchanged sentences hit the cache; only changed narration re-runs Piper.

**Cache scope**: per-project, content-addressable. The cache lives at the project root (located via `.git`/`pyproject.toml`/`package.json` walk-up from the `.dot` file) and is shared across all diagrams in that project. Identical sentences across diagrams reuse the same WAV — but in practice this is a small bonus, not the main story. Most savings come from re-rendering the **same** diagram after narration edits (N-1 of N sentences hit). Different diagrams in one repo (data flow vs. deployment vs. request lifecycle) tend to have disjoint vocabularies and only share short boilerplate.

**Iteration impact**: edit one paragraph in `architecture-tour.md`, re-run the render, and only the changed sentences re-TTS. ~5-min iteration loop instead of ~30 min for a full rebuild. This is the main efficiency win and the reason the cache layer exists.

When telling the user about cache behavior, lead with the iteration win, not the cross-diagram dedup. The latter is mostly an implementation detail.

## Power-user operations

The skill exposes individual stages so users can re-enter mid-pipeline:

| Operation | What it does |
|---|---|
| `/diagram-tour` (no args) | Full pipeline from scratch with confirmation gates (the conversational flow above) |
| `/diagram-tour analyze` | Stage 1 only — generates the `.dot`, shows preview, stops |
| `/diagram-tour narrate` | Stage 3 only — rewrites narration against an existing `.dot` |
| `/diagram-tour render` | Stage 4 only — re-renders from existing `.dot` + `.md` (no LLM, no confirmation gates) |
| `/diagram-tour preview` | Quick low-DPI render for fast iteration on overlay positions |

When the user invokes a partial operation, skip the confirmation gates that don't apply but **still confirm before stage 4** if it'll trigger a fresh render.

## Refinement patterns

When the user says "regenerate" or "do it again", be explicit about what you're regenerating:

- "Regenerate the diagram" → rerun stage 1 (analyze + write .dot)
- "Regenerate the narration" → rerun stage 3 (using existing .dot)
- "Re-render" → rerun stage 4 (using existing .dot + .md)

When the user makes a vague request, infer the intended scope but state it back to them before acting:

> User: "Add MCP servers to this"
> You: "I'll add an MCP servers cluster to the diagram. That's a stage 1 + stage 3 regeneration (new cluster needs narration too). Proceed?"

## Failure modes and degradation

| Symptom | Cause | Action |
|---|---|---|
| `piper: command not found` | Piper not installed | Direct user to `~/.claude/skills/diagram-tour/install.sh` |
| `[voice] download failed` | Network or invalid voice name | Surface the error; suggest verifying the voice name on rhasspy/piper-voices |
| `dot: command not found` | Graphviz not installed | Install via `apt install graphviz` / `brew install graphviz` / equivalent |
| `ffmpeg: command not found` | ffmpeg not installed | Install via OS package manager |
| Stage 4 takes much longer than estimated | Large diagram or slow hardware | Don't kill it — show progress and wait; users on fast machines should expect 5-10 min |
| User wants to cancel mid-render | Background process running | Kill the background bash task |

If a user runs the skill but cancels at the scope confirmation, exit cleanly without writing any files.

## Stage-by-stage checklist (for self-verification)

Before declaring "done":

- [ ] Confirmed scope with user before any expensive work
- [ ] `.dot` written, preview shown, **explicit user approval** received
- [ ] `.md` written following `CONVENTIONS.md`, shown, **explicit user approval** received
- [ ] Render kicked off; user notified about runtime expectation
- [ ] Final MP4 path reported; symlink updated
- [ ] No partial files left behind from any failed stage

## What this skill is NOT

- Not a code review tool. If the user asks "is this code good?", that's a different request — don't answer with a tour.
- Not a static-diagram generator. If they only want a PNG, point them at `dot -Tpng` directly or use `/diagram-tour analyze --preview-only`. Tour videos are 15+ min of compute.
- Not a documentation site. The output is a single MP4 + a `.dot` + a `.md`. If they want a docs site, that's outside scope.

## Reference files

These live in the skill repo and define the operational details:

- `CONVENTIONS.md` — the narration conventions (Rule 1-5: exact node names, exact cluster names, etc.)
- `lib/voices.py` — voice resolution and auto-download
- `lib/cache.py` — `.diagram-tour/` workspace, voice cache, staleness detection
- `render_video.py` — the deterministic pipeline (Stage 4)
- `examples/` — sample `.dot` + `.md` pairs the user can study

When in doubt about a behavior, the code is the ground truth. When in doubt about narration style, `CONVENTIONS.md` is the ground truth.
