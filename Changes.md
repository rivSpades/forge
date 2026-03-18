# Change log

## 2026-03-18 (Phase 3 build persistence + GitHub push)

**Prompt:** Save Claude Code build workspace under `projects/<project_name>` instead of `/tmp`, and add a final step to push the Claude-generated commits to GitHub.

**Changes:**

- **agents/build_orchestrator.py**
  - Clone/build into `forge/projects/<slug>` (stable local path) rather than `/tmp/forge-builds/...`.
  - Clone uses an authenticated Git remote URL when `GITHUB_BOT_TOKEN` is available.
  - After a successful Claude build, pushes `HEAD` to the repo default branch so Vercel/webhooks see the built code.
  - Ensures `origin` remote exists and is set to the expected push URL before pushing.

## 2026-03-12 (Launch Readiness Report email + one-click approve + launch sequence)

**Prompt:** When QA produces READY verdict, send Launch Readiness Report email (Resend) with summary table, Lighthouse pass/fail, Code Reviewer flags, and one-click approval link. Approval link calls GET /approve-launch?project_id=xxx&token=yyy (token = HMAC of project_id). On valid approval, run launch sequence: Vercel promote, set env vars, Railway deploy, Buffer first post, update status, send CEO confirmation.

**Changes:**

- **utils/env.py**
  - `LAUNCH_APPROVAL_SECRET`, `LAUNCH_GATEWAY_URL` (approval link base URL), `BUFFER_ACCESS_TOKEN`.

- **utils/launch_token.py** (new)
  - `create_launch_approval_token(project_id)` (HMAC-SHA256), `verify_launch_approval_token(project_id, token)`.

- **agents/qa_agent.py**
  - `LIGHTHOUSE_THRESHOLDS`: performance 70, accessibility 80, best-practices 80, seo 70. `build_launch_readiness_report` sets `verdict`: READY (all tests pass + all Lighthouse above threshold) or NOT_READY; adds `lighthouse_pass_fail` per category.
  - When `verdict == "READY"`, calls `send_launch_readiness_email(project_id, report, code_reviewer_flags)`.
  - `send_launch_readiness_email`: builds HTML (test results, Lighthouse table with pass/fail, Code Reviewer flags, one-click approval link), sends via Resend. Link: `{LAUNCH_GATEWAY_URL}/approve-launch?project_id=&token=`.

- **api/main.py**
  - `GET /approve-launch?project_id=xxx&token=yyy`: verifies token with `verify_launch_approval_token`, runs `launch_product(project_id)`, returns HTML success or error.

- **scripts/launch_product.py** (new)
  - `fetch_project`, `fetch_project_credentials` (decrypt with CREDENTIAL_ENCRYPTION_KEY), `generate_launch_post` (from content_calendar or placeholder), `send_launch_confirmation_email`.
  - `launch_product(project_id)`: (1) Vercel promote_to_production (2) Vercel set_env_vars from credentials (3) Railway deploy_to_production if railway_service_id (4) Buffer publish_immediately for channels (5) update projects status=active_growth, launched_at (6) send CEO confirmation email. Returns `{ok, error?, steps}`.

- **utils/vercel_client.py**
  - `promote_to_production(project_name, custom_domain?)`: list deployments, promote latest (v6/v9).
  - `set_env_vars(project_name, env_vars)`: POST to Vercel env API for production.

- **utils/railway_client.py**
  - `deploy_to_production(service_id)`: placeholder (log only); implement with Railway GraphQL when needed.

- **utils/buffer_client.py** (new)
  - `publish_immediately(channel_ids, content)`: create update + share now via Buffer API (BUFFER_ACCESS_TOKEN).

---

## 2026-03-12 (GitHub webhook Code Reviewer + QA Agent)

**Prompt:** Code Reviewer triggers via GitHub webhook on every push to development branch; FastAPI endpoint receives webhook, calls Code Reviewer with diff and Architect spec. QA Agent runs Playwright e2e (generated from Designer key_screens) and Lighthouse; build Launch Readiness Report.

**Changes:**

- **utils/env.py**
  - Added `GITHUB_WEBHOOK_SECRET` (optional) for verifying GitHub webhook signature.

- **api/main.py** (new FastAPI app)
  - `POST /webhooks/github`: verifies `X-Hub-Signature-256`, on `push` to `refs/heads/main` or `refs/heads/development` finds project by repo `github_repo`, fetches diff via GitHub compare API, fetches Architect and Designer spec from planning_artifacts, runs Code Reviewer in background, returns 200.
  - `GET /health`: health check.
  - Run with: `uvicorn api.main:app` (or `make run-webhook`).

- **utils/github_client.py**
  - `get_compare_diff(repo_full_name, base_sha, head_sha)`: returns diff text using GitHub API with `Accept: application/vnd.github.diff`.

- **agents/code_reviewer_agent.py** (new)
  - `run_code_review(diff, architect_spec, designer_spec=None)`: calls Claude with structured prompt; returns `{verdict, issues, security_violations}` as JSON. SECURITY CHECKS (any failure = FAIL): no hardcoded secrets, auth checked, input validated. SPEC COMPLIANCE: MVP features, screen match, error/loading states.

- **claude_agents/code_reviewer/CLAUDE.md**
  - Updated: tools `read_file`, `web_fetch`; effort low; explicit checklist and output format `{"verdict":"PASS|FAIL","issues":[],"security_violations":[]}`.

- **agents/qa_agent.py** (new)
  - `fetch_designer_spec(project_id)`: loads designer artifact for project’s judged_idea_id.
  - `run_qa(project_id, preview_url)`: async; generates Playwright tests from Designer key_screens via Claude, writes to temp file, runs `pytest --base-url preview_url`, runs `npx lighthouse preview_url --output=json`, returns `build_launch_readiness_report(pytest_result, lh_scores)`.
  - Requires: `pip install playwright pytest pytest-playwright pytest-base-url` and `playwright install chromium` (once).

- **config/models.yaml**
  - Added `code_reviewer`, `qa` → claude-sonnet-4-6.

- **requirements.txt**
  - Added: fastapi, uvicorn[standard], playwright, pytest, pytest-playwright, pytest-base-url.

- **Makefile**
  - `run-webhook`: run FastAPI app (PORT=8000).
  - `run-qa`: PROJECT_ID=uuid PREVIEW_URL=https://... (async run_qa).
  - `install-playwright`: playwright install chromium.

**GitHub webhook setup:** In repo or org Settings → Webhooks → Add webhook: Payload URL = `https://<your-forge-host>/webhooks/github`, Content type = application/json, Secret = GITHUB_WEBHOOK_SECRET, events = Just the push event.

---

## 2026-03-12 (Phase 3 Step 3 — Claude Code build subagents)

**Prompt:** Implement Step 3: Install Claude Code and define the build subagents. Python orchestrator calls `claude` CLI programmatically; CLAUDE.md files for Frontend Dev, Backend Dev, Code Reviewer, QA.

**Changes:**

- **agents/build_orchestrator.py** (new)
  - `fetch_briefing(judged_idea_id)`: loads latest CEO brief from `planning_artifacts` (artifact_type=ceo_brief).
  - `run_build_pipeline(project_id)`: loads project and briefing; if `project.github_repo` already set (e.g. from phase3_build), pushes scaffold to that repo via `push_scaffold_to_repo`; else calls `create_product_repo` and updates project. Clones repo to `/tmp/forge-builds/{product_name}`, runs `claude --dangerously-skip-permissions --model claude-sonnet-4-6 -p "..."` in that directory. Returns subprocess result.

- **utils/github_client.py**
  - `_push_scaffold(clone_url, briefing, token)`: init repo in temp dir, add ARCHITECT_SPEC.md, DESIGNER_SPEC.md, CLAUDE.md from briefing, push to origin main.
  - `create_product_repo(product_name, briefing)`: creates repo via `create_repo`, then `_push_scaffold` to push initial scaffold. Returns clone URL.
  - `push_scaffold_to_repo(repo_ref, briefing)`: pushes scaffold to an existing repo (repo_ref can be URL or owner/repo). Used when phase3_build already created the GitHub repo.

- **utils/build_specs.py** (new)
  - `format_arch_spec(technical_plan)`, `format_design_spec(design_direction)`, `get_parent_claude_md()`: format briefing content for repo scaffold and parent CLAUDE.md.

- **claude_agents/** (new)
  - `CLAUDE.md`: parent orchestrator (same content as get_parent_claude_md()).
  - `frontend_dev/CLAUDE.md`, `backend_dev/CLAUDE.md`, `code_reviewer/CLAUDE.md`, `qa_agent/CLAUDE.md`: subagent definitions with name, model, tools, RULES (stop on ambiguity, commit format, no hardcoded secrets).

- **Makefile**
  - `run-claude-build`: `make run-claude-build PROJECT_ID=uuid` runs the Claude Code build pipeline.

---

## 2026-03-12 (Phase 3 build pipeline)

**Prompt:** Complete Phase 3 requirements: user has `projects` table in Supabase and GitHub/Vercel/Railway configured as personal. Implement build pipeline so APPROVE triggers GitHub repo + Vercel + Railway and updates `projects`.

**Changes:**

- **utils/env.py**
  - Added optional env vars: `GITHUB_BOT_TOKEN`, `VERCEL_TOKEN`, `VERCEL_TEAM_ID`, `RAILWAY_TOKEN`, `CREDENTIAL_ENCRYPTION_KEY` (all `required=False`).

- **utils/github_client.py** (new)
  - `create_repo(repo_name, description="", private=False)` using PyGithub and `GITHUB_BOT_TOKEN`. Slugifies repo name. Returns `full_name`, `html_url`, `clone_url`.

- **utils/vercel_client.py** (new)
  - `create_project(project_name, repo_full_name, framework="nextjs")` via Vercel REST API; links GitHub repo. Uses `VERCEL_TOKEN`; optional `VERCEL_TEAM_ID`. Returns `id`, `name`, `link`.

- **utils/railway_client.py** (new)
  - `create_project(project_name)` via Railway GraphQL; uses `RAILWAY_TOKEN`. Returns `id`, `name`, `dashboard_url`. Does not link GitHub via API (manual or CLI).

- **scripts/phase3_build.py** (new)
  - `run_build_for_project(project_id)`: loads project from `projects` (needs `product_name`, `judged_idea_id`); creates GitHub repo → Vercel project (linked to repo) → Railway project; updates `projects` with `github_repo`, `vercel_url`, `railway_url`, `status='building'`. On exception: partial update, `status='build_failed'`, returns `{ok: False, error: "..."}`.
  - `run_build_for_idea(idea_id)`: finds latest project by `judged_idea_id`, then calls `run_build_for_project`.

- **scripts/check_plan_requests.py**
  - `_create_project_if_approved`: inserts into `projects` with `product_name` (from email/title or `Product-{idea_id}`), `judged_idea_id`, `status='approved'`. After insert, calls `run_build_for_project(project_id)` so APPROVE email triggers Phase 3 build when tokens are set. Build errors are caught and logged; project creation is not reverted.

- **Makefile**
  - Added `run-phase3-build` target: `make run-phase3-build PROJECT_ID=uuid` or `make run-phase3-build IDEA_ID=uuid` to run Phase 3 build manually.

- **requirements.txt** (new)
  - Core (Phase 1), Phase 2 (notion-client), Phase 3 (PyGithub, cryptography) dependencies for `pip install -r requirements.txt`.

---

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
