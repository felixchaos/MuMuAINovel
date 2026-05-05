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

Current repair loop:
- Goal: make the final effective prompt match the template's design intent after dynamic context, style, retry, and MCP tool-result stitching.
- MCP tool results may add reference data, but must never replace or weaken the original output contract. If the original prompt says "only JSON", "only正文", or forbids Markdown/explanations, the follow-up prompt after tool calls must preserve those constraints.
- Streaming provider tool follow-up must not duplicate the original prompt. Keep the original prompt in prior messages and append only tool results plus contract-preserving follow-up instructions.
- `enable_mcp` must be carried through each workflow that exposes the switch:
  - outline create/continue foreground and background calls, including JSON retry calls
  - batch chapter generation task creation and per-chapter generation
- Do not add new workflow pages, new tables unless an existing task model cannot carry the switch, or large new prompt frameworks.

Current issues to fix:
1. Replace generic "give a complete detailed answer" tool-result follow-ups with contract-preserving instructions in `AIService` and provider streaming paths.
2. Pass `auto_mcp=enable_mcp` and matching `tool_choice` through all outline generation calls.
3. Persist and pass batch chapter `enable_mcp` so batch generation matches single chapter generation behavior.

Completed in current repair loop:
1. Added `app.services.tool_prompting.build_tool_result_followup()` as the single contract-preserving MCP tool-result follow-up builder.
2. Updated non-streaming `AIService` MCP continuation to preserve the original prompt's JSON/body/style/output constraints and accumulate tool contexts across rounds.
3. Updated OpenAI/Anthropic/Gemini streaming provider tool-result follow-up prompts to preserve the original output contract. OpenAI no longer duplicates the original user prompt when appending tool results.
4. Routed `enable_mcp` through outline create/continue foreground and background generation, including JSON retry calls.
5. Added `BatchGenerationTask.enable_mcp`, Alembic migrations, and batch generation plumbing so batch chapter generation uses the same MCP switch semantics as single chapter generation.

Verified in current repair loop:
- `python3 -m compileall -q backend/app backend/tests backend/alembic`
- Targeted prompt registry constants/placeholders check
- `PYTHONPATH=backend python3 backend/tests/test_txt_parser_service.py`
- `PYTHONPATH=backend python3 backend/tests/test_name_authority_service.py`
- `git diff --check`
- `npm --prefix frontend run build`

Known local verification limitation:
- `PYTHONPATH=backend python3 backend/tests/test_prompt_template_registry.py` still requires local backend dependencies missing from system Python (`pydantic_settings`). Use the project backend environment or install requirements to run the full file.

Current repair loop: AI polish/input-field assistant consolidation
- Goal: make every input-field AI polish/assist tool feel and behave like the same product capability, while reducing prompt duplication and keeping prompt templates authoritative.
- Do not add a new page, new table, or another prompt framework.
- Do not make prompts longer to fix inconsistency. Prefer a small shared component, a small shared prompt contract, and existing `PromptService` templates.
- Preserve specialized chapter behavior where it is materially different: stream results, generate title/summary, rewrite full text, and edit selected text can stay chapter-specific, but should still reuse shared result/requirement UI where practical.
- Ordinary field polish/assist should support two modes:
  - `polish`: current field has text; improve expression without changing facts.
  - `complete`: field is empty; use surrounding project/import context to fill only that field.
- Text shown to users should be consistent:
  - entry label: `AI辅助` for field-level assist, `润色` only when the action is explicitly polish-only.
  - request modal: `${label} AI处理要求`
  - result modal: `${label} AI结果`
  - result copy: confirmation required before writing back.
- Backend prompt contract should be centralized:
  - `/api/polish` with an instruction must still use a template-managed wrapper, not raw frontend prompt + source concatenation.
  - add/register a minimal template for instruction-based field editing instead of scattering default instruction text across pages.
  - background outline/character/organization optimization already uses `OUTLINE_OPTIMIZE`, `CHARACTER_OPTIMIZE`, `ORGANIZATION_OPTIMIZE`; single-character/single-organization optimization should not maintain separate hardcoded frontend JSON prompt contracts.

Issues to fix in this loop:
1. `WorldSetting.tsx` and `Outline.tsx` duplicate near-identical `PolishableTextArea` implementations.
2. `ProjectWizardNew.tsx` and `BookImport.tsx` duplicate near-identical field AI assist implementations, while BookImport shows less context in the result modal.
3. Many field assist calls pass default instructions from the frontend, causing `/api/polish` to bypass `AI_DENOISING` and any template-managed prompt contract.
4. Single character/organization optimization still sends hardcoded JSON instructions from the frontend instead of using backend/template-managed optimize flows.
5. Selected chapter text editing includes broad chapter context; keep behavior for now, but do not expand it further.

Implementation order:
1. Add shared frontend field AI components/helpers.
2. Replace WorldSetting/Outline duplicated polish textareas.
3. Replace ProjectWizardNew/BookImport duplicated AI field buttons.
4. Add backend template-managed wrapper for instruction-based polish calls and register/test it.
5. Route single character/organization optimization through backend template-managed endpoints or a shared backend helper.
6. Run typecheck/build and targeted backend checks after each meaningful slice.

Completed in this loop:
1. Added shared `frontend/src/components/AIFieldAssistant.tsx` with:
   - `PolishableTextArea`
   - `AIFieldAssistButton`
   - `confirmAIFieldResult`
   - `buildDefaultAIFieldInstruction`
2. Replaced duplicated polish textareas in `WorldSetting.tsx` and `Outline.tsx`.
3. Replaced duplicated field AI assist flows in `ProjectWizardNew.tsx` and `BookImport.tsx`.
4. Added template-managed `AI_INSTRUCTION_EDIT`; `/api/polish` and `/api/polish/stream` now wrap custom/default instructions through `PromptService` instead of raw concatenation.
5. Added `/api/polish/character-settings` for single character/organization optimize preview; `Characters.tsx` and `Organizations.tsx` now use backend template-managed optimize contracts.
6. Expanded `ORGANIZATION_OPTIMIZE` to include `location`, `color`, and `power_level`, and updated background parsing to persist those fields when returned.

Verified in this loop:
- `python3 -m compileall -q backend/app backend/tests`
- `PYTHONPATH=backend python3 -c "...PromptService registry check..."`
- `npm --prefix frontend run build`
- `git diff --check`
