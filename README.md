# Breach (working name)

A Minecraft agent that plans from certified world rules, never from stored
procedures. When a server changes a rule, it catches the change at the step,
revises the rule, and re-certifies it by replaying its own log.

Design and milestones: [docs/design.md](docs/design.md).

```bash
python3 -m unittest discover -s tests -t .
```

Started from the SchemaVoyager starter by Luiz Felipe Barbosa.
