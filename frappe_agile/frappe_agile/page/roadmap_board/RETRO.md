## Conversation Retro Report

**Date:** 2026-06-10
**Conversation Title:** Build Roadmap front-end page on Frappe Agile

### Prompt Summary

- Planning Prompts: 1
- Execution Prompts: 1 (combined planning + execution)
- Total Prompts: 2 (1 user instruction + 1 clarification answer)

> Note: this session had a single substantive user message. The `/model` line
> was a CLI command, not a task prompt, so it is excluded from the counts.

### Prompt Log

| # | Prompt Summary (first ~15 words) | Category |
|---|----------------------------------|----------|
| 1 | "build a front end page on frappe agile … Roadmap … Kanban … Sprint vertical, Projects horizontal … get to work … retro report" | Planning + Execution |
| 2 | (Answer to my clarifying question) "Which grid orientation?" → "Match Stitch screenshots" | Planning |

### What Went Well

- **Single, well-structured brief.** The request followed a clean user-story
  format (As / I want / So that) with explicit acceptance criteria, a live
  design reference (Stitch link + 3 annotated screenshots), and a defined
  deliverable (retro). That let me go from prompt to working code with only
  one clarification.
- **Concrete acceptance criteria.** Each criterion (Kanban grid, sprint status,
  acceptance %, checkbox for accepted items) mapped directly to a build task,
  so there was no ambiguity about "done."
- **Authoritative visual reference.** The screenshots resolved most layout
  questions (card anatomy, status badges, progress bars, checklists) without
  back-and-forth.
- **Explicit autonomy ("kindly get to work").** Clear permission to implement
  end-to-end rather than stopping at a plan.

### Improvement Suggestions

1. **Resolve internal contradictions before sending.** The text said
   *"Sprint on the vertical axis, Projects on the horizontal axis,"* but all
   three screenshots showed the opposite (Projects = rows, Sprints = columns).
   This forced one clarification round-trip. Stating *"follow the screenshots
   where they differ from my text"* up front would have removed it.
2. **Name the row/lane identity.** The criteria assume "Projects" segment the
   rows, but in the actual data almost every Sprint has no linked Project — the
   real lane key is `sprint_prefix`. Flagging *"group rows by sprint prefix /
   team; project link is usually empty"* would have pre-empted a design
   judgement I had to infer from the data.
3. **Specify the acceptance-% formula.** "Story Point Acceptance Percentage"
   could mean accepted/committed, accepted/target, or count-based. I chose
   accepted-points ÷ total-points (computed live). One sentence defining it
   would remove the assumption.
4. **State the read/write intent for the checkbox.** "Indicate accepted items
   with a checkbox" is ambiguous between a *display indicator* and an
   *editable toggle*. I built it as a read-only indicator (matching the
   screenshots); confirming intent avoids a possible rework.

### Estimated Prompt Savings

The session was already efficient — effectively **2 prompts** for a complete,
verified feature. Folding suggestions #1–#4 into the original brief (4 extra
sentences) would have **eliminated the 1 clarification round-trip**, bringing it
to a true **single-prompt delivery**. No redundant or scope-creep prompts were
observed; the main lever is front-loading the four ambiguities above into the
initial message.
