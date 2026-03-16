# Three-agent workflow migration guide

## Goal

Port the three-agent analysis workflow to another OpenClaw instance with minimal manual editing.

## Agents to create

1. `zhongshusheng` — 中书省
2. `shangshusheng` — 尚书省
3. `menxiasheng` — 门下省

## ⚠️ Critical: Subagent Depth Constraint

OpenClaw enforces a **subagent depth limit of 1**. This means only depth-0 agents can spawn subagents.

**Correct allowAgents configuration:**
- `zhongshusheng` may call: `shangshusheng`, `menxiasheng`
- All other agents: **no allowAgents** (empty)

> Only 中书省 orchestrates the chain. Subordinate agents at depth 1 cannot spawn further subagents.

## Workflow Orchestration

中书省 (depth 0) directly orchestrates the entire chain:

```
中书省 → plans internally
中书省 → spawn(shangshusheng)  → receive execution result JSON (1-2 instances for parallel)
中书省 → spawn(menxiasheng)    → receive review + audit verdict JSON
中书省 → output to user
```

Each subordinate agent completes its own role and returns results. They do NOT spawn the next agent.

## Role contract

### 中书省 / zhongshusheng
- Visible entrypoint to the user
- Route simple tasks directly, but force full workflow when user says "交部议"
- Plan internally, then spawn: shangshusheng (1-2 instances) → menxiasheng
- Handle rework: spawn shangshusheng again if execution_defect (max 1 rework)
- Handle plan defect: fix plan internally (max 1 rework)
- Handle quality defect: resubmit to menxiasheng (max 1 rework)
- Stop automatic loop after rework limits

### 尚书省 / shangshusheng
Produce JSON execution result:
- completed items, incomplete items, missing information
- blockers/conflicts, plan defects noted

⚠️ Must NOT call sessions_spawn. Return JSON directly.

### 门下省 / menxiasheng
- Validate execution against 中书省 plan
- Perform quality audit: user need addressed, no hallucination, uncertainty marked, deliverable
- Output verdict: passed / failed
- If failed: specify problem_source (execution_defect, plan_defect, or quality_defect)
- Do not introduce unrelated requirements
- On second rejection: require_user_decision=true, stop loop

⚠️ Must NOT run shell commands. Must NOT call sessions_spawn. Return JSON directly.

## Inter-agent communication contract

All internal handoffs between agents use JSON-formatted payloads.

Recommended minimum fields:
- `meta`: task_id, from_agent, to_agent, stage, status
- `payload`: task/plan/result/review content
- `issues`: structured issue list

## Channel migration policy

### Telegram
- Bind the target Telegram DM or test entrypoint to `zhongshusheng`.
- Use Telegram as the isolated three-agent testing entry point.

### Feishu
- Do **not** change the existing Feishu main channel by default.
- Treat the default migration posture as: **Telegram for three-agent testing, Feishu unchanged**.

## Trigger phrase contract

- If the user says **"交部议"**, force the three-agent workflow.
- Interpret it as a workflow command, not ordinary prose.

## Spawn configuration

All `sessions_spawn` calls must include these parameters:

```json
{
  "background": true,
  "runTimeoutSeconds": 900,
  "timeoutSeconds": 900,
  "streamTo": "parent"
}
```

- `background: true` — non-blocking spawn; caller polls `sessions_status` every 5s
- `streamTo: "parent"` — real-time output forwarding to parent agent
- `runTimeoutSeconds: 900` — unified timeout for all agents (no per-agent differentiation)
- On timeout: record partial results, notify user, offer checkpoint resume

## Recommended smoke test

Use a prompt like:
- "请调研一下油价上升对中国房地产市场的影响，交部议。"

Expected behavior:
- 中书省 recognizes forced three-agent mode
- 中书省 plans internally, then spawns: 尚书省 → 门下省
- 中书省 returns final integrated answer to user
