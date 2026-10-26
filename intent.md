# Intent: Candidate Inbox Triage

## Problem

Recruiters receive candidate messages about different issues, including application status, interview scheduling, document requests, withdrawals, and general questions. Sorting messages and writing repetitive replies takes time.

## User

A recruiter who needs to process a backlog of candidate messages efficiently without losing important requests or sending inappropriate replies.

## Desired outcome

Build a tool that accepts candidate messages, groups them by intent, drafts concise replies, and presents every draft for human review.

## Scope

- Accept CSV or JSON input.
- Classify messages into a defined set of intents.
- Generate a short reply using the message and supplied recruiting policies.
- Flag ambiguous, unsupported, or sensitive requests for review.
- Let a reviewer approve, edit, or reject a draft.
- Keep an auditable record of the original message and review outcome.

## Constraints

- No automatic sending of messages.
- No invented interview dates, hiring decisions, or company policies.
- Invalid input must produce understandable errors.
- The tool must work on a sample dataset without requiring access to a real candidate database.

## Initial success criteria

- Every valid input message produces one traceable result.
- Every result has a valid intent label.
- Drafts do not invent facts absent from the message or supplied policy.
- Ambiguous messages are flagged for human review.
- Automated tests cover normal cases, malformed input, and difficult messages.
- A reviewer can identify and correct an unsuitable draft before it is used.

## Out of scope

Email-provider integration, automatic message sending, production authentication, and complex multi-agent orchestration.

## Intent set (decided day 1)

`application_status`, `interview_scheduling`, `documents`, `offer_and_compensation`, `withdrawal`,
`accommodation_request`, `complaint`, `general_question`, `other`.
A message gets one primary intent and an optional secondary intent. `accommodation_request`, `complaint` and `other`
always go to the top of the review queue.
