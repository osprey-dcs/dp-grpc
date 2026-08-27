# Plan Documents

Official, version-controlled plan documents for dp-grpc work — design decisions and
implementation plans that benefit from PR review and a stable URL (for example, a handoff
document that a dp-service implementor reads cross-repo).

Layout: one directory per GitHub issue under `plan/tickets/<N>/`, typically containing
`plan.md` plus any companion documents (handoffs, design notes). Other kinds of plans may
get sibling directories later (e.g., `plan/releases/`).

Lifecycle:

- Draft and iterate in `~/dp/dev/tickets/dp-grpc/<N>/`, outside the repo; promote a document
  here once its decisions are settled, so the plan gets review without churning the repo
  during drafting.
- A committed plan is a **point-in-time record**, not a living document. It describes intent
  at the time of writing; the protos and `README.md` are authoritative for current behavior.
- Merged plans are not retro-edited to track later changes. If a plan turns out to be wrong
  about something material, add a dated correction note at the top rather than rewriting it.
