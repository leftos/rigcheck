---
name: demo
description: Runs the demo through a subagent.
---

Dispatch the `helper` agent with the demo brief. For a wide search, dispatch `general-purpose`.

Run the `dispatch` skill first, and load the `plan-execution` skill. `nextup` loads the profile.
Hand the map to the profile's explore agent, or to the `claude-security:explore` agent.

```text
Dispatch the `ghost` agent.
```
