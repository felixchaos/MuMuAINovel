# Prompt Audit Repair Memory

This file is the local working memory for the prompt audit repair pass.

Scope:
- Improve prompt effectiveness by fixing existing wiring and reducing duplication.
- Do not add new workflow pages, new prompt dashboards, new tables, or parallel fact stores.
- Keep changes inside existing `PromptService`, AI call plumbing, and current API flows.

Issues to fix:
1. `AIService` must merge the user/default system prompt with per-call system prompts instead of replacing one with the other.
2. `enable_mcp`/`auto_mcp` must actually control AI calls. Creative generation should not force `tool_choice="required"` unless the caller explicitly wants required tool use.
3. User-facing prompt flows that still build large f-string prompts must be registered in template management:
   - incremental career generation
   - full-text character analysis
   - relationship generation
4. Chapter analysis should not silently analyze only the first 8000 characters when the task says it analyzes the chapter.
5. Full chapter regeneration should not inject the same writing style into both `system_prompt` and user prompt.
6. Template management should not expose unused planning templates as if they are active capabilities.

Verification targets:
- Prompt templates declared in `PromptService` are registered in `get_all_system_templates`.
- Template registry parameter lists match actual placeholders.
- Existing chapter generation, analysis, polish, and prompt registry tests still pass.

Completed in this repair pass:
1. `AIService` now merges global/default and per-call system prompts once, including MCP tool-call continuation rounds.
2. Creative MCP-enabled calls use `tool_choice="auto"` only when the caller enables MCP; user-facing generation no longer forces required tool use.
3. Hardcoded user-facing prompt flows were moved into `PromptService` and template registry:
   - outline/character/organization polish optimization
   - full-text character analysis
   - relationship incremental generation
   - career incremental generation
4. Chapter analysis now samples long chapters from head, middle, and tail instead of only the opening.
5. Full chapter regeneration no longer duplicates writing style content in both system and user prompt.
6. Unused planning/prediction templates were removed from template management:
   - `MCP_WORLD_BUILDING_PLANNING`
   - `MCP_CHARACTER_PLANNING`
   - `AUTO_CHARACTER_ANALYSIS`
   - `AUTO_ORGANIZATION_ANALYSIS`
7. Added prompt-registry tests to keep constants, registry entries, and placeholders synchronized.

Verified:
- `python -m compileall -q backend/app backend/tests`
- `backend/tests/test_txt_parser_service.py`
- `backend/tests/test_name_authority_service.py`
- `backend/tests/test_prompt_template_registry.py`
- `git diff --check`
- `npm --prefix frontend run build`
