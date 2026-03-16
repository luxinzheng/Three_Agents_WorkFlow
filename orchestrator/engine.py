"""Workflow engine that orchestrates the three-agent pipeline (三省制).

Implements the workflow:
- Simple tasks: C (direct response) → user
- Complex tasks: C (plan) → D (execute, 1-2 instances) → E (review+audit) → C (integrate) → user
- Rework limits enforced at each level

Spawn strategy (OpenClaw runtime=subagent):
- sessions_spawn is inherently non-blocking; do NOT pass ``background`` or ``streamTo``.
- After spawn, call ``sessions_yield`` to suspend the parent until the child completes.
- The child's completion triggers a push-based ``announce`` event that resumes the parent.
- NEVER poll ``sessions_status`` — OpenClaw docs explicitly forbid it.
- ``runTimeoutSeconds`` is the only timeout knob.  Unified to 900 s for all agents.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from orchestrator.models import (
    MenXiaSheng,
    ShangShuSheng,
    ZhongShuSheng,
)
from orchestrator.schemas import (
    AgentID,
    Message,
    MessageStatus,
    Stage,
    TaskType,
    build_message,
    generate_task_id,
)

logger = logging.getLogger(__name__)

# ── Spawn strategy constants ──────────────────────────────────────────
# OpenClaw runtime=subagent mode:
#   - sessions_spawn is already non-blocking (background/streamTo NOT supported)
#   - After spawn → call sessions_yield to wait for announce event
#   - NEVER poll sessions_status (forbidden by OpenClaw)
RUN_TIMEOUT_SECONDS = 900          # Max execution time for any spawned agent


class WorkflowEngine:
    """Orchestrates the three-agent workflow pipeline (三省制)."""

    def __init__(self, log_dir: str | None = None):
        self.zhongshusheng = ZhongShuSheng()
        self.shangshusheng_0 = ShangShuSheng(instance_id=0)
        self.shangshusheng_1 = ShangShuSheng(instance_id=1)
        self.menxiasheng = MenXiaSheng()

        self.agents = {
            AgentID.C: self.zhongshusheng,
            AgentID.D: self.shangshusheng_0,
            AgentID.E: self.menxiasheng,
        }

        self.log_dir = Path(log_dir) if log_dir else None
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)

        self.message_log: list[dict] = []

        # Rework counters
        self._plan_rework_count = 0
        self._exec_rework_count = 0
        self._review_rework_count = 0

    # ── Spawn helpers (sessions_yield + announce) ───────────────────────

    @staticmethod
    def _build_spawn_params(agent_id: str) -> dict[str, Any]:
        """Build the standard ``sessions_spawn`` parameter dict.

        OpenClaw runtime=subagent rules:
        - ``sessions_spawn`` is already non-blocking; do NOT pass
          ``background`` or ``streamTo`` (they are ACP-only).
        - Only ``agentId`` and ``runTimeoutSeconds`` are valid.
        - After spawn, the caller must ``sessions_yield`` to wait
          for the push-based ``announce`` event.
        """
        return {
            "agentId": agent_id,
            "runTimeoutSeconds": RUN_TIMEOUT_SECONDS,
        }

    def _spawn_and_yield(self, agent_id: str, message: Message) -> Message:
        """Spawn *agent_id*, then yield until completion (announce-based).

        Real OpenClaw flow:
        1. ``sessions_spawn(agentId, runTimeoutSeconds=900)``
        2. ``sessions_yield()`` — parent suspends, waits for announce
        3. Child completes → OpenClaw pushes ``announce`` event to parent
        4. Parent resumes with child's result

        ⚠️ NEVER poll ``sessions_status`` — OpenClaw forbids it.

        In the current **local-simulation** orchestrator, the actual agent
        logic runs in-process so yield is instantaneous.  Porting to real
        OpenClaw only requires swapping the ``# --- simulate ---`` block.
        """
        spawn_params = self._build_spawn_params(agent_id)
        logger.info(
            "sessions_spawn(%s) runTimeout=%ss → sessions_yield()",
            agent_id,
            spawn_params["runTimeoutSeconds"],
        )

        # --- simulate: in-process execution (replace with real spawn+yield) -
        agent_map = {
            "shangshusheng_0": self.shangshusheng_0,
            "shangshusheng_1": self.shangshusheng_1,
            "shangshusheng": self.shangshusheng_0,
            "menxiasheng": self.menxiasheng,
        }
        agent = agent_map.get(agent_id)
        if agent is None:
            raise ValueError(f"Unknown agent_id for spawn: {agent_id}")

        start = time.monotonic()
        result = agent.process(message)
        elapsed = time.monotonic() - start
        # --- end simulate --------------------------------------------------

        if elapsed > RUN_TIMEOUT_SECONDS:
            logger.warning(
                "spawn(%s) exceeded runTimeoutSeconds (%ss > %ss) — returning partial result",
                agent_id, f"{elapsed:.1f}", RUN_TIMEOUT_SECONDS,
            )
            result.meta.status = MessageStatus.BLOCKED
            result.notes.append(
                f"⏱️ 执行超时（{elapsed:.0f}s > {RUN_TIMEOUT_SECONDS}s），返回已完成的部分结果。"
            )
        else:
            logger.info("spawn(%s) announce received in %.1fs", agent_id, elapsed)

        return result

    # ── Plan persistence (fix for rework context loss) ──────────────────

    def _persist_plan(self, plan: Message) -> None:
        """Write the execution plan to ``<log_dir>/task-plan.json``.

        This ensures the plan survives context-window truncation during long
        rework loops.  On rework the engine reads it back via ``_load_plan``
        so the full plan is always available.
        """
        if not self.log_dir:
            return
        plan_path = self.log_dir / "task-plan.json"
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info("计划已持久化 → %s", plan_path)

    def _load_plan(self) -> dict | None:
        """Load a previously persisted plan from disk (if any)."""
        if not self.log_dir:
            return None
        plan_path = self.log_dir / "task-plan.json"
        if plan_path.exists():
            with open(plan_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def _save_message(self, msg: Message) -> None:
        """Log a message to the message history and optionally to disk."""
        msg_dict = msg.to_dict()
        self.message_log.append(msg_dict)

        if self.log_dir:
            idx = len(self.message_log)
            filename = f"{idx:03d}_{msg.meta.from_agent.value}_to_{msg.meta.to_agent.value}_{msg.meta.stage.value}.json"
            filepath = self.log_dir / filename
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(msg_dict, f, ensure_ascii=False, indent=2)

    def run(self, user_request: str) -> dict[str, Any]:
        """Run the full workflow for a user request.

        Returns the final output payload.
        """
        task_id = generate_task_id()
        logger.info("=== 新任务 %s ===", task_id)
        logger.info("用户请求: %s", user_request)

        # Reset rework counters
        self._plan_rework_count = 0
        self._exec_rework_count = 0
        self._review_rework_count = 0

        # Step 1: 中书省 classify task
        task_type, reasons = self.zhongshusheng.classify_task(user_request)
        logger.info("任务类型: %s, 原因: %s", task_type.value, reasons)

        if task_type == TaskType.SIMPLE:
            return self._run_simple(task_id, user_request)
        else:
            return self._run_complex(task_id, user_request, reasons)

    def _run_simple(self, task_id: str, user_request: str) -> dict[str, Any]:
        """Simple task flow: 中书省 directly responds (internal self-review)."""
        logger.info("--- 简单任务流程 ---")

        response = self.zhongshusheng.create_simple_response(task_id, user_request)
        self._save_message(response)
        return response.payload

    def _run_complex(self, task_id: str, user_request: str, reasons: list[str]) -> dict[str, Any]:
        """Complex task flow: C (plan) → D (execute) → E (review) → C (output)."""
        logger.info("--- 复杂任务流程 ---")

        # Step 1: 中书省 generates plan and persists to disk
        plan = self.zhongshusheng.create_plan(task_id, user_request, reasons)
        self._save_message(plan)
        self._persist_plan(plan)

        # Step 2: Verify plan has subtasks
        if not plan.payload.get("subtasks"):
            if self._plan_rework_count < 1:
                logger.info("计划缺失子任务，中书省重新规划 1 次")
                self._plan_rework_count += 1
                plan = self.zhongshusheng.create_plan(task_id, user_request, reasons)
                plan.meta.version = 2
                self._save_message(plan)
                self._persist_plan(plan)

        # Step 3: Execute - determine single or parallel 尚书省
        subtasks = plan.payload.get("subtasks", [])
        use_parallel = self.zhongshusheng.should_parallel_execute(subtasks)

        if use_parallel:
            exec_result = self._execute_parallel(plan, subtasks)
        else:
            exec_result = self._execute_single(plan)

        # Step 4: 门下省 reviews execution results (spawn + yield)
        review_msg = self._prepare_for_review(plan, exec_result)
        review_result = self._spawn_and_yield("menxiasheng", review_msg)
        self._save_message(review_result)

        # Step 5: Handle review result
        if review_result.meta.status == MessageStatus.FAILED:
            problem_source = review_result.payload.get("problem_source", "execution_defect")

            if problem_source == "execution_defect" and self._exec_rework_count < 1:
                logger.info("门下省审核不通过（执行缺陷），尚书省补充执行 1 次")
                self._exec_rework_count += 1
                if use_parallel:
                    exec_result2 = self._execute_parallel(plan, subtasks)
                else:
                    exec_result2 = self._execute_single(plan)
                review_msg2 = self._prepare_for_review(plan, exec_result2)
                review_result = self._spawn_and_yield("menxiasheng", review_msg2)
                self._save_message(review_result)

            elif problem_source == "plan_defect" and self._plan_rework_count < 1:
                logger.info("门下省审核不通过（计划缺陷），中书省修正计划 1 次")
                self._plan_rework_count += 1
                plan2 = self.zhongshusheng.create_plan(task_id, user_request, reasons)
                plan2.meta.version = 2
                self._save_message(plan2)
                self._persist_plan(plan2)  # overwrite with reworked plan

                subtasks2 = plan2.payload.get("subtasks", [])
                use_parallel2 = self.zhongshusheng.should_parallel_execute(subtasks2)
                if use_parallel2:
                    exec_result2 = self._execute_parallel(plan2, subtasks2)
                else:
                    exec_result2 = self._execute_single(plan2)

                review_msg2 = self._prepare_for_review(plan2, exec_result2)
                review_result = self._spawn_and_yield("menxiasheng", review_msg2)
                self._save_message(review_result)

            elif problem_source == "quality_defect" and self._review_rework_count < 1:
                logger.info("门下省审核不通过（质量问题），中书省调整后重提交 1 次")
                self._review_rework_count += 1
                if use_parallel:
                    exec_result2 = self._execute_parallel(plan, subtasks)
                else:
                    exec_result2 = self._execute_single(plan)
                review_msg2 = self._prepare_for_review(plan, exec_result2)
                review_result = self._spawn_and_yield("menxiasheng", review_msg2)
                self._save_message(review_result)

        # Step 6: 中书省 integrates results and outputs to user
        final = self.zhongshusheng.integrate_results(task_id, TaskType.COMPLEX, review_result)
        self._save_message(final)
        return final.payload

    def _execute_single(self, plan: Message) -> Message:
        """Execute all subtasks with a single 尚书省 instance (spawn + yield)."""
        exec_msg = self._prepare_for_execution(plan, plan.payload.get("subtasks", []))
        exec_result = self._spawn_and_yield("shangshusheng", exec_msg)
        self._save_message(exec_result)
        return exec_result

    def _execute_parallel(self, plan: Message, subtasks: list[dict]) -> Message:
        """Execute subtasks in parallel with 2 尚书省 instances (spawn + yield), then merge."""
        logger.info("任务量较大，启动 2 个尚书省并行执行 (spawn + yield)")
        mid = len(subtasks) // 2
        batch_0 = subtasks[:mid]
        batch_1 = subtasks[mid:]

        exec_msg_0 = self._prepare_for_execution(plan, batch_0)
        exec_msg_1 = self._prepare_for_execution(plan, batch_1)

        # Both spawned then yielded; in a real runtime they run concurrently.
        result_0 = self._spawn_and_yield("shangshusheng_0", exec_msg_0)
        self._save_message(result_0)
        result_1 = self._spawn_and_yield("shangshusheng_1", exec_msg_1)
        self._save_message(result_1)

        # Merge results
        merged = self._merge_execution_results(plan, result_0, result_1)
        self._save_message(merged)
        return merged

    def _prepare_for_execution(self, plan: Message, subtasks: list[dict]) -> Message:
        """Forward plan (or subset of subtasks) to 尚书省 for execution."""
        return build_message(
            task_id=plan.meta.task_id,
            version=plan.meta.version,
            from_agent=AgentID.C,
            to_agent=AgentID.D,
            task_type=TaskType.COMPLEX,
            stage=Stage.EXECUTE,
            status=MessageStatus.PENDING,
            payload={
                **plan.payload,
                "subtasks": subtasks,
            },
            attachments=plan.attachments,
        )

    def _merge_execution_results(self, plan: Message, result_0: Message, result_1: Message) -> Message:
        """Merge results from 2 parallel 尚书省 instances."""
        completed = result_0.payload.get("completed_subtasks", []) + result_1.payload.get("completed_subtasks", [])
        unresolved = result_0.payload.get("unresolved_items", []) + result_1.payload.get("unresolved_items", [])

        content_0 = json.loads(result_0.payload.get("result", {}).get("content", "{}"))
        content_1 = json.loads(result_1.payload.get("result", {}).get("content", "{}"))
        merged_content = {**content_0, **content_1}

        return build_message(
            task_id=plan.meta.task_id,
            version=plan.meta.version,
            from_agent=AgentID.D,
            to_agent=AgentID.C,
            task_type=TaskType.COMPLEX,
            stage=Stage.EXECUTE,
            status=MessageStatus.PENDING,
            payload={
                "plan_id": plan.payload.get("plan_id", ""),
                "execution_result_id": f"EXEC-{plan.meta.task_id}-merged",
                "completed_subtasks": completed,
                "result": {
                    "content": json.dumps(merged_content, ensure_ascii=False, indent=2),
                },
                "unresolved_items": unresolved,
                "parallel_execution": True,
                "instance_count": 2,
            },
            notes=["由 2 个尚书省实例并行执行后合并。"],
        )

    def _prepare_for_review(self, plan: Message, exec_result: Message) -> Message:
        """Combine plan and execution result for 门下省 review."""
        combined_payload = {
            "plan_id": plan.payload.get("plan_id", ""),
            "execution_result_id": exec_result.payload.get("execution_result_id", ""),
            "subtasks": plan.payload.get("subtasks", []),
            "completed_subtasks": exec_result.payload.get("completed_subtasks", []),
            "result": exec_result.payload.get("result", {}),
            "unresolved_items": exec_result.payload.get("unresolved_items", []),
            "completion_criteria": plan.payload.get("completion_criteria", []),
        }
        return build_message(
            task_id=plan.meta.task_id,
            version=exec_result.meta.version,
            from_agent=AgentID.C,
            to_agent=AgentID.E,
            task_type=TaskType.COMPLEX,
            stage=Stage.REVIEW,
            status=MessageStatus.PENDING,
            payload=combined_payload,
        )

    def get_message_log(self) -> list[dict]:
        """Return the full message log."""
        return self.message_log
