# skill-tiers

Analyses a skill definition — `SKILL.md` plus the files it bundles — and reports
which parts of it are carrying more agent freedom than they warrant, and could be
expressed as deterministic code instead.

This context is about **reading skills as artifacts**. It never executes the skill
it analyses and never looks at runtime traces.

## Language

### The artifact under analysis

**Subject**:
The skill being analysed — its `SKILL.md`, its bundled files, and its frontmatter.
_Avoid_: target, input, skill (bare, when ambiguous with the analyser itself)

**Body**:
The prose of a Subject's `SKILL.md` below the frontmatter. What stays in the
agent's context once the skill loads.
_Avoid_: content, markdown, instructions

**Bundled Script**:
An executable file a Subject ships and invokes, which runs without its source
entering context.
_Avoid_: helper, tool, code

### Segmentation

**Block**:
The smallest unit of a Body the analyser reasons about and reports on. Deliberately
not called a step — most Blocks are not steps.
_Avoid_: step, chunk, node, section, segment

**Directive**:
A Block that tells the agent to do something. The only kind of Block that gets
tiered.
_Avoid_: instruction, command, action, step

**Exposition**:
A Block that conveys facts the agent needs but commands nothing — file locations,
schemas, output formats, background. Never tiered; a Body legitimately consists
mostly of Exposition.
_Avoid_: documentation, reference, context

**Narration**:
A Block that describes what a Bundled Script already does. Reads like a Directive
but commands nothing, because the determinism it describes has already been
achieved. Mistaking Narration for a Directive is this context's characteristic
false positive.
_Avoid_: description, summary, docs

### Classification

**Freedom Tier**:
One of the three levels of agent latitude a Directive can be expressed at:
prose, parameterised script, or exact script.
_Avoid_: level, category, class, severity, degree

**As-Written Tier**:
The Freedom Tier a Directive is currently expressed at.
_Avoid_: current tier, actual tier

**Warranted Tier**:
The Freedom Tier a Directive's Fragility and Variability actually call for.
_Avoid_: recommended tier, ideal tier, target tier

**Tier Gap**:
A Directive whose As-Written Tier grants more freedom than its Warranted Tier.
The unit of finding this context exists to produce.
_Avoid_: opportunity, finding, issue, violation, smell

**Fragility**:
How costly deviation from one exact way of doing a Directive is. High Fragility
pushes the Warranted Tier down.
_Avoid_: risk, criticality, brittleness

**Variability**:
How much legitimate variation exists between invocations of a Directive. High
Variability pushes the Warranted Tier up.
_Avoid_: flexibility, generality, variance

**Signal**:
A textual pattern in a Block that is evidence for a classification. Evidence only —
a Signal never decides a Tier by itself.
_Avoid_: rule, heuristic, indicator, marker

### Cost

**Recurring Cost**:
The tokens a Block spends on every turn for as long as the Subject stays loaded.
What a Tier Gap costs if left unclosed, and why Bundled Scripts are cheaper than
prose that describes the same work.
_Avoid_: token cost, overhead, size
