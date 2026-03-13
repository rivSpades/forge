# Change log

## 2026-03-12

**Prompt:** Implement Phase 2 parallel planning pipeline: when CEO marks an idea as interested in the digest, trigger Architect + Designer + Marketing Strategist in parallel, each with a paired Reviewer, then PM synthesis → CEO Briefing → Notion (4–6 hours). Use asyncio + AsyncAnthropic, no LangGraph.

**Changes:**

- **utils/claude_client.py**
  - Added `TOOL_WEB_SEARCH` and `_sanitize_schema()` / `_build_agent_params()` for shared param building.
  - Sync `call_agent()` now uses `_build_agent_params()`; tools list is normalized (e.g. `"web_search"` → API tool definition).
  - Added `async_call_agent()` for parallel agent calls using `utils.async_claude.async_claude`.

- **agents/architect.py**
  - Added `_record_to_prompt(record)` and `async run_architect_for_idea(idea_id, record)` that call `async_call_agent`, save to `architect/architect-{idea_id}.json`, and return the plan dict.

- **agents/designer.py**
  - Same pattern: `_record_to_prompt(record)` and `async run_designer_for_idea(idea_id, record)`, output to `designer/designer-{idea_id}.json`.

- **agents/marketing_strategist.py**
  - Same pattern: `_record_to_prompt(record)` and `async run_marketing_strategist_for_idea(idea_id, record)`, output to `marketing/marketing-{idea_id}.json`.

- **agents/arch_reviewer.py, design_reviewer.py, marketing_reviewer.py, plan_reviewer.py**
  - Added `run_*_reviewer_for_idea(idea_id)` to review a single output file (for use after the parallel planning step).

- **agents/planner.py**
  - Replaced single-agent “plan” flow with full Phase 2 pipeline:
    1. Fetch judged idea by `idea_id` with `plan_requested=True`.
    2. Run Architect, Designer, Marketing Strategist **in parallel** via `asyncio.gather` with 4-hour timeout; on timeout or failure, use partial results where available.
    3. Run paired reviewers (arch, design, marketing) for that idea.
    4. Call `run_project_manager(idea_context, arch_plan, design_plan, mktg_plan)` and save brief to `project_manager/ceo_brief_{idea_id}.json`.
    5. Run plan reviewer for the briefing.
    6. Push briefing to Notion via `push_briefing_to_notion(brief, judge_score)`.
    7. Update `judged_ideas`: `plan_requested=False`, `notion_url`, `ceo_brief_path`, and send CEO notification via `_send_notification`.

- **utils/notion_client.py**
  - Added `import json` for `build_notion_blocks`.
  - `push_briefing_to_notion`: `idea_summary` can be a string (schema) or object with `title`; `projected_mrr` access is safe when missing.

Scheduler and `check_plan_requests` unchanged: hourly check sets `plan_requested=True` on “PLAN REQUEST — idea_id”; every 5 minutes the planner runs for all such ideas via `run_planning_pipeline(idea_id)`.

---

**Prompt:** Reviewer gave output like "ESCALATED: This output cannot be revised at the design level. The core product concept — ...". Require reviewers to focus on checklist-based assessment only, no political/meta-commentary.

**Changes:**

- **agents/arch_reviewer.py, design_reviewer.py, marketing_reviewer.py, plan_reviewer.py**
  - Added shared `REVIEWER_SYSTEM_INSTRUCTIONS`: reviewers must only assess against the checklist; PASS/REVISE/ESCALATE with concrete, actionable notes only. No commentary about product concept, "cannot be revised at X level," or process; no political or meta-commentary. REVISE = failed check IDs + what to change; ESCALATE only when output is out of scope, with one short sentence on which checks could not be assessed.
  - Injected the actual checklist (id + description) into the user prompt so the model has the criteria. Added `_checks_text(checklist)` and use it in both batch and single-idea flows.
  - Replaced generic system prompts with `REVIEWER_SYSTEM_INSTRUCTIONS` so all four reviewers (arch, design, marketing, plan) behave consistently and stay on-task.

---

**Prompt:** Designer (and other agents using web_search) was returning raw API Message object when the model used tools — no tool loop, so the first response had only tool_use blocks and no text. Fix by implementing a tool loop and avoiding storing raw Message dumps.

**Changes:**

- **utils/claude_client.py**
  - Added `_content_has_text_block`, `_build_tool_result_blocks`, `_content_to_message_param` to detect text blocks and build tool-result continuation messages from server-side tool results (e.g. `web_search_tool_result`).
  - Added `_run_tool_loop_sync` and `_run_tool_loop_async`: when tools are used, loop up to 5 rounds — each round if the response has no text block but has tool result blocks, append assistant message + user tool_result message and call `messages.create` again until the model returns a text block.
  - `call_agent` and `async_call_agent` now use the tool loop when `tools` is non-empty, so agents (designer, marketing, architect) that use `web_search` always get a final text response instead of raw tool_use content.

- **agents/designer.py**
  - When `json.loads(text)` fails, if `text` looks like a raw Message dump (`Message(id=` or starts with `Message(`), skip saving and log instead of storing `{"raw": text}`. Same guard in revision loop, new-ideas loop, and async `run_designer_for_idea` (raises `ValueError` there).

- **agents/marketing_strategist.py**
  - Same guard as designer: skip saving or raise when the response is a raw Message dump instead of storing `{"raw": text}`.

---

**Prompt:** After designer revised from reviewer notes, running the design reviewer again did nothing. Fix so reviewer runs on revised output.

**Changes:**

- **agents/design_reviewer.py, arch_reviewer.py, marketing_reviewer.py, plan_reviewer.py**
  - Removed `.lte("revision_count", max_revisions)` from the batch pending query. The reviewer was only selecting rows with revision_count ≤ max_revisions (2). After the designer runs a revision it sets revision_count = previous + 1, so an artifact at 2 became 3 and was excluded; the reviewer had nothing to process. Reviewers now select any artifact where reviewer_pass is not True, regardless of revision_count. The revision limit is enforced by the planning agents (designer/architect/marketing), not by the reviewers.
  - Added a clear message when there are no pending rows: e.g. "[design_reviewer] no designer artifacts pending review (all passed or none found)" so running the reviewer when there is nothing to do is explicit.

---

**Prompt:** Marketing agent (and same for architect/designer) did nothing when run after the artifact had been reviewed 2 times — user wants to be able to run the agent again.

**Changes:**

- **agents/marketing_strategist.py, architect.py, designer.py**
  - Removed `.lte("revision_count", max_revisions)` from the revision-candidates query in `run_marketing_strategist`, `run_architect`, and `run_designer`. Previously, after 2 review cycles revision_count exceeded max_revisions (2), so the agent skipped the artifact and did nothing. Revision candidates are now any artifact with `reviewer_pass=False` and non-null `reviewer_notes`, regardless of revision_count, so manual re-runs always process pending feedback. The batch `limit` still caps how many items are processed per run.
