# 0002. One graph thread per turn, conversation history in domain tables

Status: accepted

## Context

LangGraph persists state per thread. The usual setup is one thread per conversation, with the message list growing inside the checkpoint. I also need the owner's approval to pause a turn with an interrupt and resume it later with the decision.

Those two things collide. An approval can stay pending for hours. During that time the customer keeps sending messages, and a thread with a pending interrupt is not a place to run a fresh input: the new run and the pending interrupt compete for the same thread state.

The panel also needs the conversation as rows it can list, filter and show to the owner, whatever the checkpoint format is.

## Decision

A turn runs on its own thread, with the thread id derived from the turn id. Messages, turns and approval requests are domain tables. At the start of a turn, `load_context` reads the recent messages and the pending approval of the conversation into the state.

A turn that needs approval stays interrupted on its own thread. New customer messages start new turns, which see in their context that a request is pending and can answer "still waiting" or deal with an unrelated question. When the owner decides, a resume job for that turn goes through the same per-conversation queue group as customer messages, so a resume and a new turn never run at the same time.

Checkpoints are execution state: crash recovery inside a turn and pending approvals. They are deleted a few days after the turn completes.

## Alternatives rejected

One thread per conversation. It is the documented default and keeps history for free. I rejected it because of the pending approval problem above, because it makes the checkpoint the source of truth for the conversation, and because history would grow in a serialized blob that I would have to trim anyway.

No interrupt, approval only as a domain record that a later job executes. It works and is simpler to reason about. I kept the interrupt because the turn that resumes has the full state of the plan (what was asked, what was already checked, what to say next) without rebuilding it, and because the pause and resume are visible in the trace as one turn.

## Cost of this choice

I do not use LangGraph's built-in message memory, so windowing and summarizing history are mine to write. The checkpoint tables grow by one thread per turn and need a retention job. And the rule "a resumed turn validates again before writing" has to be kept by hand, because the world may have changed between the pause and the resume.

## As built

The checkpointer is LangGraph's `AsyncPostgresSaver` on the same PostgreSQL, with durability `exit`: one checkpoint when a turn stops, which in practice means a turn waiting for the owner. Tests resume a paused turn through a second checkpointer object that shares nothing with the first but the database, which is how they stand for another worker process. A turn that is retried deletes its thread before it starts, so the graph is never given new input on top of a paused run, the case the documentation leaves undefined. Checkpoints are deserialized against an explicit list of this project's types.
