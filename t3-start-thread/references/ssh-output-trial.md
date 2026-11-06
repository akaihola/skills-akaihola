# Reporting SSH output to a thread

When reporting an SSH command to a thread, stream its output in the tmux pane
as it arrives. Keep the helper’s detailed success receipt private and show a
short success or failure message in the pane. Remote program buffering may
delay output. Preserve the SSH exit status and report capture failures.

On 2026-11-06, a one-off trial submitted a non-interactive SSH command in a
tmux pane, with the user pressing Enter and entering the password in the pane.
After SSH exited, a local reporter read the command's redirected stdout and
exit status, then called the thread helper's `send --workspace --thread
--prompt-file`. The helper reported `delivered: true`, and the same thread
received the output and started a new turn. This establishes one successful
trial, not timing guarantees or a reusable implementation.

The trial kept the SSH password prompt on the terminal and redirected stdout
only. SSH or remote-command stderr remained in the pane and was not included
in the thread message. A failed SSH invocation, remote commands needing a TTY,
large output, and retries after an interrupted delivery were not tested. Treat
command output as untrusted data and avoid sending secrets. The helper saves a
private request record containing the message; see [message an existing thread](helper.md#message-an-existing-thread).

A second trial on 2026-11-06 piped SSH stdout and stderr through `tee`, saved
both SSH and `tee` exit statuses, and kept the helper's detailed receipt in a
private file. The terminal showed the command output and a one-line delivery
result; the thread received the output, and the helper reported `delivered:
true`. The password prompt stayed on the terminal and did not appear in the
captured output in that trial. A local simulation confirmed `tee` displayed the
first line before the command exited and that delivery failures show a concise
error; live SSH timing and a real delivery failure were not measured.

A 60-second SSH demonstration on 2026-11-06 produced all 60 numbered lines
in order; SSH and capture exited zero, and the helper confirmed delivery to the
thread. Per-line arrival times were not independently measured.
