from __future__ import annotations

import os
from dataclasses import dataclass

from crewai import Agent, Crew, LLM, Process, Task
from dotenv import load_dotenv

from balagh.database import get_report
from balagh.tools import FindSimilarReportsTool, GetCaseHistoryTool, GetCaseTool


load_dotenv()


@dataclass(frozen=True)
class AgentRecommendation:
    triage_review: str
    coordinator_review: str
    final_recommendation: str


def _llm() -> LLM:
    return LLM(
        model=os.getenv("MODEL", "ollama/qwen3:4b-instruct"),
        base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        temperature=0.2,
    )


def _task_text(task: Task) -> str:
    output = getattr(task, "output", None)
    if output is None:
        return ""
    raw = getattr(output, "raw", None)
    return str(raw if raw is not None else output).strip()


def generate_recommendation(
    report_id: int,
    language: str = "Arabic",
) -> AgentRecommendation:
    """Run the two read-only advisory agents for a stored report."""
    if get_report(report_id) is None:
        raise ValueError(f"Report #{report_id} does not exist.")

    llm = _llm()

    triage_agent = Agent(
        role="Triage & Routing Agent",
        goal=(
            "Audit the deterministic triage using stored case evidence and similar reports, "
            "then recommend whether the classification, priority, and routing need human attention."
        ),
        backstory=(
            "You are an internal public-service triage analyst. BALAGH's deterministic engine "
            "already made the initial safety-sensitive decisions. You audit those decisions; "
            "you do not overwrite case state and you never invent field observations."
        ),
        tools=[GetCaseTool(), FindSimilarReportsTool()],
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )

    coordinator_agent = Agent(
        role="Case Coordinator Agent",
        goal=(
            "Recommend the next controlled case-management action by using the stored case facts, "
            "the triage audit, and the auditable case history."
        ),
        backstory=(
            "You coordinate public-service cases for human employees. Your output is advisory only. "
            "You cannot change a status, approve a case, or write to the case record."
        ),
        tools=[GetCaseTool(), GetCaseHistoryTool()],
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )

    triage_task = Task(
        description=f"""
Use your tools to review BALAGH report #{report_id}.

The deterministic triage remains the authoritative initial safety layer.
Return exactly these sections:
1. Classification assessment
2. Priority assessment
3. Routing assessment
4. Similar/duplicate report assessment
5. Missing-information assessment
6. Human confirmation items

Rules:
- Do not change emergency guidance.
- Do not invent locations, incidents, field findings, deadlines, or staff names.
- State uncertainty explicitly.
- Write in {language}.
""",
        expected_output=(
            "A concise evidence-based triage and routing audit that clearly separates "
            "confirmed case facts from items needing human confirmation."
        ),
        agent=triage_agent,
    )

    coordinator_task = Task(
        description=f"""
Review BALAGH report #{report_id} using your read-only case and history tools.
Use the Triage & Routing Agent output as context.

Return exactly these sections:
1. Recommended next action
2. Information to request from the reporter, if any
3. Escalation condition
4. Suggested citizen status update
5. Human approval checklist

Rules:
- This is a recommendation, not an executed decision.
- Do not change case status.
- Do not promise a resolution date.
- Do not invent facts.
- Write in {language}.
""",
        expected_output=(
            "A practical case-coordination recommendation explicitly marked as requiring human approval."
        ),
        agent=coordinator_agent,
        context=[triage_task],
    )

    crew = Crew(
        agents=[triage_agent, coordinator_agent],
        tasks=[triage_task, coordinator_task],
        process=Process.sequential,
        memory=False,
        verbose=False,
    )
    crew.kickoff()

    triage_review = _task_text(triage_task)
    coordinator_review = _task_text(coordinator_task)
    final_recommendation = (
        "AI RECOMMENDATION — HUMAN APPROVAL REQUIRED\n\n" + coordinator_review
    )

    return AgentRecommendation(
        triage_review=triage_review,
        coordinator_review=coordinator_review,
        final_recommendation=final_recommendation,
    )
