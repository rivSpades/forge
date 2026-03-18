# Makefile for running Forge pipeline agents

CONDA_ENV ?= forge
PY := conda run -n $(CONDA_ENV) python

.PHONY: help run-scout run-analyst run-reviewer run-judge run-digest run-all

help:
	@echo "Usage: make <target>"
	@echo "Targets:"
	@echo "  run-scout     - run the Scout agent (populate raw_ideas)"
	@echo "  run-analyst   - run the Analyst agent (populate analyzed_ideas)"
	@echo "  run-reviewer  - run the Reviewer agent (validate analyzed ideas)"
	@echo "  run-judge     - run the Judge agent (produce judged_ideas)"
	@echo "  run-digest    - send the daily digest email"
	@echo "  run-planner   - run Phase 2 planning pipeline for all judged_ideas with plan_requested = true"
	@echo "  approve        - approve idea from terminal: create project + Phase 3 infra (IDEA_ID=uuid [PRODUCT_NAME=...])"
	@echo "  run-phase3-build - run Phase 3 infra (GitHub + Vercel + Railway) for PROJECT_ID=uuid or IDEA_ID=uuid"
	@echo "  run-claude-build - run Phase 3 Step 3: Claude Code build (scaffold + claude CLI) for PROJECT_ID=uuid"
	@echo "  run-webhook   - run FastAPI webhook server (GitHub Code Reviewer); set PORT=8000"
	@echo "  run-qa       - run QA agent (Playwright + Lighthouse) for PROJECT_ID=uuid PREVIEW_URL=..."
	@echo "  install-playwright - install Chromium for QA agent (run once)"
	@echo "  run-all       - run scout->analyst->reviewer->judge->digest in sequence"

run-scout:
	$(PY) -c "from agents.scout import run_scout; run_scout()"

run-analyst:
	$(PY) -c "from agents.analyst import run_analyst; run_analyst()"

run-reviewer:
	$(PY) -c "from agents.reviewer import run_reviewer; run_reviewer()"

run-judge:
	$(PY) -c "from agents.judge import run_judge; run_judge()"

run-architect:
	$(PY) -c "from agents.architect import run_architect; run_architect()"

run-arch-reviewer:
	$(PY) -c "from agents.arch_reviewer import run_arch_reviewer; run_arch_reviewer()"

run-designer:
	$(PY) -c "from agents.designer import run_designer; run_designer()"

run-design-reviewer:
	$(PY) -c "from agents.design_reviewer import run_design_reviewer; run_design_reviewer()"

run-marketing:
	$(PY) -c "from agents.marketing_strategist import run_marketing_strategist; run_marketing_strategist()"

run-marketing-reviewer:
	$(PY) -c "from agents.marketing_reviewer import run_marketing_reviewer; run_marketing_reviewer()"

IDEA_ID ?=
run-project-manager:
	$(PY) -c "import asyncio, os; from agents.project_manager import run_project_manager_pipeline, get_idea_id_with_plans; idea_id = get_idea_id_with_plans(os.environ.get('IDEA_ID') or '$(IDEA_ID)' or None); (print('[pm] No judged_idea with architect+designer+marketing artifacts. Set IDEA_ID=uuid or run planner first.'), __import__('sys').exit(1)) if not idea_id else asyncio.run(run_project_manager_pipeline(idea_id))"

run-plan-reviewer:
	$(PY) -c "from agents.plan_reviewer import run_plan_reviewer; run_plan_reviewer()"

run-planner:
	$(PY) -c "import asyncio; from utils.supabase_client import supabase; from agents.planner import run_planning_pipeline; pending = supabase.table('judged_ideas').select('id').eq('plan_requested', True).execute().data or []; [asyncio.run(run_planning_pipeline(row['id'])) for row in pending]"

IDEA_ID ?=
PRODUCT_NAME ?=
approve:
	$(PY) -m scripts.approve_idea '$(IDEA_ID)' '$(PRODUCT_NAME)'

PROJECT_ID ?=
IDEA_ID ?=
run-phase3-build:
	$(PY) -c "from scripts.phase3_build import run_build_for_project, run_build_for_idea; pid, iid = '$(PROJECT_ID)'.strip(), '$(IDEA_ID)'.strip(); out = run_build_for_project(pid) if pid else run_build_for_idea(iid) if iid else {'ok': False, 'error': 'Set PROJECT_ID=uuid or IDEA_ID=uuid'}; print(out); __import__('sys').exit(0 if out.get('ok') else 1)"

run-claude-build:
	$(PY) -c "pid = '$(PROJECT_ID)'.strip(); (print('Set PROJECT_ID=uuid'), __import__('sys').exit(1)) if not pid else None; from agents.build_orchestrator import run_build_pipeline; r = run_build_pipeline(pid); print(r.stdout or ''); print(r.stderr or ''); __import__('sys').exit(r.returncode)"

PORT ?= 8000
run-webhook:
	$(PY) -m uvicorn api.main:app --host 0.0.0.0 --port $(PORT)

PROJECT_ID ?=
PREVIEW_URL ?=
run-qa:
	$(PY) -c "import asyncio, os, sys; from agents.qa_agent import run_qa; pid = (os.environ.get('PROJECT_ID') or '$(PROJECT_ID)').strip(); url = (os.environ.get('PREVIEW_URL') or '$(PREVIEW_URL)').strip(); (print('Set PROJECT_ID=uuid and PREVIEW_URL=https://...'), sys.exit(1)) if not pid or not url else None; r = asyncio.run(run_qa(pid, url)); print(r); sys.exit(0 if r.get('ok') else 1)"

install-playwright:
	$(PY) -m playwright install chromium

run-digest:
	$(PY) -c "from agents.digest import send_digest; send_digest()"

run-all: run-scout run-analyst run-reviewer run-judge run-digest
