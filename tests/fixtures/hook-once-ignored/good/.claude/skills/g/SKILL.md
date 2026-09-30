---
name: g
description: Greets once per session.
hooks:
  SessionStart:
    - hooks:
        - type: command
          command: echo hi
          once: true
---

Greet the user.
