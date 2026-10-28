## Approved behavior

Carry the complete Task thread identity JSON line from the main task prompt into the initial prompt of every related child, fork or independently launched conversation. Keep the canonical tracker, stable issue ID, task reference and original main thread ID. Main task threads await the user’s settlement; supporting threads can settle after their work and obligations finish. Document this in the T3 coordination skill without changing T3 itself.

## Outcome

Merged the identity and settlement guidance in commit `d1676b6`. The skill applies to native tools, ACP and the helper, preserves the original task identity across projects, and distinguishes the main thread from supporting work. Read-only standards and specification reviews found no unresolved issues. Documentation-only change; diff and private-information checks passed.
