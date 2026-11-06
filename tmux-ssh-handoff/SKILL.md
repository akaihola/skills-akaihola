---
name: tmux-ssh-handoff
description: Prepare an authorized SSH command in tmux for Antti to submit and authenticate, then collect its result without handling passwords.
---

# Prepare SSH for manual authentication

Use Bash and shell-quote argv. List panes before choosing an idle shell, or create
an isolated window. Send the complete command with `tmux send-keys -t PANE -l COMMAND`
and no Enter/C-m. Tell Antti the session/window/pane and let him submit it and enter
passwords there. Do not read password input or store credentials.

When output must return asynchronously, arrange a bounded existing scheduler
check of a local completion marker written after SSH exits. Retain its ID and
delete only that check at completion or its deadline. Capture output only after
the command has ended; physical GUI observations still require user evidence.

Verified 2026-11-06: `tmux new-window -d -t 0` failed with index 0 in use;
`tmux new-window -a -d -t 0:0 -n NAME 'bash --noprofile --norc'` successfully
inserted a new window. Literal command preparation without Enter succeeded.
The SSH authentication and remote desktop environment handoff were not yet tested
at that point. Do not infer passwordless access from successful preparation.
