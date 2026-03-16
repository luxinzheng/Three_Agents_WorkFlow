---
name: wuyuan-analysis
description: Three-agent analysis workflow for OpenClaw using 中书省、尚书省、门下省. The sole trigger phrase is "交部议" — only activate this skill when the user explicitly says "交部议". Do not activate based on generic mentions of multi-agent analysis or three-agent workflow.
---

# 三省制分析工作流（Three-Agent Analysis）

## 一、设计目标

本系统采用三 Agent 协同机制，模拟"三省制"工作体系：

1. 对简单任务快速处理，减少不必要的多轮协同；
2. 对复杂任务采用"规划—执行—审核"的分层流程；
3. 通过门下省一站式把关（过程验收+质量终审），降低虚构信息、依据不足、遗漏用户需求等风险；
4. 在无法继续有效优化时，终止循环并向用户明确说明当前结果、存在问题及后续所需信息。

## 二、触发短语

如用户说 **"交部议"**，强制启动三省制完整流程，即使任务本可直接回答。

## 三、Agent 体系

| Agent | 代号 | 角色 |
|-------|------|------|
| 中书省 (zhongshusheng) | C | 系统总控，接收/分流/规划/调度/整合/输出 |
| 尚书省 (shangshusheng) | D | 按计划执行（可1-2个实例并行） |
| 门下省 (menxiasheng) | E | 过程验收 + 质量终审 |

所有 Agent 之间的通信必须采用 JSON 格式。

## 四、⚠️ 关键架构约束：子代理深度限制

**OpenClaw 子代理最大深度为 1。** 被 spawn 的 Agent 不能再 spawn 其他 Agent。

**正确工作流（中书省串行 spawn 所有省）：**

```
中书省内部：任务分解，生成计划
中书省 → sessions_spawn(shangshusheng)  [执行，传入计划，返回执行结果]
  （大任务：spawn 2个尚书省实例并行执行，合并结果）
中书省 → sessions_spawn(menxiasheng)    [审核，传入计划+结果，返回verdict]
  verdict=failed(execution_defect) → 中书省 spawn 尚书省补充1次
  verdict=failed(plan_defect) → 中书省修正计划后重新执行1次
  verdict=failed(quality_defect) → 中书省调整后重提交1次
中书省汇总输出给用户
```

**allowAgents 正确配置：**
```
zhongshusheng → [shangshusheng, menxiasheng]
其余各省     → [] （无子 Agent 权限）
```

## 五、各 Agent 职责

### 5.1 中书省（Agent C）

**职责：**
1. 接收用户请求并生成唯一任务编号
2. 判断简单/复杂任务
3. 简单任务直接执行并内部自审
4. 复杂任务：内部制定计划，串行 spawn 尚书省→门下省
5. 根据门下省意见决定：通过 / 发回尚书省补充（1次） / 修正计划（1次） / 重提交（1次）
6. **统一负责对用户发言**，其他 Agent 不得直接面向用户
7. 大任务可同时 spawn 2个尚书省并行执行

### 5.2 尚书省（Agent D）

严格按计划执行，标注完成项/信息不足/无法完成项/计划缺陷。
可作为并行实例之一执行部分子任务。
⚠️ 禁止调用 sessions_spawn，直接返回 JSON 结果。

### 5.3 门下省（Agent E）

**过程验收：** 对照计划验收执行结果，标注 execution_defect 或 plan_defect。
**质量终审：** 审查是否回应用户核心需求、是否虚构/臆测、不确定信息是否标注、是否可交付。标注 quality_defect。
⚠️ 禁止调用 sessions_spawn，禁止运行 shell 命令，直接返回 JSON 审核意见。

## 六、⏱️ Spawn 参数规范与超时策略（runtime=subagent）

### sessions_spawn 调用参数

```json
{
  "agentId": "shangshusheng",
  "runTimeoutSeconds": 900
}
```

| 参数 | 值 | 说明 |
|------|:--:|------|
| `agentId` | 目标省 ID | 必填 |
| `runTimeoutSeconds` | 900 | 所有省统一最大执行时间 |

### ⚠️ 禁用参数（runtime=subagent 不支持）

- ❌ `background: true` — sessions_spawn 本身已是非阻塞，该参数无效
- ❌ `streamTo: "parent"` — 报错：仅 runtime=acp 支持
- ❌ 轮询 `sessions_status` — OpenClaw 明确禁止主动轮询

### spawn + yield 模式（正确流程）

```
1. sessions_spawn(agentId='shangshusheng', runTimeoutSeconds=900)
2. sessions_yield()              ← 挂起中书省，等待子省完成
3. 子省完成 → announce 事件推回    ← OpenClaw push-based 通知
4. 中书省恢复，获得子省返回结果
```

### 大任务并行执行

当子任务数量 >= 4 且子任务间相互独立时，中书省可同时 spawn 2个尚书省实例，各分配部分子任务，分别 yield 等待 announce 完成后合并结果再提交门下省审核。

### 超时兜底逻辑

1. 若某省 spawn 超时（超过 900s）→ 中书省记录已完成步骤，告知用户当前进度
2. 提示用户是否从断点继续（提供已有中间结果）
3. **不自动无限重试**，避免资源浪费

---

## 七、流程规则

### 复杂任务触发条件

满足任一即为复杂任务：
1. 用户明确要求"交部议"
2. 任务包含多个子目标、多个交付物或多个步骤
3. 任务需要先规划再执行
4. 任务需要审查、校对、核验、比较、汇总等多阶段输出

### 返工上限
- 尚书省最多补充执行 1 次（门下省打回执行缺陷）
- 中书省最多修正计划 1 次（门下省打回计划缺陷）
- 质量问题最多重提交 1 次

### 停止条件
满足任一时必须停止：
1. 同一层级返工已达上限
2. 新一轮修改未引入实质性改进
3. 问题源于用户信息不足
4. 继续执行会造成重复空转

## 八、Agent 间 JSON 通信规范

### 通用顶层结构

```json
{
  "meta": {
    "task_id": "string",
    "from_agent": "C|D|E",
    "to_agent": "C|D|E",
    "stage": "intake|plan|execute|review|final_output",
    "status": "pending|passed|failed|needs_rework|blocked|finalized"
  },
  "payload": {},
  "notes": [],
  "issues": []
}
```

### 标准问题类型
`missing_information` | `missing_subtask` | `constraint_violation` | `logic_conflict` |
`format_error` | `insufficient_evidence` | `hallucination_risk` | `uncertainty_not_marked` |
`execution_incomplete` | `plan_defect` | `user_request_not_fully_addressed`

## 九、系统禁止事项

1. 禁止 Agent 之间以自由文本替代 JSON 正式交接
2. 禁止将未验证内容陈述为确定事实
3. 禁止重复返工超过规定次数
4. 禁止尚书省擅自更改任务目标
5. 禁止尚书省和门下省调用 sessions_spawn（depth 限制）
6. 禁止中书省在返工无实质收益时继续空转

## Migration

When porting to another OpenClaw:
1. Read `references/migration.md`
2. Recreate three agents and identities
3. Set `subagents.allowAgents`:
   - 中书省 → [shangshusheng, menxiasheng]
   - 其余各省 → (empty, no subagents)
4. Bind Telegram only to zhongshusheng for isolated testing
5. Keep Feishu on existing main agent path
6. Preserve trigger phrase "交部议"
7. Run smoke test

## Resources

- Migration guide: `references/migration.md`
- Example config fragment: `assets/openclaw-five-agent.example.json`
- JSON Schema: `../../schemas/message_schema.json`
- Python orchestrator: `../../orchestrator/`
