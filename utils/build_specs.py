"""Phase 3: Format briefing content into ARCHITECT_SPEC.md and DESIGNER_SPEC.md for the repo scaffold."""


def format_arch_spec(technical_plan: str) -> str:
    """Turn technical_plan from the briefing into ARCHITECT_SPEC.md content."""
    if not (technical_plan or "").strip():
        return "# Architecture spec\n\n(No technical plan in briefing.)\n"
    return f"# Architecture spec\n\n{technical_plan.strip()}\n"


def format_design_spec(design_direction: str) -> str:
    """Turn design_direction from the briefing into DESIGNER_SPEC.md content."""
    if not (design_direction or "").strip():
        return "# Design spec\n\n(No design direction in briefing.)\n"
    return f"# Design spec\n\n{design_direction.strip()}\n"


def get_parent_claude_md() -> str:
    """Content for the repo-root CLAUDE.md that the Claude Code CLI reads."""
    return """---
name: FORGE Build
model: claude-sonnet-4-6
thinking: adaptive
effort: medium
---

You are the FORGE build orchestrator. Build this product according to ARCHITECT_SPEC.md and DESIGNER_SPEC.md.

RULES:
- If anything in the spec is ambiguous, write the question to QUESTIONS.md and STOP. Never guess. Never improvise.
- Commit after each section with format: "feat: [section] - [description]".
- Never hardcode API keys or secrets.
- Order: Start with layout, then landing page, then auth, then core product.
"""
