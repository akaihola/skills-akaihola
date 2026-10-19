## Context

Antti chose this on 2026-10-19 (steward [decision 13](http://hopeli/my-knowledge/agents/steward/asks/13-chores-into-issues.md?f), Q3). In 2026-W42 he spent
13 prompts relaying review findings to the thread that had implemented
the work ([agent@hopeli:~/my-knowledge/agents/steward/reports/2026-W42.md](http://hopeli/my-knowledge/agents/steward/reports/2026-W42.md?f), section 7), and relaying between threads remains his
largest kind of friction ([agent@hopeli:~/my-knowledge/agents/steward/reports/2026-10-19-session-analysis.md](http://hopeli/my-knowledge/agents/steward/reports/2026-10-19-session-analysis.md?f), finding 2). Paced reviews, acceptance
checks and review threads find what needs fixing, but the fix request
reaches the implementing thread only when Antti copies it there.

kandev-pacer's launch records (`~/.local/state/kandev-pacer/t3/*.json`,
keys `tracker`, `issue`, `thread`) map each paced issue to its T3
thread, and the `t3-start-thread` helper in this repository can already
`send` to a thread. A follow-up whose prompt ends in `...` parks until
the pacer admits it, so it doesn't jump the queue.

## Work

1. Let the helper find the implementing thread from a tracker and an
   issue number, using the launch records (for example
   `send --tracker PATH --issue N`). Refuse when no record or no live
   thread exists, and say so.
2. In the skill, tell reviewers: when findings need changes to work a
   known thread did, send them to that thread as a paced follow-up,
   with the evidence and what "done" means, instead of handing them to
   Antti. When the thread is gone or archived, file a follow-up issue
   in the same tracker.
3. Note the steward's side in the skill: review issues it files say to
   do this.

## Done when

- [ ] `--dry-run` resolves a real paced issue to its thread and
      refuses an issue with no record.
- [ ] The skill tells reviewers when to send and when to file instead.
- [ ] Tests cover the lookup.
