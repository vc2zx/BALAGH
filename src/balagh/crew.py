from __future__ import annotations

import os

from crewai import Agent, Crew, LLM, Process, Task
from dotenv import load_dotenv

from balagh.core import TriageResult


load_dotenv()


def _llm() -> LLM:
    return LLM(
        model=os.getenv("MODEL", "ollama/qwen3:4b-instruct"),
        base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        temperature=0.2,
    )


def generate_agent_review(
    report_id: int,
    report: TriageResult,
    language: str = "English",
) -> str:
    llm = _llm()

    triage_reviewer = Agent(
        role="Civic Triage Reviewer",
        goal=(
            "Audit the deterministic classification and priority without "
            "inventing facts or overriding emergency guidance."
        ),
        backstory=(
            "You review public-service reports for consistency, transparency, "
            "and missing operational details."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    routing_reviewer = Agent(
        role="Service Routing Reviewer",
        goal=(
            "Check whether the selected department is operationally suitable "
            "and identify the next internal action."
        ),
        backstory=(
            "You coordinate municipal and community-service workflows and "
            "prefer clear ownership and traceable handoffs."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    communication_coordinator = Agent(
        role="Citizen Communication Coordinator",
        goal=(
            "Create a concise case action note and a respectful citizen update "
            "using only the provided facts."
        ),
        backstory=(
            "You communicate public-service progress clearly and never promise "
            "deadlines or outcomes that were not provided."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    audit_task = Task(
        description="""
Review deterministic community-report triage #{report_id}.

Category: {category}
Priority: {priority}
Department: {department}
Reasoning: {reasoning}
Missing information: {missing_information}
Duplicate report: {duplicate}
Emergency warning: {emergency_warning}

Check consistency and list any point that requires human confirmation.
Do not change the emergency warning and do not invent facts.
Write in {language}.
""",
        expected_output=(
            "A short audit with confirmed findings and human-check items."
        ),
        agent=triage_reviewer,
    )

    routing_task = Task(
        description="""
Based on the audited triage, recommend the next internal service action.

Department: {department}
Priority: {priority}
Duplicate report: {duplicate}
Missing information: {missing_information}

Provide:
1. Case owner
2. First verification action
3. Duplicate-handling action
4. Escalation condition

Do not invent addresses, staff names, deadlines, or field findings.
Write in {language}.
""",
        expected_output="A concise routing and escalation note.",
        agent=routing_reviewer,
        context=[audit_task],
    )

    communication_task = Task(
        description="""
Create the final action note for report #{report_id}.

Suggested acknowledgment:
{acknowledgment}

Required sections:
1. Internal action summary
2. Information to request from the reporter
3. Citizen status update
4. Human approval checklist

Do not promise a resolution date. Use only the supplied facts.
Write in {language}.
""",
        expected_output="A practical markdown case action note.",
        agent=communication_coordinator,
        context=[audit_task, routing_task],
    )

    crew = Crew(
        agents=[
            triage_reviewer,
            routing_reviewer,
            communication_coordinator,
        ],
        tasks=[audit_task, routing_task, communication_task],
        process=Process.sequential,
        memory=False,
        verbose=True,
    )

    output = crew.kickoff(
        inputs={
            "report_id": report_id,
            "category": report.category,
            "priority": report.priority,
            "department": report.department,
            "reasoning": report.reasoning,
            "missing_information": (
                ", ".join(report.missing_information)
                if report.missing_information
                else "None"
            ),
            "duplicate": (
                f"Report #{report.duplicate_of} at "
                f"{report.duplicate_score:.0%} similarity"
                if report.duplicate_of
                else "None"
            ),
            "emergency_warning": report.emergency_warning or "None",
            "acknowledgment": report.acknowledgment,
            "language": language,
        }
    )

    return str(output)
