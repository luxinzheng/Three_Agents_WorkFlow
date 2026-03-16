# Changelog

## 0.5.1
- [#1] Added Brave Search throttling guidelines to 尚书省 SOUL.md + identity (1 QPS limit, merge queries, max 3 searches per subtask)
- [#2] Fixed misleading "转交" wording in 尚书省 — now clarifies 中书省 auto-spawns 门下省 after execution
- [#3] Added plan persistence (_persist_plan / _load_plan) in engine.py — writes task-plan.json to prevent context truncation during rework
- [#4] Documented known limitation: subagent runtime only injects AGENTS.md + TOOLS.md, not SOUL.md/USER.md (role definitions rely on identity.theme)
- [#5] Added require_user_decision output format contract to 门下省 SOUL.md + identity (with user_action_options for second-pass failures)
- [#6] Documented known limitation: tools.profile "coding" applies globally but has no functional impact on non-coding agents

## 0.5.0
- Unified runTimeoutSeconds=900 for all agents (no per-agent differentiation)
- All sessions_spawn calls now use background=true + polling (non-blocking)
- Added streamTo="parent" for real-time output streaming from subagents
- Added _spawn_background() helper in engine.py with polling loop and timeout fallback
- Added spawnDefaults section in openclaw-three-agent.example.json
- Updated SOUL.md, SKILL.md, architecture.md, migration.md with new spawn strategy

## 0.4.0
- Refactored from five-agent (五院制) to three-agent (三省制) architecture
- Removed 枢密院 (shumiyuan) and 都察院 (duchayuan) agents
- 中书省 (zhongshusheng) now serves as central controller + planner (merged 枢密院 + old 中书省)
- 门下省 (menxiasheng) now handles both review and quality audit (merged old 门下省 + 都察院)
- 尚书省 (shangshusheng) supports 1-2 parallel instances for execution
- Updated allowAgents: zhongshusheng → [shangshusheng, menxiasheng], others → []
- Rework rules: execution_defect → rework D, plan_defect → C fixes, quality_defect → resubmit E (each max 1x)
- Updated all documentation, scripts, and test cases for three-agent workflow

## 0.3.0
- Added conservative config patch workflow with dry-run and backup
- Added install-prompt for AI-assisted setup
- Upgraded doctor output with graded diagnostics and repair hints
- Expanded docs for trigger semantics, Telegram isolation, Feishu safety, and upgrades
- Improved README toward a more publishable open-source layout

## 0.2.0
- Added install.sh / install-lite.sh / doctor.sh
- Added docs, templates, tests, and workspace skeletons
- Added trigger semantics for `交部议`

## 0.1.0
- Initial GitHub-distributable pack with wuyuan-analysis skill and migration template
