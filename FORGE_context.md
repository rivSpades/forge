# FORGE — Developer Agent Context

> Autonomous Idea-to-Product Engine  
> Blueprint version: 4.0 (March 2026)  
> Stack: Claude Agent SDK · Sonnet 4.6 / Opus 4.6 · Structured Outputs · Adaptive Thinking · Auto-Caching

---

## PURPOSE

FORGE is an autonomous multi-agent pipeline that:
1. Discovers product ideas from target forums daily (Scout)
2. Researches and scores them without human input (Analyst → Reviewer → Judge)
3. Sends a daily digest to the CEO — only GO ideas above a score threshold
4. On CEO interest, generates a full technical + design + marketing plan (parallel planning team)
5. On CEO approval, builds and deploys the product using Claude Code subagents
6. Manages live products post-launch (support, uptime, growth, revenue, analytics)
7. Learns from CEO decisions monthly and calibrates its own scoring rubric

**CEO touches the system only at three gates:**
- Gate 1: marks ideas "interested" in the daily digest email
- Gate 2: approves or rejects the full product brief
- Gate 3: approves the QA launch readiness report

---

## TECH STACK

| Layer | Tool | Notes |
|---|---|---|
| LLM | `anthropic` Python SDK | `pip install anthropic` — no CrewAI, no LangGraph |
| Standard agents | `claude-sonnet-4-6` | Analyst, Designer, Marketing Strategist, Reviewers |
| High-reasoning agents | `claude-opus-4-6` | Judge, Architect, Project Manager |
| Parallel execution | `AsyncAnthropic` + `asyncio.gather()` | Planning team runs in parallel natively |
| Build agents | Claude Code subagents | Defined in `CLAUDE.md` files per agent |
| Agent reasoning | `thinking: {type: "adaptive"}` + `effort="high"/"low"` | Replaces deprecated `budget_tokens` |
| Structured outputs | `output_config.format` JSON schema | Guaranteed schema on all agent responses — no regex |
| Prompt caching | `"cache_control": {"type": "ephemeral"}` | One field on system prompt — automatic, 60-75% cost reduction |
| Web search | `{"type": "web_search_20250305", "name": "web_search"}` | GA — no beta header needed |
| Multi-API calls | Programmatic tool calling + `code_execution_20250522` | Code execution free when used with web search |
| Long sessions | Compaction API (Opus 4.6) | PM synthesis of large multi-plan inputs |
| Scraping | Firecrawl SDK + Reddit `.json` API | JS-rendered forums via Firecrawl, Reddit direct |
| Database | Supabase (PostgreSQL + pgvector + auth) | All pipeline data, credentials, project registry |
| Frontend | Next.js + Tailwind → Vercel | Every product frontend |
| Backend | Python FastAPI → Railway | Every product API |
| Payments | Stripe or Lemon Squeezy | Lemon Squeezy handles global VAT automatically |
| Email | Resend | CEO digests + transactional product email |
| Analytics | PostHog | Funnels, feature usage, A/B tests |
| Social | Buffer API | Marketing Execution Agent schedules all posts |
| Scheduling | APScheduler (dev) / Railway cron (prod) | All agent run times |
| Error monitoring | Sentry | Auto-captures exceptions with context |
| Uptime | Uptime Robot (free, 50 monitors) | 5-minute ping per live product |

**Deprecated / removed vs v3:**
- ❌ CrewAI — replaced by native SDK
- ❌ LangGraph — replaced by `asyncio.gather()`
- ❌ `budget_tokens` — replaced by `effort` parameter
- ❌ `claude-sonnet-4-5`, `claude-opus-4-5`, `claude-haiku-3-5` — use 4.6 generation
- ❌ `claude-3-opus-20240229`, `claude-3-7-sonnet-20250219`, `claude-3-5-haiku-20241022` — all retired, return errors

---

## API PATTERNS

### Standard agent call with auto-caching
```python
import anthropic, json

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    system=[
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"}  # one field = automatic caching
        }
    ],
    messages=[{"role": "user", "content": user_input}]
)
```

### Structured output (guaranteed JSON schema)
```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
    messages=[{"role": "user", "content": user_input}],
    output_config={
        "format": {
            "type": "json_schema",
            "json_schema": YOUR_SCHEMA  # response guaranteed to match
        }
    }
)
result = json.loads(response.content[0].text)
```

### High-reasoning agent (Judge, Architect, PM)
```python
response = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=8000,
    thinking={"type": "adaptive"},   # adaptive replaces budget_tokens on Opus 4.6
    effort="high",                   # "low" | "medium" | "high"
    system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
    messages=[{"role": "user", "content": user_input}],
    output_config={"format": {"type": "json_schema", "json_schema": SCHEMA}}
)
# Filter to text blocks only (adaptive thinking produces thinking blocks too)
result_text = next(b.text for b in response.content if b.type == "text")
result = json.loads(result_text)
```

### Web search enabled (Analyst, Architect, Marketing Strategist)
```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    tools=[{"type": "web_search_20250305", "name": "web_search"}],
    # Dynamic filtering: code execution filters results before they reach context window
    system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
    messages=[{"role": "user", "content": user_input}],
    output_config={"format": {"type": "json_schema", "json_schema": SCHEMA}}
)
result_text = next(b.text for b in response.content if b.type == "text")
```

### Parallel async execution (Planning team)
```python
import asyncio
from anthropic import AsyncAnthropic

async def run_planning_pipeline(idea):
    arch_task  = asyncio.create_task(run_architect(idea))
    design_task = asyncio.create_task(run_designer(idea))
    mktg_task  = asyncio.create_task(run_marketing_strategist(idea))

    arch_plan, design_plan, mktg_plan = await asyncio.wait_for(
        asyncio.gather(arch_task, design_task, mktg_task),
        timeout=14400  # 4 hours
    )
    briefing = await run_project_manager(idea, arch_plan, design_plan, mktg_plan)
    return briefing
```

### Programmatic tool calling (Analytics Agent)
```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=8000,
    tools=[
        {"type": "web_search_20250305", "name": "web_search"},
        {"type": "code_execution_20250522", "name": "code_execution"}  # free with web search
    ],
    system=[{"type": "text", "text": ANALYTICS_PROMPT, "cache_control": {"type": "ephemeral"}}],
    messages=[{"role": "user", "content": f"Fetch all product data and compile weekly report. APIs: {api_keys}"}],
    output_config={"format": {"type": "json_schema", "json_schema": REPORT_SCHEMA}}
)
# Claude writes a Python function, executes it, returns structured results
```

---

## CENTRAL CLIENT PATTERN

All agents import from `utils/claude_client.py`. Never instantiate the client in agent files directly.

```python
# utils/claude_client.py
import anthropic, yaml, json
from utils.env import settings

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

with open("config/models.yaml") as f:
    MODELS = yaml.safe_load(f)

def call_agent(agent_name: str, system_prompt: str, user_message: str,
               schema: dict = None, effort: str = None,
               web_search: bool = False) -> dict:
    model = MODELS.get(agent_name, "claude-sonnet-4-6")
    params = {
        "model": model,
        "max_tokens": 4096,
        "system": [{"type": "text", "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user_message}]
    }
    if schema:
        params["output_config"] = {"format": {"type": "json_schema", "json_schema": schema}}
    if effort:
        params["thinking"] = {"type": "adaptive"}
        params["effort"]   = effort
    if web_search:
        params["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]
    response = client.messages.create(**params)
    return response
```

```yaml
# config/models.yaml
scout:     claude-sonnet-4-6
analyst:   claude-sonnet-4-6
reviewer:  claude-sonnet-4-6
judge:     claude-opus-4-6
architect: claude-opus-4-6
designer:  claude-sonnet-4-6
marketing: claude-sonnet-4-6
pm:        claude-opus-4-6
digest:    claude-sonnet-4-6
analytics: claude-sonnet-4-6
```

---

## ENVIRONMENT VARIABLES

```
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_KEY=eyJ...           # backend agents only, never expose in frontend

# Firecrawl
FIRECRAWL_API_KEY=fc-...

# Resend
RESEND_API_KEY=re_...

# Notion (Phase 2+)
NOTION_API_TOKEN=secret_...
NOTION_DATABASE_ID=...

# GitHub bot (Phase 3+)
GITHUB_BOT_TOKEN=ghp_...

# Vercel (Phase 3+)
VERCEL_TOKEN=...
VERCEL_TEAM_ID=...

# Railway (Phase 3+)
RAILWAY_TOKEN=...

# Buffer (Phase 4+)
BUFFER_ACCESS_TOKEN=...

# Credential encryption (Phase 3+)
CREDENTIAL_ENCRYPTION_KEY=...         # Fernet key

# CEO email
CEO_EMAIL=...
PLAN_EMAIL=plans@yourdomain.com       # for CEO reply parsing
PLAN_EMAIL_PASSWORD=...
```

---

## DATABASE SCHEMA

### Phase 1 — Idea Pipeline

```sql
-- Raw ideas from Scout
CREATE TABLE raw_ideas (
  id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  source_url  TEXT UNIQUE NOT NULL,
  post_title  TEXT,
  body_text   TEXT,
  upvotes     INTEGER DEFAULT 0,
  comments    INTEGER DEFAULT 0,
  forum_name  TEXT,
  category    TEXT,
  scraped_at  TIMESTAMP DEFAULT NOW(),
  processed   BOOLEAN DEFAULT FALSE
);

-- Analyst structured reports
CREATE TABLE analyzed_ideas (
  id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  raw_idea_id     UUID REFERENCES raw_ideas(id),
  report          JSONB NOT NULL,       -- full structured Analyst output
  reviewer_pass   BOOLEAN DEFAULT FALSE, -- NULL = escalated
  reviewer_notes  TEXT,
  revision_count  INTEGER DEFAULT 0,
  created_at      TIMESTAMP DEFAULT NOW()
);

-- Judge verdicts and scores
CREATE TABLE judged_ideas (
  id                    UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  analyzed_idea_id      UUID REFERENCES analyzed_ideas(id),
  market_demand         FLOAT,
  competition_moat      FLOAT,
  build_complexity      FLOAT,
  time_to_revenue       FLOAT,
  capital_required      FLOAT,
  weighted_total        FLOAT,
  verdict               TEXT,           -- 'GO' | 'NO-GO'
  confidence            TEXT,           -- 'HIGH' | 'MEDIUM' | 'LOW'
  reasoning             TEXT,
  plan_requested        BOOLEAN DEFAULT FALSE,
  plan_requested_at     TIMESTAMP,
  judged_at             TIMESTAMP DEFAULT NOW()
);

-- CEO decisions (used by Learning Loop in Phase 5)
CREATE TABLE ceo_decisions (
  id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  judged_idea_id  UUID REFERENCES judged_ideas(id),
  decision        TEXT,                 -- 'interested' | 'pass' | 'archive'
  notes           TEXT,
  decided_at      TIMESTAMP DEFAULT NOW()
);
```

### Phase 2+ — Projects

```sql
CREATE TABLE projects (
  id                    UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  product_name          TEXT NOT NULL,
  judged_idea_id        UUID REFERENCES judged_ideas(id),
  github_repo           TEXT,
  vercel_url            TEXT,
  railway_url           TEXT,
  status                TEXT DEFAULT 'planning',  -- see lifecycle states below
  activation_event      TEXT,
  activation_event_description TEXT,
  launched_at           TIMESTAMP,
  created_at            TIMESTAMP DEFAULT NOW()
);

-- Encrypted product credentials
CREATE TABLE project_credentials (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  project_id       UUID REFERENCES projects(id),
  credential_name  TEXT NOT NULL,
  encrypted_value  TEXT NOT NULL,         -- Fernet encrypted
  created_at       TIMESTAMP DEFAULT NOW()
);
ALTER TABLE project_credentials ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_only" ON project_credentials USING (auth.role() = 'service_role');

-- Social channels per product
CREATE TABLE social_channels (
  id                UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  project_id        UUID REFERENCES projects(id),
  platform          TEXT,               -- 'twitter' | 'instagram' | 'linkedin'
  buffer_channel_id TEXT,
  handle            TEXT
);

-- Content calendar
CREATE TABLE content_calendar (
  id             UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  project_id     UUID REFERENCES projects(id),
  platform       TEXT,
  scheduled_date DATE,
  post_type      TEXT,                  -- 'educational' | 'engagement' | 'promo' | 'blog'
  content_brief  TEXT,
  content        TEXT,
  buffer_post_id TEXT,
  status         TEXT DEFAULT 'planned' -- 'planned' | 'generated' | 'scheduled' | 'published'
);
```

---

## AGENT ROSTER

### Phase 1 — Idea Pipeline

| Agent | Model | Tools | Effort | Schedule |
|---|---|---|---|---|
| Scout | sonnet-4-6 | Firecrawl SDK | default | 7am daily |
| Analyst | sonnet-4-6 | web_search (GA) | default | 9am daily |
| Analysis Reviewer | sonnet-4-6 | — | low | 11am daily |
| Judge | opus-4-6 | web_search | high + adaptive | 1pm daily |
| Digest | sonnet-4-6 | — | default | 3pm daily |

**Reviewer loop pattern (all phases):**  
Reviewer issues `PASS` / `REVISE` / `ESCALATE`. On `REVISE`, writes notes to the agent. Max 2 revision loops. On `ESCALATE`, surfaces to CEO in digest under "Flagged for Manual Review" — does not block pipeline.

### Phase 2 — Planning Team (runs in parallel)

| Agent | Model | Tools | Effort |
|---|---|---|---|
| Architect | opus-4-6 | web_search | high + adaptive |
| Architecture Reviewer | sonnet-4-6 | — | low |
| Designer | sonnet-4-6 | web_search | default |
| Design Reviewer | sonnet-4-6 | — | low |
| Marketing Strategist | sonnet-4-6 | web_search | default |
| Marketing Reviewer | sonnet-4-6 | — | low |
| Project Manager | opus-4-6 | — (Compaction API) | high + adaptive |
| Plan Reviewer | sonnet-4-6 | — | low |

### Phase 3 — Build (Claude Code subagents)

| Agent | Model | Tools | CLAUDE.md location |
|---|---|---|---|
| Frontend Dev | sonnet-4-6 | computer, bash, read/write file, web_fetch | `claude_agents/frontend_dev/CLAUDE.md` |
| Backend Dev | sonnet-4-6 | computer, bash, read/write file, web_fetch | `claude_agents/backend_dev/CLAUDE.md` |
| Code Reviewer | sonnet-4-6 | read_file | `claude_agents/code_reviewer/CLAUDE.md` |
| QA Agent | sonnet-4-6 | bash, read/write file | `claude_agents/qa_agent/CLAUDE.md` |

**Rule in every CLAUDE.md:** If anything in the spec is ambiguous, write the question to `QUESTIONS.md` and stop. Never guess. Never improvise.

### Phase 4 — Marketing & Analytics

| Agent | Model | Tools | Schedule |
|---|---|---|---|
| Marketing Execution | sonnet-4-6 | web_search, Buffer API | Daily content generation |
| Analytics & Reporting | sonnet-4-6 | web_search + code_execution (programmatic) | Sunday 8am |

### Phase 5 — Autonomy Loop

| Agent | Model | Tools | Schedule |
|---|---|---|---|
| Learning Loop | opus-4-6 | — | 1st of month, 6am |

### Post-Launch (ongoing from Phase 3)

| Agent | Role | Schedule |
|---|---|---|
| Customer Support | First-line ticket response, bug escalation | On new ticket |
| Product Health | Uptime, SSL, webhook monitoring | Every 5 minutes |
| Growth | Activation funnel, A/B tests, reactivation emails | Daily |
| Revenue | Dunning sequences, MRR tracking, upgrade flagging | Daily |
| Portfolio Manager | Cross-product registry, total MRR, net profit | Daily |

---

## KEY CONFIG FILES

### `config/forums.yaml`
```yaml
forums:
  - name: IndieHackers
    url: https://www.indiehackers.com/posts
    type: thread_list        # use Firecrawl
    active: true
    min_upvotes: 10
    keywords: ["how I", "case study", "$ per month", "MRR", "built and launched"]

  - name: Reddit-SideProject
    url: https://www.reddit.com/r/SideProject/top.json?t=day
    type: reddit_json        # fetch .json directly, no Firecrawl needed
    active: true
    min_upvotes: 20
    keywords: ["launched", "making money", "first revenue", "built"]

  - name: HackerNews
    url: https://news.ycombinator.com/show
    type: thread_list
    active: true
    min_upvotes: 5
    keywords: ["Show HN", "I built", "tool for"]
```

### `config/judge_rubric.yaml`
```yaml
dimensions:
  market_demand:
    weight: 0.25
    # scores 2/4/6/8/10 with specific observable descriptions

  competition_moat:
    weight: 0.20

  build_complexity:
    weight: 0.20   # lower complexity = higher score (inverted)

  time_to_revenue:
    weight: 0.20

  capital_required:
    weight: 0.15

go_threshold: 6.5
high_confidence_threshold: 7.5
```

### `config/reviewer_checklist.yaml`
```yaml
checks:
  - id: competitors_real
    description: "All named competitors have a URL present"
  - id: market_size_sourced
    description: "market_size_source is non-empty"
  - id: risks_specific
    description: "All risks are named concerns, not generic"
  - id: no_insufficient_data
    description: "No INSUFFICIENT_DATA in any field"
    escalate_if_true: true

thresholds:
  min_checks_to_pass: 5
  max_revisions: 2
```

---

## STRUCTURED OUTPUT SCHEMAS

### Scout categorization
```python
SCOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "category":      {"type": "string"},
        "quality_score": {"type": "integer", "minimum": 1, "maximum": 5},
        "keep":          {"type": "boolean"}
    },
    "required": ["category", "quality_score", "keep"]
}
# threshold: quality_score >= 3 AND keep == True
```

### Analyst report
```python
ANALYST_SCHEMA = {
    "type": "object",
    "properties": {
        "market_size_estimate": {"type": "string"},
        "market_size_source":   {"type": "string"},
        "competitors": {
            "type": "array", "minItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "name":     {"type": "string"},
                    "url":      {"type": "string"},
                    "pricing":  {"type": "string"},
                    "weakness": {"type": "string"}
                },
                "required": ["name", "url", "pricing", "weakness"]
            }
        },
        "monetization_model":  {"type": "string"},
        "effort_score":        {"type": "integer", "minimum": 1, "maximum": 10},
        "revenue_score":       {"type": "integer", "minimum": 1, "maximum": 10},
        "risks":               {"type": "array", "minItems": 3, "items": {"type": "string"}},
        "assessment":          {"type": "string"}
    },
    "required": ["market_size_estimate", "market_size_source", "competitors",
                 "monetization_model", "effort_score", "revenue_score", "risks", "assessment"]
}
```

### Reviewer verdict
```python
REVIEWER_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict":        {"type": "string", "enum": ["PASS", "REVISE", "ESCALATE"]},
        "failed_checks":  {"type": "array", "items": {"type": "string"}},
        "revision_notes": {"type": "string"}
    },
    "required": ["verdict", "failed_checks", "revision_notes"]
}
```

### Judge verdict
```python
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "market_demand":    {"type": "number", "minimum": 1, "maximum": 10},
        "competition_moat": {"type": "number", "minimum": 1, "maximum": 10},
        "build_complexity": {"type": "number", "minimum": 1, "maximum": 10},
        "time_to_revenue":  {"type": "number", "minimum": 1, "maximum": 10},
        "capital_required": {"type": "number", "minimum": 1, "maximum": 10},
        "weighted_total":   {"type": "number"},
        "verdict":          {"type": "string", "enum": ["GO", "NO-GO"]},
        "confidence":       {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
        "reasoning":        {"type": "string"}
    },
    "required": ["market_demand", "competition_moat", "build_complexity",
                 "time_to_revenue", "capital_required", "weighted_total",
                 "verdict", "confidence", "reasoning"]
}
```

### Architect plan
```python
ARCHITECT_SCHEMA = {
    "type": "object",
    "properties": {
        "stack": {
            "type": "object",
            "properties": {
                "frontend": {"type": "string"}, "backend": {"type": "string"},
                "database": {"type": "string"}, "auth":    {"type": "string"},
                "hosting":  {"type": "string"}, "payments":{"type": "string"}
            }
        },
        "stack_rationale": {"type": "string"},
        "components": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"name": {"type": "string"}, "responsibility": {"type": "string"}},
                      "required": ["name", "responsibility"]}
        },
        "features": {
            "type": "object",
            "properties": {
                "mvp":   {"type": "array", "items": {"type": "string"}},
                "v1":    {"type": "array", "items": {"type": "string"}},
                "later": {"type": "array", "items": {"type": "string"}}
            }
        },
        "third_party_apis": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"name": {"type": "string"}, "purpose": {"type": "string"},
                                     "monthly_cost": {"type": "string"}},
                      "required": ["name", "purpose", "monthly_cost"]}
        },
        "database_schema":       {"type": "string"},
        "folder_structure":      {"type": "string"},
        "security_design":       {"type": "string"},
        "effort_estimate_weeks": {"type": "number"}
    },
    "required": ["stack", "stack_rationale", "components", "features",
                 "third_party_apis", "database_schema", "folder_structure",
                 "security_design", "effort_estimate_weeks"]
}
```

---

## SCHEDULER SETUP

```python
# scheduler.py
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

scheduler = BlockingScheduler(timezone="UTC")

# Phase 1 — daily pipeline (all times UTC)
scheduler.add_job(run_scout,             CronTrigger(hour=7))
scheduler.add_job(run_analyst,           CronTrigger(hour=9))
scheduler.add_job(run_reviewer,          CronTrigger(hour=11))
scheduler.add_job(run_judge,             CronTrigger(hour=13))
scheduler.add_job(send_digest,           CronTrigger(hour=15))

# Phase 2+ — hourly plan/decision polling
scheduler.add_job(check_plan_requests,   CronTrigger(minute=0))

# Phase 4 — weekly report
scheduler.add_job(run_analytics_agent,   CronTrigger(day_of_week='sun', hour=8))

# Phase 5 — monthly calibration
scheduler.add_job(run_learning_loop,     CronTrigger(day=1, hour=6))

scheduler.start()
```

---

## CLAUDE CODE SUBAGENT STRUCTURE

```
forge/
  claude_agents/
    CLAUDE.md                    # Parent orchestrator
    frontend_dev/CLAUDE.md
    backend_dev/CLAUDE.md
    code_reviewer/CLAUDE.md
    qa_agent/CLAUDE.md
```

**Parent CLAUDE.md invocation:**
```bash
claude --dangerously-skip-permissions \
       --model claude-sonnet-4-6 \
       -p "Build this product according to ARCHITECT_SPEC.md and DESIGNER_SPEC.md. \
           Start with layout, then landing page, then auth, then core product. \
           Commit after each section. Stop and write to QUESTIONS.md if anything is ambiguous."
```

**Every subagent CLAUDE.md must include:**
```markdown
---
name: [Agent Name]
model: claude-sonnet-4-6
tools: [list of permitted tools]
thinking: adaptive
effort: medium
---

[System prompt]

RULES:
- If anything is ambiguous, write the question to QUESTIONS.md and STOP.
- Never guess. Never improvise outside the spec.
- Commit with format: "feat: [section] - [description]" after each section.
- Never hardcode API keys or secrets.
```

---

## PRODUCT LIFECYCLE STATES

| State | Meaning | Next action |
|---|---|---|
| `planning` | Brief approved, CEO completing action items | CEO finishes action items |
| `in_build` | Claude Code subagents building | Monitor QUESTIONS.md |
| `in_qa` | QA agent running tests | Review Launch Readiness Report |
| `active_growth` | Live, first 60 days | Monitor weekly metrics |
| `maintenance` | Stable revenue, autopilot | Build next product |
| `under_review` | 60-day gate — below threshold | CEO decides within 5 days |
| `scaling` | Hit thresholds, strong growth | CEO approves budget increase |
| `shut_down` | Wound down | All costs eliminated within 7 days |

### 60-Day Review Thresholds
- **Green:** MRR ≥ $500 OR 100+ active users with strong activation → move to `maintenance`
- **Yellow:** MRR $100–$500 OR users present but activation low → 30-day extension + one specific change
- **Red:** MRR < $100 AND activation < 20% → shut down or hard pivot (CEO decides within 5 days)

### Shut Down Protocol (7 days)
- Day 1: CEO confirms. System emails all users with 30-day notice + data export link.
- Days 1–3: Cancel all ad campaigns. Stop all scheduled social content.
- Days 3–5: Revenue Agent cancels Stripe subscriptions, issues pro-rata refunds.
- Days 5–7: Export DB to Supabase Storage. Stop Railway service. Pause Vercel.
- Day 7: Domain archived or listed for sale. Portfolio state → `shut_down`. Monthly cost → $0.

---

## METRICS FRAMEWORK

### Tier 1 — Company Level (weekly)
| Metric | Healthy | Action if unhealthy |
|---|---|---|
| Total Portfolio MRR | Growing MoM | Review shrinking products |
| Net Monthly Profit | Positive and growing | Audit costs |
| Products in Active Growth | 1–2 max | Too many → pause pipeline |
| Pipeline Velocity | Trending down | Find bottleneck phase |
| Ideas to Build Rate | 10–30% of GO ideas | Outside range → adjust Judge threshold |

### Tier 2 — Product Level: Acquisition
| Metric | Healthy range | Red flag |
|---|---|---|
| Visitor → Signup | 2–5% (B2B SaaS) | < 1% → landing page messaging broken |
| Signup → Paid | 3–8% freemium | Below range → pricing or value prop issue |
| CPA | < LTV/3 | CPA > LTV → unit economics broken |

### Tier 2 — Product Level: Activation
| Metric | Healthy | Red flag |
|---|---|---|
| Activation Rate | > 40% | < 20% → critical |
| Time to Activation | < 48 hours | > 48h → onboarding friction |
| Funnel step drop-off | < 40% per step | > 40% → Growth Agent alerts CEO |

### Tier 2 — Product Level: Retention & Revenue
| Metric | Healthy | Red flag |
|---|---|---|
| Monthly Churn | < 5% | > 10% → not delivering sustained value |
| MRR Growth Rate | > 10% (growth phase) | Negative → cancellations exceed new |
| Net Revenue Retention | > 100% | < 80% → churn outpacing upgrades |
| LTV | > 3x CPA | LTV < CPA → acquiring costs more than they pay |

### Tier 3 — Operational
| Metric | Healthy | Action |
|---|---|---|
| Analyst Revision Rate | < 20% | Rising → forums producing low-quality content |
| Judge GO Rate | 10–30% | Outside range → adjust Judge threshold |
| Brief to Approval Rate | > 50% | Below → planning agents missing expectations |
| Agent Error Rate | < 5% | Check logs, investigate |

### Weekly CEO Report Structure (every Sunday)
1. Portfolio Snapshot — Total MRR, net profit, product count by state
2. Product Scorecards — One row per live product with trend arrows
3. Active Growth Detail — Full metrics for products in first 60 days
4. Marketing Performance — Ad spend vs signups, best content, follower changes
5. Pipeline Summary — New GO ideas, briefs in progress, builds in progress, upcoming 60-day reviews
6. Alerts with Hypotheses — Any metric moving >20%, with Analytics Agent hypothesis
7. Decisions Needed — Explicit list with deadlines
8. Last Week Follow-up — Did last week's actions produce expected results?

---

## COST REFERENCE

| Phase | Component | Range |
|---|---|---|
| Phase 1 | Anthropic (Sonnet 4.6 + Opus 4.6) + Firecrawl + Supabase free + Resend free + VPS | $15–60/mo |
| Phase 2 | + Notion + Opus planning team | +$35–110/mo |
| Phase 3 | + Claude Code builds + Vercel Pro + Railway + Supabase Pro per product | +$110–250/mo |
| Phase 4 | + Buffer + PostHog + Analytics + DataForSEO | +$51–110/mo |
| Phase 5 | + Monthly Learning Loop (Opus, ~10 calls) | +$3–12/mo |
| Post-Launch | + Sentry + Uptime Robot + support infra | +$20–60/mo |
| **Full operation** | | **$244–632/mo** |

**Cost reduction vs v3 estimates:** ~50% lower due to automatic prompt caching (60-75% reduction on system prompts) and code execution being free when used with web search.

---

## CEO GATE ACTIONS

### Gate 1 — Daily Digest (Phase 1+)
- Reply "PLAN REQUEST — [idea_id]" → triggers Phase 2 planning pipeline
- No reply = no action

### Gate 2 — CEO Brief (Phase 2+)
- Reply "APPROVE — [idea_id]" → triggers Phase 3 build pipeline
- Reply "REJECT — [idea_id]" → archived, no action
- Reply "CHANGES — [idea_id]" → returns to planning team with your notes

### Gate 3 — Launch Readiness Report (Phase 3+)
- Click one-time signed URL in email → product goes live automatically
- All launch steps (Vercel promote, Railway production deploy, first social post) run in ~2 minutes

### Learning Loop Gate (Phase 5, monthly)
- Reply YES → calibration changes applied to judge_rubric.yaml and forums.yaml
- Reply NO → changes discarded, current config unchanged
- Reply MODIFY → changes applied with your specific notes as overrides

---

## DEPENDENCY INSTALL

```bash
# Core (Phase 1)
pip install anthropic supabase python-dotenv pyyaml apscheduler \
            requests firecrawl-py resend schedule

# Phase 2
pip install notion-client

# Phase 3
pip install PyGithub cryptography
npm install -g @anthropic-ai/claude-code

# Phase 4
pip install posthog stripe
npm install posthog-js  # in product frontend

# Phase 5
# No additional deps
```

---

## FOLDER STRUCTURE

```
forge/
  agents/
    scout.py
    analyst.py
    reviewer.py
    judge.py
    digest.py
    architect.py
    designer.py
    marketing_strategist.py
    project_manager.py
    build_orchestrator.py
    marketing_exec.py
    analytics_agent.py
    learning_loop.py
    support_agent.py
    health_agent.py
    growth_agent.py
    revenue_agent.py
    portfolio_manager.py
  claude_agents/
    CLAUDE.md
    frontend_dev/CLAUDE.md
    backend_dev/CLAUDE.md
    code_reviewer/CLAUDE.md
    qa_agent/CLAUDE.md
  config/
    models.yaml
    forums.yaml
    judge_rubric.yaml
    reviewer_checklist.yaml
    arch_reviewer_checklist.yaml
    design_reviewer_checklist.yaml
    marketing_reviewer_checklist.yaml
    plan_reviewer_checklist.yaml
    posthog_events.yaml
    calibration_log.yaml
  scripts/
    add_credential.py
    check_plan_requests.py
    run_learning_loop.py
    add_activation_event.py
  utils/
    claude_client.py
    async_claude.py
    supabase_client.py
    firecrawl_client.py
    notion_client.py
    github_client.py
    env.py
  logs/
    scheduler.log
  .env                  # never commit
  .gitignore            # .env, venv/, logs/, __pycache__/
  scheduler.py
  requirements.txt
```

---

*End of context document. All API patterns, schemas, and configurations reflect the GA Claude API as of March 2026.*
