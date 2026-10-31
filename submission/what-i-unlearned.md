# What I unlearned

Five days building Inbox Helper with Claude Code. I treated the AI as a coding and thinking partner—not a tool to delegate to, but a teammate to work with. I set direction, checked outcomes, and raised the scope iteratively each day. Each item below is a habit I brought in, what happened this week when I followed it, and what I do instead now.

## 1. "If the output is bad, use a better model"

**Before.** When the AI got something wrong, my first instinct was to reach for a stronger model.
**This week.** I acted on that instinct twice, and both times measurement proved me wrong.
- Day 1: *"these are due to us using basic models."* The best free models were 3.5× slower and no better. A
  clearer prompt fixed the drafts.
- Day 5: *"remove nemotron… test other models like qwen."* Every model I could get filed a person waiting for an
  answer as "no reply needed" some of the time.

**Now.** I measure before I switch, and I change one thing per experiment. When every model fails the same way, the
problem is in the design, not the model.

## 2. "If the AI can be told, tell it"

**Before.** I treated the prompt as the place to put rules.
**This week.** Three rules failed while they lived in the prompt:
- **The sign-off** varied between drafts until code wrote it.
- **"No reply needed"** began as my own prompt, *"ask llm to turn ignore flag on"*. It quietly filed real people
  under it until code decided it from the sender.
- **The injection email** was flagged, yet still got a polite reply, until code quarantined it.

**Now.** The AI writes language. Anything that must be exact, or must not go wrong, is decided by code, and the AI
isn't even offered the choice.

## 3. "Green means done"

**Before.** A passing CI run meant I could move on.
**This week.** G110, the boundary case I wrote specifically to protect "no reply needed", failed on every CI run from
day 4 until I finally looked on day 5. The gate was green because one failure was within its tolerance, and I never opened the report. On day 2
I had also called another failure "noise" after a single comparison; it was a real bug (passwords weren't treated
as sensitive and were being sent to the AI).

**Now.** I read which cases moved, not just the colour. The gate has cases that must always pass, and I repeat a fix
uncached before I believe it. One good run proves nothing.

## 4. "My job is writing the code"

**Before.** I would have spent these five days typing a CRUD app.
**This week.** I wrote the intent before any code, made the product decisions from options the agent laid out, ran
two agents side by side on separate files, and spent most of my time reading output:
- drafts,
- eval reports,
- the UI as a user.

What I caught by reading changed the design more than anything I typed: the injection reply, the unclear flags, the
"Hi Maria, Hola Maria" greeting, the stale G110 failure.

**Now.** My work is specifying, deciding and verifying. The agent writes the code, and I am responsible for knowing
whether it is right.

## Still unlearning

- **Keeping the paperwork current.** My day-1 directive said "revise this file as the rules change", and I didn't.
  I rebuilt it on day 5 from my prompts and logs.
- **Raising the load in the planned order.** I went past my own "out of scope" line (Gmail, sign-in, deployment)
  but skipped the stress test I had planned: 500+ messy messages.

## For the next person

- Write `intent.md` yourself, before the first prompt, and say which decisions stay with you.
- Have the agent check model names and limits against the live API. Memory and blog posts were wrong on day 1.
- Read twenty real outputs before trusting any score.
- Give the eval gate a list of cases that must pass whatever the tolerance, and open the report even when it's green.
- When the same rule keeps failing in the prompt, move it to code.
