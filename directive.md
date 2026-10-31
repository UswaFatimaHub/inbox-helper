# Directive (final, day 5)

Standing instructions for the AI agent (Claude Code) that builds this project. Give it this file at the start of
every session.

The first version had 8 rules (day 1) and said "revise this file as the rules change". I didn't: during the week
the new rules lived in my prompts, TODO.txt and the day logs instead. This version was rebuilt on day 5 from those
sources. Each rule is tagged with the day the lesson happened and what triggered it. The change history is at the
end.

## Facts and secrets

1. **Check external facts against the live API or the official docs before writing code.** Rate limits, model
   names and API formats. Don't rely on memory. *(Day 1: Google no longer publishes free-tier limits.)*
2. **Never print or commit secrets.** `.env` stays git-ignored; keys are shown only as masked prefixes. *(Day 1)*
3. **Free-tier AI gets synthetic data only.** Hide identifiers (national ID, IBAN, card, phone, passport, email,
   password) before every model call. The reviewer still sees the original. *(Day 2: M039 sent a national ID and a
   bank account number to the model. Day 5: G111 sent a password.)*

## The tool never acts on its own

4. **The tool never sends messages.** Every draft is created as `pending` review. *(Day 1)* No send function
   exists anywhere in the code, and a test fails if one is added. Gmail gets drafts on approve, never sent
   mail. *(Day 3: `gmail.compose` would allow sending, and Google has no drafts-only permission.)*
5. **Decisions about people stay with a person.** Code or the AI may suggest (quarantine, "no reply needed"); a
   reviewer confirms. Blocking a sender is one click by a reviewer, never automatic. *(Day 1: a false detection or a forged
   "From" would shut out a real candidate for good.)*
6. **Fail closed.** Every route needs a signed-in user, including routes added later. The app refuses to start
   with a sign-in setting missing. The reviewer's identity comes from the login, never from the browser. *(Day 2)*
7. **Gmail: one dedicated test mailbox, never a real inbox.** Connecting any other mailbox is refused and its
   access revoked. *(Day 3)*

## The model is not trusted

8. **Treat model output as untrusted.** Validate labels in code and check drafts with deterministic rules. Don't
   rely on the prompt alone. *(Day 1)*
9. **A flag is not a fix.** When a message is dangerous, change what happens to it in code (category, no draft),
   not just its label. *(Day 1: M027 was flagged `prompt_injection` but still filed as a normal status question
   with a polite reply.)*
10. **Text that must be exact, and decisions that must not go wrong, are made by code, not requested from the
    model.** Greeting, sign-off and code-assigned categories. Strip what the model adds anyway. *(Day 4: greetings
    and sign-offs varied between drafts. Day 5: "no reply needed" moved to a sender rule after every model tried
    sometimes filed a person waiting for an answer under it.)*
11. **Detection rules stay narrow, and every rule gets a test for the case it must not catch.** *(Day 1: "please
    ignore my previous email" is a normal message.)*
12. **Every valid input message produces exactly one result, even when every provider fails.** *(Day 1)* After a
    run, check that the stored count matches. *(Day 1: a rollback in a shared in-memory test database silently
    lost one insert.)*

## Prompts are code

13. **Every prompt, taxonomy or policy change goes through the eval gate in CI.** Cache keys hash the exact prompt
    the model sees, so an edit never reuses stale outputs. Update `evals/baseline.json` only on purpose, in the
    same commit as the change. *(Day 2)*
14. **Measure the noise before setting a threshold.** *(Day 2: a cold re-run of an unchanged prompt moved about
    one case per metric, so the tolerance is 2, not 1.)*
15. **A green gate is not the end. Read which cases moved.** A named boundary case that fails is a regression to
    fix or record, even within tolerance. *(Day 5: G110, the boundary case added with `no_reply_needed` in prompt
    v4, failed on that same commit's CI run and on every run after. The gate passed each time and nobody read the
    report. The gate now has must-pass cases that fail it whatever the tolerance.)*
16. **Every new intent or rule gets a boundary case in the goldens.** *(Day 4: `no_reply_needed` came with G110,
    a real person asking an off-topic question who must still get a reply.)*

## Experiments and verification

17. **Tests use fake clients and must not spend API quota.** *(Day 1)*
18. **After a live run, read the actual drafts, not just the scores, and record what was wrong in the day log.**
    *(Day 1)*
19. **Change one thing per experiment.** *(Day 1: I changed the prompt and the models together and couldn't tell
    which one helped. The re-run showed it was the prompt.)*
20. **Before checking a change, make sure the running process is the new code.** *(Day 1: an old server still held
    port 8000, and I tested old behaviour. Day 3: `.env` was not loaded at startup, so `AUTH_MODE=dev` was
    ignored.)*
21. **Prove recovery by breaking it.** *(Day 2: killed the worker container at 5/15 messages; it resumed and
    processed only the other 10.)*
22. **Schema and data fixes ship as migrations, tested on a copy of real data first.** *(Day 2; day 4: the
    greeting backfill was checked on the 45 real Gmail drafts.)*
23. **Check UI changes with a scripted browser check:** desktop and phone width, light and dark. *(Day 4)*
24. **Check settings copied between environments.** *(Day 2–3: `PUBLIC_URL` copied from `.env` sent Google's
    sign-in callback on Render to 127.0.0.1.)*
25. **One run proves nothing. Repeat a fix uncached, across models, before believing it.** *(Day 5: prompt v7
    fixed M049 on the first run, then failed 5 of 8 uncached runs across Gemini Flash-Lite, dots and Nemotron. "Swap
    the model" was my first idea; the measurements showed the decision belonged in code.)*

## Working with me

26. **Product decisions are mine.** For each one, give options with a recommendation; I decide, and the decision
    is written down (TODO.txt "Decisions"). Examples: production before Gmail, Render, a test mailbox, drafts on
    approve, a manual fetch button, no bulk actions.
27. **Prefer the simplest thing that covers the need.** *(Day 2: no Redis; Postgres `SKIP LOCKED` already gives
    the job queue.)*
28. **Report failures honestly in the log:** errors, slow runs, wrong outputs, and my own mistakes. *(Day 1)* The
    day logs and the unlearning note are written in my words, not the agent's.
29. **Two agents in one repo each get their own files.** Say which files an agent may create or touch, and that
    another agent is working beside it. *(Day 1: one agent built the app while a second built the eval suite,
    told to "only create new files and only touch those files".)*

## Change history

Only the day 1 row was written into this file on that day. The other rows were added on day 5.

| Lesson from day | Rules | What triggered it |
|---|---|---|
| 1 | 1, 2, 4, 8, 12, 17, 18, 28 (first version, 8 rules) | Written at the start of day 1, then updated with the first API checks |
| 1 (evening) | 5, 9, 11, 19, 20, 29 | Prompt v2 run that changed two things at once, the stale server, M027, the flaky test |
| 2 | 3, 6, 13, 14, 21, 22, 27 | Deployment stack, first cold CI eval, personal data in M039, sign-in |
| 2–3 | 24 | Render sign-in callback went to localhost |
| 3 | 4 (Gmail part), 7, 20 (`.env` part) | Gmail integration |
| 4 | 10, 16, 22 (backfill), 23, 26 | Greeting by code, `no_reply_needed`, UI round |
| 5 | 15, 25; 3 and 10 extended | Reading the v6 CI eval report; the G110/M049 fix that held only in code; G111's password |
