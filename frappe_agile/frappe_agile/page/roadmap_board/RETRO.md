## Conversation Retro Report

**Date:** 2026-06-11
**Conversation Title:** Build & extend the Roadmap front-end page on Frappe Agile

### Prompt Summary

- Planning Prompts: 2
- Execution Prompts: 1
- Total Prompts: 3 (substantive user messages; `/model` CLI line excluded)

### Prompt Log

| # | Prompt Summary (first ~15 words) | Category |
|---|----------------------------------|----------|
| 1 | "build a front end page on frappe agile … Roadmap … Kanban … sprint/project axes … get to work … retro" | Planning + Execution |
| 2 | (Answer to my clarifying question) "Which grid orientation?" → "Match Stitch screenshots" | Planning |
| 3 | "user stories should move from one sprint to next … make it wider, 4 sprints ahead … show future sprints … go to the future based on how many sprints" | Execution |

### What Went Well

- **Clean, story-formatted brief with a live design reference.** Prompt #1 gave
  user-story framing, explicit acceptance criteria, and the Stitch link +
  screenshots — enough to build end-to-end with a single clarification.
- **Incremental, well-scoped follow-up.** Prompt #3 bundled four related
  enhancements (move items, wider grid, future sprints, navigate forward) that
  all belonged to one coherent change set — a reasonable unit of work, not
  scattered asks.
- **Concrete, testable requirements.** "See at least 4 sprints ahead" and
  "move stories from one sprint to the next" map directly to verifiable
  behaviour (column width, drag-and-drop, auto-created future sprints).

### Improvement Suggestions

1. **State drag-and-drop semantics for edge cases up front.** "Move from one
   sprint to the next" left open: what happens at a Completed sprint, and what
   happens when the next sprint doesn't exist yet? I chose to block drops into
   Completed sprints and to auto-create a Draft sprint for empty future slots.
   One sentence ("block moves into completed sprints; create the next sprint if
   missing") would confirm intent and avoid possible rework.
2. **Quantify "future" and "based on how many sprints there are."** This was
   ambiguous between a fixed look-ahead and a proportional one. I implemented a
   "Plan ahead: 4 / 8 / 12 / 20 sprints" selector (default 8) plus inferred
   weekly cadence. Naming the default (e.g. "always show 8 ahead") removes the
   guess.
3. **Confirm the row-axis identity once, reuse thereafter.** The recurring
   subtlety is that "Project" rows are really `sprint_prefix` lanes in this
   data. Acknowledging that once ("group by prefix; project link is usually
   empty") keeps later prompts unambiguous.

### Estimated Prompt Savings

The engagement was efficient: **3 prompts** for a built, extended, and verified
feature. Folding suggestions #1–#2 into prompts #1/#3 (≈3 extra sentences) would
have removed the one clarification round-trip, making this a **2-prompt**
delivery. No redundant or scope-creep prompts occurred.

---

### Implementation Notes (for future reference)

- **Page:** `/app/roadmap-board` — desk Page in `frappe_agile`, files read from
  disk at load (no `bench build` needed; re-import the page JSON + `clear-cache`
  after changes).
- **Server:** `roadmap_board.py` →
  - `get_roadmap_data(group_by, lane, sprint_status, search, future_count)` —
    rows = lanes, columns = weekly windows (real + projected future), cells =
    sprints with live-computed acceptance %.
  - `move_work_item(work_item, target_sprint=None, lane, group_by, window_start,
    window_end)` — reassigns `Work Item.sprint` via `.save()` (so child tables,
    brought-forward flags, and velocity all recompute); auto-creates a Draft
    sprint for empty future slots (prefix grouping only); blocks moves into
    Completed sprints.
- **Client:** `roadmap_board.js` uses bundled `vendor/sortable.min.js`;
  drag is gated on `Work Item` write permission; horizontal scroll + "Today"
  button + "Plan ahead" selector for navigating future sprints.
- **Verified:** API + page + move endpoint return 200 over HTTP; move tests
  (existing-sprint move, future auto-create, completed-rejection) pass and were
  restored to leave no test data behind.
