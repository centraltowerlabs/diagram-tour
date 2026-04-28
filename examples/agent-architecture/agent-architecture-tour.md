---
diagram-tour: 1
diagram: ./agent-architecture.dot
stops:
  1: FULL
  2: cluster_external
  3: cluster_core
  4: cluster_tools
  5: cluster_memory
  6: FULL
---

# AI Agent Architecture — Tour

## Stop 1 — Orientation

This is the architecture of a typical Claude-style AI agent. Four
clusters in this diagram. External, where the user, the Anthropic
API, and MCP Servers sit. The Agent Core, where every request gets
routed. Tools, which the agent can invoke during a turn. And Memory,
where context across turns and sessions lives. We'll trace what
happens when a user sends a message and how the agent decides what
to do.

## Stop 2 — External boundary

The External cluster is the boundary. The User is the chat surface,
the CLI, or any API caller. The Anthropic API is what the agent
sends prompts to, and where streaming responses come from with
optional tool_use blocks. MCP Servers are external processes that
expose additional tools via the Model Context Protocol — a standard
way for agents to discover and call capabilities they didn't ship
with.

## Stop 3 — Agent Core

The Agent Core has four parts. The orchestrator is the agent loop;
it owns the request lifecycle from input to final output. The
context builder assembles each prompt: system instructions plus
conversation history plus retrieved facts from memory. The tool
router parses tool_use blocks from the model's response and
dispatches each call, in parallel when possible. The response
composer streams output tokens back to the user, formats citations,
and handles the final message.

## Stop 4 — Tools

The agent can call three built-in tool categories. bash runs shell
commands and manages background processes. file ops handle read,
write, edit, glob, and grep operations on the local filesystem.
web fetch retrieves HTTP resources, performs search queries, and
fetches documentation. Together these cover the everyday
capabilities a coding agent needs without reaching for any
external tooling.

## Stop 5 — Memory layers

Three memory layers with different lifetimes. working context is
turn-scoped and must fit in the model's context window; every
prompt rebuilds it fresh from the others. session memory holds
conversation-scoped state: summaries of earlier turns, pinned facts,
anything that should persist for the duration of one chat.
persistent memory is file-backed and survives across sessions: a
user profile, project conventions, long-lived preferences. The
context builder reads from all three; the orchestrator decides what
to write back after each turn.

## Stop 6 — The full loop

That's the loop. The User in the External cluster sends a prompt
to the orchestrator in the Agent Core. The context builder reads
from Memory and assembles the message. The orchestrator calls the
Anthropic API. If the response contains tool calls, the tool
router dispatches them — to built-in Tools or to MCP Servers — and
feeds the results back. The orchestrator may loop, calling the
model again with tool results, until the response is final. Then
the response composer streams the output. State updates land in
Memory, and the loop is ready for the next turn.
