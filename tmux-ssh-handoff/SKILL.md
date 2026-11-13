---
name: tmux-ssh-handoff
description: Prepare an authorized SSH command in tmux for Antti to submit and authenticate, then collect its result without handling passwords.
---

# Prepare SSH for manual authentication

For an authorized owner-account handoff, prepare the command in tmux instead of
asking the user to type or copy-paste shell text. The user's steps are submission
and authentication in the named pane. Follow account-specific requirements even
when the agent already runs on the destination computer. If this skill is absent
from the harness catalog, locate the existing installation; do not substitute a
chat command handoff. Existing deployment approval requirements still apply.

Use Bash and shell-quote argv. List panes before choosing an idle shell, or create
an isolated window. Send the complete command with `tmux send-keys -t PANE -l COMMAND`
and no Enter/C-m. Tell Antti the session/window/pane and let him submit it and enter
passwords there. Do not read password input or store credentials.

For T3 handoffs, arrange automatic delivery of output and exit status to the
originating thread when SSH closes; stream output in the pane and preserve
interactive prompts without capturing password input. Follow the
[tested output-reporting guidance](../t3-start-thread/references/ssh-output-trial.md)
and its stated limits. Report capture or delivery failures. Give the pane
instruction directly; automatic delivery replaces a request for a completion
message. Immediately before the SSH command, add three shell comments: thread
host and repository, thread title, and its exact HTTP(S) T3 browser link resolved
from the live server and thread ID. Physical GUI checks still need user evidence.

Verified 2026-11-06: `tmux new-window -d -t 0` failed with index 0 in use;
`tmux new-window -a -d -t 0:0 -n NAME 'bash --noprofile --norc'` successfully
inserted a new window. Literal command preparation without Enter succeeded.
The manual SCP/SSH authentication and GNOME launch subsequently succeeded on
2026-11-06; the remote build exited 0 and Antti reported the physical checks passed.
This does not establish passwordless access. Name a new *window* explicitly:
Antti initially looked for a new pane in window 0 and missed the prepared window.
A missing completion marker alone cannot prove a command is still running.

Verified 2026-11-06 in interactive Bash: `tmux send-keys` with `C-v C-j`
inserts a literal newline in an unsubmitted command. This keeps the SSH transport
and remote command on separate visible lines for review before Enter.

After saving a completed command's result, close the idle windows created for
that task; leave pre-existing windows and panes alone (user instruction,
2026-11-06). Identify them from `tmux list-panes -a` using the saved window name
and pane ID before `tmux kill-window`. Verified the same day: `display-message`
for a missing pane returned empty format fields with exit 0, so its exit status
alone does not establish that the pane exists. Check the actual pane list.

Verified 2026-11-13 on one Linux desktop: the tmux session lacked graphical
session variables that the systemd user manager supplied. For an SSH command
that needs a graphical password dialog, inspect only the required variable
names and preserve their verified values; keep credentials out of the command.
Reading those variables does not verify that a remote dialog will open. That
GUI path remained untested when this note was recorded.

Verified 2026-11-10: an isolated Bash window also accepted a two-line SSH
command using literal `C-v C-j`, with no Enter sent. Reading only that newly
created pane showed the complete command still at the Bash prompt. For a
connection through another host, keep the next-hop script visible for review
and preserve terminal stdin for SSH and sudo authentication. Preparing the
command does not verify that either hop or the remote script has succeeded.

Verified 2026-11-11: GNU tar archive creation treated a quoted `"*.pub"`
as a literal file name and exited 2, even with `--wildcards`. A local fixture
reproduced the failure. Let the remote shell expand the public-file glob:
`cd /remote/public-directory && tar -cf - manifest.tsv *.pub`. Archive and
extract a fixture and compare every file before retrying a transfer that
requires human authentication. The corrected command copied the real public
keys successfully; the authenticated SSH control connection allowed that
transfer to resume without repeating key creation. A later `sudo -n -v`
probe still required a password, so SSH reuse does not establish sudo access.
