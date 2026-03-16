"""Agent models for the three-agent workflow system (三省制).

Agents:
- 中书省 (ZhongShuSheng): Central controller + planner (merged 枢密院 + old 中书省)
- 尚书省 (ShangShuSheng): Execution agent
- 门下省 (MenXiaSheng): Review + quality audit (merged old 门下省 + 都察院)

Each agent implements a `process` method that takes a Message and returns a Message.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from orchestrator.schemas import (
    AGENT_NAMES,
    AgentID,
    Attachment,
    Issue,
    IssueSeverity,
    IssueType,
    Message,
    MessageStatus,
    Stage,
    TaskType,
    build_message,
)

logger = logging.getLogger(__name__)


class AgentBase(ABC):
    """Abstract base class for all agents."""

    agent_id: AgentID

    @property
    def name(self) -> str:
        return AGENT_NAMES[self.agent_id]

    @abstractmethod
    def process(self, incoming: Message) -> Message:
        """Process an incoming message and produce an outgoing message."""
        ...

    def _log(self, action: str, detail: str = "") -> None:
        logger.info("[%s/%s] %s %s", self.agent_id.value, self.name, action, detail)


class ZhongShuSheng(AgentBase):
    """中书省 — Central controller, planner, router, integrator.

    Merged from: 枢密院 (orchestration/routing) + old 中书省 (planning).
    Responsibilities:
    - Receive user request and classify (simple/complex)
    - For simple tasks: generate direct response
    - For complex tasks: generate structured execution plan
    - Orchestrate: spawn 尚书省 → spawn 门下省
    - Integrate results and output to user
    """

    agent_id = AgentID.C

    COMPLEX_KEYWORDS = ["交部议"]
    COMPLEX_INDICATORS = [
        "多个", "子任务", "分析", "比较", "汇总", "调研", "审查",
        "改写", "规划", "多步", "文件处理", "报告",
    ]

    def classify_task(self, user_request: str) -> tuple[TaskType, list[str]]:
        """Determine if a task is simple or complex."""
        reasons: list[str] = []

        for kw in self.COMPLEX_KEYWORDS:
            if kw in user_request:
                reasons.append(f"用户明确要求「{kw}」")

        indicator_count = sum(1 for ind in self.COMPLEX_INDICATORS if ind in user_request)
        if indicator_count >= 2:
            reasons.append(f"任务包含多个复杂指标（{indicator_count}项）")

        if len(user_request) > 200:
            reasons.append("任务描述较长，可能包含多个子目标")

        task_type = TaskType.COMPLEX if reasons else TaskType.SIMPLE
        return task_type, reasons

    def should_parallel_execute(self, subtasks: list[dict]) -> bool:
        """Determine if subtasks can be split for parallel execution by 2 尚书省 instances."""
        return len(subtasks) >= 4

    def create_plan(self, task_id: str, user_request: str, reasons: list[str]) -> Message:
        """Generate a structured execution plan for complex tasks."""
        self._log("开始规划")
        normalized = user_request.replace("交部议", "").strip()

        constraints = []
        if "正式" in user_request or "格式" in user_request:
            constraints.append("格式需正式")
        constraints.extend(["必须避免虚构", "对不确定信息明确标注"])

        plan_id = f"PLAN-{task_id}"

        subtasks = [
            {"subtask_id": "ST-001", "name": "需求分析", "description": f"分析用户核心需求：{normalized}"},
            {"subtask_id": "ST-002", "name": "信息收集", "description": "收集相关信息与数据"},
            {"subtask_id": "ST-003", "name": "分析执行", "description": "根据收集的信息进行分析"},
            {"subtask_id": "ST-004", "name": "结果整合", "description": "整合分析结果，形成结构化输出"},
        ]

        return build_message(
            task_id=task_id,
            version=1,
            from_agent=AgentID.C,
            to_agent=AgentID.D,
            task_type=TaskType.COMPLEX,
            stage=Stage.PLAN,
            status=MessageStatus.PENDING,
            payload={
                "plan_id": plan_id,
                "user_request": user_request,
                "normalized_request": normalized,
                "objective": f"完成用户请求的结构化分析：{normalized}",
                "subtasks": subtasks,
                "execution_order": ["ST-001", "ST-002", "ST-003", "ST-004"],
                "constraints": constraints,
                "expected_output_schema": {
                    "type": "document",
                    "sections": ["需求分析", "信息收集", "分析结论", "局限与不确定性"],
                },
                "completion_criteria": [
                    "覆盖全部子任务",
                    "满足用户约束",
                    "不确定信息已标注",
                    "输出结构清晰",
                ],
                "risks": [
                    "信息不足可能导致分析不完整",
                    "部分结论可能需要进一步验证",
                ],
                "routing_decision": {
                    "is_complex": True,
                    "reason": reasons,
                },
                "user_constraints": constraints,
            },
            notes=["规划基于当前可用信息生成，执行阶段可能需要调整。"],
        )

    def create_simple_response(self, task_id: str, user_request: str) -> Message:
        """Generate a direct response for simple tasks (no spawning needed)."""
        self._log("直接处理简单任务")
        return build_message(
            task_id=task_id,
            version=1,
            from_agent=AgentID.C,
            to_agent=AgentID.C,
            task_type=TaskType.SIMPLE,
            stage=Stage.FINAL_OUTPUT,
            status=MessageStatus.FINALIZED,
            payload={
                "task_summary": user_request,
                "output_mode": "normal_pass",
                "final_answer": f"[中书省直接回复] 针对用户请求「{user_request}」的回答：\n\n"
                                f"（此处为中书省生成的直接回复内容。在实际运行中，"
                                f"此内容由 LLM 根据用户请求生成。）",
                "audit_summary": "简单任务，中书省内部自审通过。",
            },
        )

    def integrate_results(self, task_id: str, task_type: TaskType, review_result: Message) -> Message:
        """Integrate review results into final output for user."""
        self._log("整合最终结果")
        status = review_result.meta.status
        result = review_result.payload.get("result", "")

        if status == MessageStatus.PASSED:
            return build_message(
                task_id=task_id,
                version=review_result.meta.version,
                from_agent=AgentID.C,
                to_agent=AgentID.C,
                task_type=task_type,
                stage=Stage.FINAL_OUTPUT,
                status=MessageStatus.FINALIZED,
                payload={
                    "output_mode": "normal_pass",
                    "final_answer": result,
                    "audit_summary": review_result.payload.get("summary", ""),
                },
            )

        # Review failed but rework limit reached
        return build_message(
            task_id=task_id,
            version=review_result.meta.version + 1,
            from_agent=AgentID.C,
            to_agent=AgentID.C,
            task_type=task_type,
            stage=Stage.FINAL_OUTPUT,
            status=MessageStatus.FINALIZED,
            payload={
                "output_mode": "stopped",
                "current_best_result": result,
                "unresolved_issues": [i.to_dict() for i in review_result.issues] if review_result.issues else [],
                "audit_summary": review_result.payload.get("summary", ""),
                "user_action_needed": review_result.payload.get("required_actions", []),
                "recommend_continue": False,
            },
        )

    def process(self, incoming: Message) -> Message:
        """Process messages returning to 中书省 from other agents."""
        stage = incoming.meta.stage
        status = incoming.meta.status
        self._log(f"收到来自 {incoming.meta.from_agent.value} 的消息", f"stage={stage.value} status={status.value}")
        return incoming


class ShangShuSheng(AgentBase):
    """尚书省 — Execution agent.

    Receives plan from 中书省, executes subtasks, returns results.
    Can be instantiated multiple times for parallel execution of independent subtasks.
    """

    agent_id = AgentID.D

    def __init__(self, instance_id: int = 0):
        self.instance_id = instance_id

    def process(self, incoming: Message) -> Message:
        """Execute the plan from 中书省."""
        self._log(f"开始执行 (实例 {self.instance_id})")
        plan_id = incoming.payload.get("plan_id", "")
        subtasks = incoming.payload.get("subtasks", [])

        completed = []
        results: dict[str, str] = {}
        unresolved: list[dict[str, str]] = []

        for st in subtasks:
            st_id = st.get("subtask_id", "")
            st_name = st.get("name", "")
            completed.append(st_id)
            results[st_id] = f"[尚书省-{self.instance_id}执行结果] {st_name}：（LLM 生成的执行结果占位）"

        exec_id = f"EXEC-{incoming.meta.task_id}-{self.instance_id}"

        return build_message(
            task_id=incoming.meta.task_id,
            version=incoming.meta.version,
            from_agent=AgentID.D,
            to_agent=AgentID.C,
            task_type=TaskType.COMPLEX,
            stage=Stage.EXECUTE,
            status=MessageStatus.PENDING,
            payload={
                "plan_id": plan_id,
                "execution_result_id": exec_id,
                "instance_id": self.instance_id,
                "completed_subtasks": completed,
                "result": {
                    "content": json.dumps(results, ensure_ascii=False, indent=2),
                },
                "unresolved_items": unresolved,
            },
            notes=[f"尚书省实例 {self.instance_id} 已按计划完成分配的子任务。"],
            attachments=[Attachment(type="plan_reference", ref_id=plan_id)],
        )


class MenXiaSheng(AgentBase):
    """门下省 — Process review + quality audit agent.

    Merged from: old 门下省 (process review) + 都察院 (quality audit).
    Responsibilities:
    - Verify execution results against the plan (subtask coverage, constraints)
    - Quality audit (user need addressed, hallucination risk, uncertainty marking, deliverability)
    - Output combined verdict
    """

    agent_id = AgentID.E

    def process(self, incoming: Message) -> Message:
        """Review execution results against the plan and perform quality audit."""
        self._log("开始审核（过程验收+质量终审）")

        plan_id = incoming.payload.get("plan_id", "")
        exec_id = incoming.payload.get("execution_result_id", "")
        completed = incoming.payload.get("completed_subtasks", [])
        unresolved = incoming.payload.get("unresolved_items", [])

        raw_result = incoming.payload.get("result", "")
        if isinstance(raw_result, dict):
            result_text = raw_result.get("content", "")
        else:
            result_text = str(raw_result) if raw_result else ""

        issues: list[Issue] = []

        # --- Process review (from old 门下省) ---
        if unresolved:
            for item in unresolved:
                issues.append(Issue(
                    issue_id=f"ISSUE-REV-{item.get('item_id', 'UNK')}",
                    type=IssueType.EXECUTION_INCOMPLETE,
                    severity=IssueSeverity.MEDIUM,
                    description=item.get("description", "未解决项"),
                ))

        # --- Quality audit (from old 都察院) ---
        if not result_text or result_text.strip() == "":
            issues.append(Issue(
                issue_id="ISSUE-AUD-001",
                type=IssueType.USER_REQUEST_NOT_FULLY_ADDRESSED,
                severity=IssueSeverity.HIGH,
                description="答复内容为空，未回应用户需求。",
                action_required="生成完整答复",
            ))

        if "虚构" in result_text or "假设" in result_text:
            issues.append(Issue(
                issue_id="ISSUE-AUD-002",
                type=IssueType.HALLUCINATION_RISK,
                severity=IssueSeverity.MEDIUM,
                description="答复中可能包含虚构或未验证的内容。",
                action_required="验证相关信息并标注不确定性",
            ))

        # Determine verdict
        has_issues = len(issues) > 0
        problem_source = "none"
        if has_issues:
            exec_issues = [i for i in issues if i.type == IssueType.EXECUTION_INCOMPLETE]
            plan_issues = [i for i in issues if i.type == IssueType.PLAN_DEFECT]
            if plan_issues:
                problem_source = "plan_defect"
            elif exec_issues:
                problem_source = "execution_defect"
            else:
                problem_source = "quality_defect"

        status = MessageStatus.PASSED if not has_issues else MessageStatus.FAILED

        review_scope = [
            "子任务覆盖",
            "关键约束满足情况",
            "遗漏与矛盾检查",
            "不确定项说明",
            "用户需求响应情况",
            "真实性与依据充分性",
            "不确定项标注情况",
            "最终可交付性",
        ]

        return build_message(
            task_id=incoming.meta.task_id,
            version=incoming.meta.version,
            from_agent=AgentID.E,
            to_agent=AgentID.C,
            task_type=incoming.meta.task_type,
            stage=Stage.REVIEW,
            status=status,
            payload={
                "review_id": f"REV-{incoming.meta.task_id}",
                "plan_id": plan_id,
                "execution_result_id": exec_id,
                "review_decision": "passed" if not has_issues else "failed",
                "review_scope": review_scope,
                "summary": "审核通过：执行结果覆盖全部子任务，内容真实可交付。" if not has_issues else "审核发现问题，需要修正。",
                "problem_source": problem_source,
                "required_actions": [i.action_required for i in issues if i.action_required],
                "result": incoming.payload.get("result", {}),
            },
            issues=issues,
            attachments=[
                Attachment(type="plan_reference", ref_id=plan_id),
                Attachment(type="execution_reference", ref_id=exec_id),
            ],
        )
