# Surfing AI Runtime Rules

- Parallelize only independent work.
- Keep discovery and verification agents read-only.
- Give write agents non-overlapping file ownership.
- Preserve the parent agent as the final coordinator.
- Require test or inspection evidence before claiming completion.
- Never bypass inherited permissions or approval prompts.
- Stop for explicit human approval before destructive, publishing,
  marketplace, or visibility-changing actions.
