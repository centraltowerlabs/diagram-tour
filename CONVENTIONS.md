# Tour Narration Conventions

How to write narration for the diagram-tour pipeline so the matcher
can automatically illuminate the right nodes and clusters at the right
time. These rules apply to both Claude-generated narration (when the
skill scaffolds + fills in scripts) and human-edited narration.

When this document moves into the public skill repo, it becomes the
single source of truth for both the narration generator and human
editors.

## TL;DR

Five rules. Following them gives you arrows and cluster highlights
synced to the spoken word, automatically.

1. **Use exact node names.** When narrating about a specific node,
   say its label verbatim (e.g. *"triage.ts is the entry point"*,
   not *"the orchestration code is the entry point"*).
2. **Use exact cluster names.** Refer to clusters by their declared
   name (e.g. *"the Worker process cluster"*, not *"the gray box at
   the top"*).
3. **List items by name, in narration order.** When mentioning
   multiple nodes from a cluster, name each one — they each get an
   arrow.
4. **Closing summaries reference clusters, not metaphors.** Trace the
   loop using cluster names so the camera can sequentially highlight
   them.
5. **Avoid pronouns that hide identity.** *"It runs the request"* →
   *"orchestrator runs the request"*. The matcher can't follow "it".

## Why these rules exist

The pipeline does two automatic-highlighting passes per stop:

- **Per-node arrows** — fire when the narration contains a node's
  label (or one of its label lines for multi-line labels).
- **Cluster boxes** — fire when the narration contains a cluster's
  natural name.

Both passes use **exact, full-phrase matching** against the narration's
words (case- and punctuation-insensitive). They do not do fuzzy or
semantic matching. So the more your prose matches the diagram's actual
labels, the more highlighting you get for free.

## Rule 1 — Use exact node names

The matcher looks for each node's label-line text in the narration.
Multi-line labels work (any line can match), but the simpler the
phrasing, the higher the hit rate.

| Avoid | Prefer |
|---|---|
| "the orchestration code is the entry point" | "**triage.ts** is the entry point" |
| "the IMAP poller saves messages" | "**imap.client.ts** saves messages" |
| "the queue manager enqueues jobs" | "**queue.ts** enqueues jobs" |

For nodes with directory-prefixed labels (e.g. `components/triage/extraction-panel.tsx`),
the matcher also accepts the bare filename (`extraction-panel.tsx`),
so either form works.

## Rule 2 — Use exact cluster names

Each cluster has a *natural name* — the text before any parenthesized
annotation or path. The matcher uses that name for cluster-level
highlights. Use it verbatim in narration.

| Cluster label in `.dot` | Natural name | Mention in narration as |
|---|---|---|
| `"Worker process  (src/worker)"` | "Worker process" | "the Worker process cluster" |
| `"Domain library  (src/lib)"` | "Domain library" | "the Domain library" |
| `"Task Queues"` | "Task Queues" | "the Task Queues" |
| `"Server actions  (src/actions/triage.actions.ts)"` | "Server actions" | "Server actions" |

Avoid:

| Avoid | Why |
|---|---|
| "the gray box at the top" | Position/color won't match anything |
| "the lavender area in the middle" | Same |
| "the worker thingy" | Vague paraphrase |

## Rule 3 — List items by name, in narration order

When narrating a cluster's contents, name each node you want
highlighted. Each name triggers a separate arrow at the moment it's
spoken.

| Avoid | Prefer |
|---|---|
| "Three files: the entry point, the poller, the handler." | "Three files: **index.ts**, **imap.client.ts**, **extraction.processor.ts**." |
| "The four APIs cover async needs." | "**setTimeout**, **fetch**, **DOM events**, and **Promise** cover async needs." |

The narration order should match the visual order if there's a
natural reading flow (left-to-right, top-to-bottom in the cluster), so
arrows appear in a coherent sequence.

## Rule 4 — Closing summaries reference clusters, not metaphors

The closing stop of a tour typically traces a request flowing through
the system. To get the camera to sequentially highlight each cluster
during this trace, **use the cluster names verbatim**.

| Avoid | Prefer |
|---|---|
| "a message arrives, gets processed, ends up in the database" | "a message arrives in the **External** cluster, flows through the **Worker process** into the **Domain library**, and lands in the **Prisma models**" |
| "the loop closes when the user reviews and the system learns" | "**Server actions** persist the user's decisions; the analytics CLI feeds those labels back into prompt tuning" |

## Rule 5 — Avoid pronouns that hide identity

The matcher can't follow "it" or "this" back to a referent. If you
want a node or cluster highlighted, name it.

| Avoid | Prefer |
|---|---|
| "It's the entry point." | "**triage.ts** is the entry point." |
| "This is where async results land." | "The **Macrotask Queue** is where async results land." |
| "We tour each in order." | "We tour each cluster in order." |

The exception: pronouns are fine when the narration is *about*
something general, not about a specific node or cluster.

## Stop structure

Each stop follows the same shape:

```markdown
## Stop N — Title

<one paragraph of narration, ~50–100 words>
```

- **N**: stop number, starting at 1.
- **Title**: short — usually the cluster's natural name, or
  "Orientation" / "Closing" for FULL stops.
- **Body**: one self-contained paragraph. Reads in roughly 25–35
  seconds at the pipeline's default Piper pacing.

Multi-paragraph stops are technically allowed but discouraged — they
extend a single static framing too long. Split into two stops if the
content warrants it.

## Frontmatter — stop → cluster mapping

Every tour markdown starts with YAML frontmatter declaring which
cluster each stop focuses on:

```yaml
---
diagram-tour: 1
diagram: ./architecture.dot
stops:
  1: FULL
  2: cluster_engine
  3: cluster_apis
  4: cluster_queues
  5: cluster_loop
  6: FULL
---
```

- `diagram-tour: 1` — spec version.
- `diagram` — relative path to the `.dot` file.
- `stops` — map of stop number → cluster id (or `"FULL"` for full-image
  stops, typically Orientation and Closing).
- For multi-cluster focal areas, use a list:
  `7: [cluster_analytics, cluster_scripts]`.

## What the matcher will *not* do

- **No semantic synonyms.** "Database" in narration won't match a
  cluster called "Prisma models". Use the actual name.
- **No camelCase splitting** (yet). `extractFromMessage` is matched as
  a single token. Most narration won't include the camel form
  literally — prefer "the extract function" or just the filename.
- **No partial-cluster matching.** "Server" alone won't match a
  cluster called "Server actions". Use the full natural name.

## What the matcher *will* do

- Case-insensitive, punctuation-insensitive matching.
- Multi-line label matching (any line of the label can match).
- Bare-filename matching for path-prefixed labels (so
  `extraction-panel.tsx` matches a node labeled
  `components/triage/extraction-panel.tsx`).
- Multi-word phrase matching (window sizes 1 through 4 tokens).
- First-match-wins per node (multiple mentions don't fire multiple
  arrows for the same node within one stop).

## When in doubt

The pipeline prints a per-stop summary of arrow events and cluster
events when it runs. If a node or cluster you expected to be
highlighted isn't in the summary, the rule it violated is almost
always Rule 1 or Rule 2 — the narration is using a paraphrase instead
of the actual label.

## Source anchors

- The matcher implementation: `scripts/generate-architecture-tour.py`,
  functions `find_node_mentions`, `find_cluster_events_for_stop`,
  and `cluster_natural_name`.
- A reference tour following these conventions:
  [`architecture-tour.md`](./architecture-tour.md) (the portal tour).
- A second reference (smaller, for quickly understanding the format):
  [`../diagrams/event-loop-tour.md`](../diagrams/event-loop-tour.md).
