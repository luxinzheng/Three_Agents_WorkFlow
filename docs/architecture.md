# Architecture

This project packages a focused three-agent workflow for analysis tasks.

Reference inspiration: https://github.com/wanikua/boluobobo-ai-court-tutorial

## Roles

| Agent | ID | Role |
|-------|----|------|
| 中书省 | `zhongshusheng` (C) | Central controller, planner, router, integrator, sole user-facing output |
| 尚书省 | `shangshusheng` (D) | Execution only (follows plans from 中书省; 1-2 parallel instances allowed) |
| 门下省 | `menxiasheng` (E) | Review + quality audit (execution vs plan verification, reliability, truthfulness, completeness) |

## ⚠️ Critical Constraint: Subagent Depth Limit

OpenClaw enforces a **subagent depth limit of 1**. This means:
- 中书省 (depth 0) can spawn 尚书省 and 门下省
- Any spawned agent (depth 1) **cannot** spawn further subagents

**Consequence:** 中书省 must directly orchestrate the entire workflow chain, calling each agent in sequence (or in parallel for execution). The subordinate agents (尚书省 + 门下省) only perform their own task and return results — they do not spawn the next agent.

## Workflow

### Simple Tasks
```
User → C (direct response) → User
```

### Complex Tasks

```
User → C
  C plans internally
  C → sessions_spawn(shangshusheng)  [execute, 1-2 instances for parallel]
  C → sessions_spawn(menxiasheng)    [review + quality audit]
  C → User
```

**All spawning is done by 中书省.** Each subordinate agent completes its role and returns a result JSON.

### Rework Rules
- `execution_defect` → C spawns 尚书省 again (max **1 time**)
- `plan_defect` → C fixes the plan internally (max **1 time**)
- `quality_defect` → C resubmits to 门下省 (max **1 time**)
- After rework limit: stop automatic loop, output current best result + review opinions to user

## allowAgents Configuration

```
zhongshusheng → [shangshusheng, menxiasheng]
shangshusheng → []
menxiasheng   → []
```

> Note: Only 中书省 (depth 0) has allowAgents. Subordinate agents at depth 1 cannot spawn further subagents.

## Inter-Agent Communication

All agents communicate via structured JSON messages with a unified schema:

```json
{
  "meta": { "task_id", "message_id", "version", "from_agent", "to_agent", "timestamp", "task_type", "stage", "status" },
  "payload": { ... },
  "notes": [],
  "issues": [],
  "attachments": []
}
```

See `schemas/message_schema.json` for the full JSON Schema definition.

### Standard Stages
`intake` → `plan` → `execute` → `review` → `final_output`

### Standard Statuses
`pending` | `passed` | `failed` | `needs_rework` | `blocked` | `finalized`

### Standard Issue Types
`missing_information`, `missing_subtask`, `constraint_violation`, `logic_conflict`, `format_error`, `insufficient_evidence`, `hallucination_risk`, `uncertainty_not_marked`, `execution_incomplete`, `plan_defect`, `quality_defect`, `user_request_not_fully_addressed`

## Spawn Strategy: spawn + yield + announce (runtime=subagent)

All `sessions_spawn` calls use `runtime=subagent` mode:

```json
{
  "agentId": "shangshusheng",
  "runTimeoutSeconds": 900
}
```

| Parameter | Value | Purpose |
|-----------|:-----:|---------|
| `agentId` | target agent | Required |
| `runTimeoutSeconds` | 900 | Unified max execution time for all agents |

**❌ Forbidden parameters** (only valid for `runtime=acp`):
- `background: true` — `sessions_spawn` is already non-blocking
- `streamTo: "parent"` — errors: only supported for `runtime=acp`
- Polling `sessions_status` — OpenClaw explicitly forbids it

**Correct flow:**
1. `sessions_spawn(agentId, runTimeoutSeconds=900)` — non-blocking
2. `sessions_yield()` — parent suspends, waits for child
3. Child completes → push-based `announce` event resumes parent
4. Parent receives child's result and continues

**Timeout fallback:**
1. On timeout → record completed steps, report partial progress to user
2. Offer to resume from checkpoint (with partial results)
3. Never auto-retry infinitely

## Channel Policy
- Feishu remains the main channel by default.
- Telegram is optional, bound narrowly to `zhongshusheng` for isolated testing.

## Trigger Policy
- `交部议` is the fixed trigger phrase for forced three-agent mode.

## Python Orchestrator

The `orchestrator/` package provides a runnable implementation:

```bash
python -m orchestrator.cli "交部议 分析主题"
python -m orchestrator.cli --verbose --log-dir ./logs "简单问题"
```

See `orchestrator/` for source code and `schemas/` for JSON Schema definitions.
