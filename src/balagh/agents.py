from __future__ import annotations

import json
import os
from dataclasses import dataclass

from crewai import Agent, Crew, LLM, Process, Task
from dotenv import load_dotenv

from balagh.agent_policy import build_agent_case_context
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
        temperature=0.1,
    )


def _task_text(task: Task) -> str:
    output = getattr(task, "output", None)
    if output is None:
        return ""
    raw = getattr(output, "raw", None)
    return str(raw if raw is not None else output).strip()


def _current_rules_context(stored_report: dict[str, object], language: str) -> str:
    payload = build_agent_case_context(stored_report, language)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def generate_recommendation(
    report_id: int,
    language: str = "Arabic",
) -> AgentRecommendation:
    """Run the two read-only advisory agents for a stored report."""
    stored_report = get_report(report_id)
    if stored_report is None:
        raise ValueError(f"Report #{report_id} does not exist.")

    llm = _llm()
    rules_context = _current_rules_context(stored_report, language)

    triage_agent = Agent(
        role="Independent Triage Auditor",
        goal=(
            "Independently classify the reported issue from its facts, compare that result "
            "with the stored deterministic triage, and explicitly propose corrections when needed."
        ),
        backstory=(
            "You are a critical public-service triage auditor. Stored automated results may be "
            "stale or wrong. You never defend a category merely because it is already stored, "
            "and you never confuse issue domain with urgency. Your advice is read-only."
        ),
        tools=[GetCaseTool(), FindSimilarReportsTool()],
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )

    coordinator_agent = Agent(
        role="Case Action Coordinator",
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
راجع بلاغ BALAGH رقم {report_id} باستخدام الأدوات، ثم حلله باستقلالية.

هذه مقارنة آلية بالقواعد الحالية وليست قرارًا منفذًا:
{rules_context}

التصنيفات المسموح بها ومعناها:
- Traffic Signs & Road Safety: لوحات السرعة واللوحات التنظيمية والإرشادية وإشارات المرور وتخطيط الطريق.
- Roads & Sidewalks: الحفر والأسفلت والأرصفة والهبوط وأضرار سطح الطريق.
- Waste & Cleanliness: النفايات والحاويات والنظافة.
- Street Lighting & Electrical: إنارة الشوارع والمخاطر الكهربائية.
- Water & Drainage: التسرب والصرف والسيول والأنابيب.
- Accessibility: عوائق وصول ذوي الإعاقة.
- Public Facilities: الحدائق والمرافق العامة.
- Noise & Community Disturbance: الضوضاء والإزعاج.
- Needs Human Classification: لا توجد أدلة كافية؛ لا تستخدم تصنيفًا عامًا افتراضيًا.

أعد الأقسام التالية فقط وبالعربية:
1. التصنيف الحالي والمقترح
2. الدليل والثقة
3. تقييم الأولوية
4. الجهة المقترحة
5. التكرار والتقارير المشابهة
6. المعلومات اللازمة فقط
7. نقاط التحقق البشري

قواعد إلزامية:
- ابدأ من عنوان البلاغ ووصفه، ثم قارن بالتصنيف المخزن ومعاينة القواعد الحالية.
- إذا تعارض التصنيف المخزن مع طبيعة المشكلة، اقترح التصحيح صراحة ولا تبرر التصنيف المخزن.
- إذا كانت فئة التخزين مساوية لفئة القواعد الحالية، فاكتب صراحة «متطابق — لا يلزم تصحيح التصنيف» ولا تقترح تغييرها إلى الفئة نفسها.
- matched_category_keywords مجرد عبارات عُثر عليها حرفيًا داخل نص البلاغ لتحديد المجال؛ ليست أدلة ميدانية ولا تثبت وجود العنصر أو سلامته.
- عبارة مثل "no speed limit sign" تعني أن المبلّغ يقول إن اللوحة غائبة؛ مطابقة عبارة "speed limit sign" لا تناقض ذلك.
- عدم وجود خطر فوري يؤثر في الأولوية فقط، ولا يحدد فئة البلاغ.
- لا تطلب الكمية أو عدد المتضررين أو وقت البدء إلا إذا كانت ضرورية فعلًا لهذا النوع.
- في بلاغات اللوحات المرورية، ركز على الطريق واتجاه السير وأقرب تقاطع أو مخرج وصورة الموقع وحالة اللوحة.
- درجة التشابه ترشح تكرارًا محتملًا فقط؛ لا تصفه بأنه تكرار مؤكد حتى يراجعه الموظف.
- لا توجد في BALAGH مهلة خدمة معتمدة؛ لا تخترع عدد ساعات أو أيام أو موعدًا للتصعيد.
- لا تخترع مواقع أو حوادث أو معاينات أو مواعيد أو أسماء موظفين.
- اذكر عدم اليقين بوضوح، ولا تنفذ أي تغيير على البلاغ.
""",
        expected_output=(
            "مراجعة عربية نقدية وموجزة تقترح تصنيفًا وأولوية وجهة واضحة، "
            "وتفصل حقائق البلاغ عن الأمور التي تتطلب تحقق الموظف."
        ),
        agent=triage_agent,
    )

    coordinator_task = Task(
        description=f"""
راجع بلاغ BALAGH رقم {report_id} باستخدام أدوات قراءة الحالة والسجل.
استخدم مراجعة وكيل التدقيق أعلاه، وإذا اقترح تصحيح التصنيف فابنِ الإجراء على التصنيف المقترح لا على التصنيف القديم.

أعد الأقسام التالية فقط وبالعربية:
1. الإجراء التالي المقترح
2. معلومات مطلوبة من المبلّغ
3. شرط التصعيد
4. تحديث مقترح للمواطن
5. قائمة اعتماد الموظف

قواعد إلزامية:
- قدّم إجراءً تشغيليًا خاصًا بنوع المشكلة، لا نموذجًا عامًا يصلح لكل البلاغات.
- لا تكرر تحليل وكيل التدقيق أو مقارنة التصنيفات أو الكلمات المطابقة؛ ابدأ مباشرة بالإجراء.
- لا تطلب معلومات لا تؤثر في التوجيه أو المعالجة.
- لبلاغ لوحة مرورية مفقودة: اقترح التحقق من الموقع واتجاه السير ثم المعاينة الميدانية والتوجيه إلى فريق اللوحات والسلامة المرورية.
- إذا ظهر بلاغ مشابه، سمّه «تكرارًا محتملًا» يحتاج قرار الموظف، ولا تعتبر نسبة التشابه إثباتًا نهائيًا.
- لا توجد مهلة خدمة معتمدة في BALAGH. في قسم شرط التصعيد، لا تذكر ساعات أو أيامًا؛ اربط التصعيد فقط بدليل جديد على خطر فوري أو أثر مرتفع يراجعه الموظف.
- لا تغيّر الحالة ولا تدّعي أن التوجيه أو المعاينة نُفذا فعلًا.
- لا تعد بتاريخ حل ولا تخترع حقائق.
- استخدم صياغة مؤسسية مثل «يرجى تزويدنا»، وتجنب الأخطاء مثل «تحقق بشرى»؛ الصحيح «تحقق بشري» أو «معاينة ميدانية».
- اجعل النص موجزًا وواضحًا للموظف.
""",
        expected_output=(
            "توصية عربية عملية ومختصرة خاصة بالبلاغ، ومعلّمة بوضوح بأنها تتطلب اعتماد الموظف."
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
    header = (
        "توصية الذكاء الاصطناعي — تتطلب اعتماد الموظف"
        if language.lower() == "arabic"
        else "AI RECOMMENDATION — HUMAN APPROVAL REQUIRED"
    )
    final_recommendation = header + "\n\n" + coordinator_review

    return AgentRecommendation(
        triage_review=triage_review,
        coordinator_review=coordinator_review,
        final_recommendation=final_recommendation,
    )
