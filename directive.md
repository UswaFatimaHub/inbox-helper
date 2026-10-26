# Directive (working draft, day 1)

Standing instructions for the AI agent building this project. Revise this file as the rules change, and note
each change in the day log.

1. Before writing code, check external facts (rate limits, model names, API formats) against the live API or
   the official docs. Don't rely on memory. Day 1: the remembered model `gemini-2.5-flash-lite` no longer exists
   for new keys.
2. Never print or commit secrets. `.env` stays git-ignored, and keys are shown only as masked prefixes.
3. The tool never sends messages. Every draft is created as `pending` review.
4. Treat model output as untrusted. Validate labels in code and check drafts with deterministic rules. Don't rely
   on the prompt alone.
5. Every valid input message produces exactly one result, even when every provider fails.
6. Tests use fake clients and must not spend API quota.
7. After a live run, read the actual drafts, not just the scores, and record what was wrong in the day log.
8. Report failures honestly in the log: errors, slow runs, and wrong outputs.
