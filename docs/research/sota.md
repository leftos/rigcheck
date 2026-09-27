# State of the art outside vendor guidance: writing and validating the coding-agent instruction layer

Compiled 2026-09-27 for the rigcheck rule study. Scope: CLAUDE.md, AGENTS.md, rules files, skills, subagent definitions, hooks, memory files. Excludes Anthropic's own docs/blog and the reporails/rules and reporails/recommended rule packs (covered elsewhere). Every source below was fetched on 2026-09-27; arXiv dates come from the arXiv API (`published` = v1 date). Quotes are verbatim from the fetched text; numbers that the HTML render dropped (LaTeX) are marked as such rather than filled in from memory.

**Evidence grades.** A = controlled experiment, reproducible, on a model generation still in use (2025-H2 or later). B = observational or corpus study with a stated method, or a controlled study with a serious limit (single model, tiny n, older generation, unreplicated). C = practitioner experience or anecdote, or an experiment whose model, data or n is not published. D = unsourced, marketing, circular, or misquoted.

**Lintable column.** M = mechanically checkable (parse, count, resolve, regex). J = needs LLM judgment. N = not a file property (process, eval, or runtime behaviour); belongs in an eval harness, not a linter.

## Summary table

| # | Claim | Grade | Lintable? | Verdict for rigcheck |
|---|---|---|---|---|
| 1 | Context files (AGENTS.md/CLAUDE.md) do not, on average, raise task success; they raise cost ~20% | A | N | Holds on SWE-bench-style Python tasks, 2025-H2 models. Do not claim a file "improves success"; a linter can only target defects and cost |
| 2 | Agents do follow what context files say (tool mentions change tool use ~100x) | A | N (motivates M rules) | Holds. Consequence: a stale or wrong command in the file is followed. Strongest evidential basis for "referenced path/command must exist" rules |
| 3 | LLM-generated context files (e.g. `/init`) are mostly redundant with existing docs and slightly hurt | A | J (redundancy) | Holds on the tested repos; they help when docs are removed. Candidate rule: flag overview sections duplicating README (heuristic, low severity) |
| 4 | File size (25-500 lines), instruction position, split across files, and a contradicting instruction do not change adherence | A (one trivial marker instruction, Claude 4.6 models) | M for size/position, but no rule justified | Null result with Bayes-factor support for size and conflict. Undercuts "position decay" and hard line-count limits as error-level rules |
| 5 | Adherence decays within a session as the agent writes more code (OR 0.944 per function) | A (post-hoc) | N | Runtime property; argues for hooks over prose for must-happen rules, not for a file lint |
| 6 | Instruction-following degrades with instruction count ("curse of instructions", IFScale) | A on 2024-25 models; superseded for 2026 frontier on the IFScale task | M (count) but threshold unsupported | Real on older/smaller models and keyword-inclusion tasks; a 2026 replication shows saturation to thousands of keywords for GPT-5.5. No evidence for any specific budget (150, 200) for coding-agent rules |
| 7 | "Frontier models reliably follow ~150-200 instructions" | C (misapplied) | M count, threshold is folklore | Traces to IFScale's keyword-inclusion curves; not a behavioural-rule budget. Do not encode as a threshold |
| 8 | Rule count 0-50 does not change SWE-bench pass rate; random rules help as much as curated | A (Opus 4.6, 58 tasks) | N | Holds in that setting; implies content "quality scores" are unlikely to predict task success |
| 9 | Negative constraints help, positive directives hurt ("guardrails beat guidance") | B (suggestive; 3 vs 4 rules, not significant after correction) | M (polarity detection) but do not encode | Directly contradicts the popular "prefer positive phrasing" rule. Neither direction is established; lint neither |
| 10 | Naming a forbidden token primes the model to emit it | A mechanistic, small open model (Qwen2) | J | Plausible for word-avoidance; not shown for coding-agent rules. Folklore-adjacent for rigcheck |
| 11 | Negated instructions are followed about as well as positive ones by current models | C (2023, 10 prompts) | none | Weak but consistent with #9. The "never use negatives" rule is not supported |
| 12 | ALL-CAPS / IMPORTANT / MUST improve compliance | C for effect (+2-3%, n=10/model); A that caps shifts attention but not accuracy | M (count emphasis) | Effect small or absent on 2025-26 models; reasoning models buffer it. At most an info-level "emphasis density" note, not an error |
| 13 | Specific instructions (naming `unittest.mock`) are followed ~10x more than category words | C (vendor, model and data unpublished) | M-ish (backtick/code-token heuristic) | Untraceable experiment. Partial support from #2 (named tools get used). Acceptable as info-level hint, not as a scored rule |
| 14 | Lost in the middle: mid-context information is used worst | A on 2023 models; B for today | M (position) but unjustified | Recent work: bias shifts toward recency as input nears the window; #4 found no position effect in a 250-line CLAUDE.md. Do not encode |
| 15 | Context rot: performance falls as input length grows, even on simple tasks | A- (vendor tech report, 18 models, 2025) | M (token count) | Real for long inputs (10k-100k+). Instruction files are small relative to that; supports a token-budget warning, not a line cap |
| 16 | Curated skills raise pass rate (+16.6 pp over 18 configs); self-generated skills do not help | A | N | Holds. Supports "skills are worth validating"; says nothing about which lint rules matter |
| 17 | Compact/focused skills beat comprehensive ones | B (Comprehensive bucket = 5 tasks, confounded with task) | M (size) | Directional only. A soft size warning is defensible; a hard cap is not |
| 18 | Skills often are not invoked (56% never invoked in Vercel's eval) | C (vendor, n and model unpublished) | M (description present/non-empty); J (description quality) | Plausible and consistent with skill-routing design; basis for frontmatter/description rules |
| 19 | 13-26% of marketplace skills carry security issues; scripts double the odds | B (scanner-based; precision 86.7%) but contested (0.52% after repo-context check) | M (secrets, `curl|sh`, broad tool grants) | Security lints are mechanically checkable and well motivated; false-positive rate is the open problem |
| 20 | Rules > examples for in-context learning of novel tasks | A (open-weight + GPT-5.4 ref; non-coding tasks) | none | Contradicts "examples beat rules" folklore; does not transfer cleanly to coding conventions. Do not lint |
| 21 | 30k-corpus: "90% of instructions don't name what they talk about", instruction quality falls with file count | D for "quality" (circular); B for descriptive counts | M (their rules) | Headline misstates its own data (66.5% abstract; 89.9% is repos with at least one). File-count claim is contradicted by the released stats file |
| 22 | Developers rarely write security/performance guidance in context files (14.8% / 14.5%) | B | N | Descriptive; not a lint target |
| 23 | Stale paths/commands in context files mislead agents | B (mechanism from #2) + C (tool authors) | M | Best-supported mechanical rule family; several tools already do it |
| 24 | Politeness, tipping, threats change results | A (null for tips/threats on GPQA/MMLU-Pro, 2025) | M | No effect on average; do not lint |

## 1. Empirical and academic work

### 1.1 Do context files help at all?

**Gloaguen, Mündler, Müller, Raychev, Vechev (ETH Zurich / SRI Lab), "Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?", arXiv 2602.11988, v1 2026-02-12.** https://arxiv.org/abs/2602.11988

- Claim: context files do not generally raise success and raise cost. Quote: "we find that providing context files does not generally improve task success rates, while increasing inference cost by over 20% on average."
- Method: SWE-bench Lite (300 tasks, LLM-generated files) plus a new CTXbench of 138 instances from 12 repos with developer-committed files; four agent/model pairs: "Claude Code [3] with Sonnet-4.5 [4], Codex [26] with GPT-5.2 and GPT-5.1 mini [32], and Qwen Code [28] with Qwen3-30b-coder"; one sample per instance ("We sample completions for each agent once").
- Developer vs generated: "developer-committed files outperform LLM-generated ones by a significant margin of 7% on average." Secondary coverage (InfoQ, 2026-03) reports LLM-generated at about -3% and developer-written at about +4% versus no file; InfoQ also misnames the model as "Claude 3.5 Sonnet" (the paper says Sonnet-4.5), so cite the paper, not InfoQ. https://www.infoq.com/news/2026/03/agents-context-file-value-review/
- Instructions are followed: "uv is used 1.6 times per instance on average when mentioned in the context files, compared to fewer than 0.01 times when it is not mentioned". "this result implies that the absence of improvements when using context files is not due to a lack of instruction-following capabilities."
- Redundancy: with all `.md`, examples and `docs/` removed, "LLM-generated context files not only consistently improve performance ... but also outperform developer-written ones across settings." (percentage lost in HTML render).
- Length: "We observe no clear dependency between the success rate or the per-instance cost and the context file length."
- Section ablation (overview, tooling, testing removed one at a time, GPT-5.2): "no category has a significant positive or negative effect on benchmark accuracy."
- Grade A. Recent models, two benchmarks, four harnesses, McNemar/permutation tests. Limits: Python only, single sample per instance, 12 repos in CTXbench, success measured by hidden tests (not convention adherence). No COI.
- Lint implications: (a) outcome "task success" is insensitive to file content, so a linter should not promise success gains; (b) agents act on what the file names, so wrong facts propagate: the strongest argument for M rules on referenced paths, commands and tools; (c) "repository overview" sections duplicated from README add cost without benefit (J/heuristic).

**Lulla, Mohsenimofidi, Galster, Zhang, Baltes, Treude, "On the Impact of AGENTS.md Files on the Efficiency of AI Coding Agents", arXiv 2601.20404, v1 2026-01-28.** https://arxiv.org/abs/2601.20404

- Claim: AGENTS.md lowers runtime and output tokens. Quote: "the presence of AGENTS.md is associated with a lower median runtime (Δ28.64%) and reduced output token consumption (Δ16.58%), while maintaining a comparable task completion behavior."
- Method: 10 repos, 124 PRs, paired with/without, one agent: "the latest available Codex model was gpt-5.2-codex ... which we use consistently across all experiments."
- Grade B (paired, but one agent/model, efficiency only; direction on cost conflicts with Gloaguen's +20%, plausibly because Gloaguen counts reasoning/tool steps on SWE-bench and Lulla measures wall-clock on the repos' own PRs). Not lintable.

**Khatri, "Do Context Files Help Coding Agents? A Two-Agent Ablation Study on Real Repositories", arXiv 2607.27250, v1 2026-07-28.** https://arxiv.org/abs/2607.27250

- Claim: injection strategy (none, always-on, selective retrieval) does not move correctness. Quote: "Context strategy does not measurably move correctness on either agent (bounded to <=10-15pp via equivalence testing)." and "agents fail on implementation skill---feature design, pattern selection, exact wiring---not missing repository knowledge that a context file could supply".
- Models: `claude-sonnet-4-6` via `claude --print --bare`, `gpt-5.5` via `codex exec`. 17 tasks, 288 runs.
- Grade A for the bounded null, with small n (the equivalence bound is wide). Offers an explanation for contradictory prior results: "borderline task difficulty is agent-specific (Spearman rho=0.75)". Not lintable.

**Zhang et al., "Guardrails Beat Guidance: A Large-Scale Study of Rules, Skills, and Persistent Configuration for Coding Agents", arXiv 2604.11088, v1 2026-04-13.** https://arxiv.org/abs/2604.11088

- Claim 1 (content independence): "Random rules improve a coding agent's task performance as much as expert-curated ones". "random rules tie with curated rules at 63.8%"; baseline 50.0%; "no condition is significantly different from any other".
- Claim 2 (count): "pass rates remain stable across rule counts from 0 to 50." "The dominant source of variance is which rules are sampled (seed variance up to 17pp ...), not how many."
- Claim 3 (polarity): "all three shaping rules are negative constraints ('do not X'), while all four distorting rules are positive directives ('do X')." The authors qualify it: the top rule "is the only individually significant comparison and would not survive a strict multiple-comparison correction across all 18 rules", and "we treat it as suggestive evidence motivating cross-agent replication".
- Method: 679 scraped rule files (25,532 rules), >5,000 runs of Claude Code with Claude Opus 4.6 on SWE-bench Verified, but only on "58 discriminative tasks (those solved 1 or 2 out of 3 times)"; polarity analysis on 35 tasks and 18 hand-written rules.
- Grade: A for claims 1-2 (single model/benchmark), B for claim 3. Caveat the authors give: SWE-bench rewards minimal patches, so "do not refactor unrelated code" is favoured by the metric itself.
- Lint implications: rule-count caps and "quality" rewrites have no demonstrated effect on task success in this setting. The polarity result is the opposite of the common "tell it what to do, not what not to do" rule, so rigcheck should encode neither direction.

**McMillan (HxAI Australia), "Instruction Adherence in Coding Agent Configuration Files: A Factorial Study of Four File-Structure Variables", arXiv 2605.10039, v1 2026-05-11.** https://arxiv.org/abs/2605.10039

- Claim: size, position, file split, and a contradicting instruction in AGENTS.md do not change adherence. Quote: "None of the four structural variables or three two-way interactions in the design produces a detectable contrast after multiple-testing correction. The size and conflict nulls are supported by affirmative-null Bayes factors (BF10 between 0.05 and 0.10); the position and architecture nulls are failures to reject without Bayes-factor support."
- Design: 1,650 Claude Code CLI sessions, 16,050 function-level observations; sizes 25/100/250/500 lines; positions at lines 2/63/128/187/250 of a 250-line file; primarily Sonnet 4.6, cross-checked on Opus 4.6; 50 runs per cell; power ≥98% for a 15 pp shift. DV: agent must start each function with `// @tracked`, scored by AST.
- Within-session decay: "each additional function the agent generates within a session is associated with approximately 5.6% lower odds of compliance per generation step (OR = 0.944)"; "identified during analysis rather than pre-specified". Task identity mattered more: a 26.2 pp gap between two tasks.
- Grade A for the nulls within scope, B for the post-hoc decay. Limit, stated by the author: a trivial always-applicable marker; "transfer of the absolute compliance rate to other instruction classes is an open question". Single author, preprint.
- Lint implications: removes the empirical basis for error-level rules on line count (up to 500), "instruction buried in the middle", and even for treating a cross-file contradiction as a compliance hazard (still worth flagging as a maintenance defect, M/J). The decay finding argues for moving must-happen checks into hooks, which is a design recommendation, not a file lint.

**Arize, "CLAUDE.md best practices learned from optimizing Claude Code with prompt learning", 2025-11-20.** https://arize.com/blog/claude-md-best-practices-learned-from-optimizing-claude-code-with-prompt-learning/

- Claim: optimized rules raise SWE-bench Lite accuracy "by 5.19%" (cross-repo split) and "+10.87%" (Django temporal split), Sonnet 4.5.
- Grade C. Vendor selling the optimizer; the Django test split is small (the repo README notes "Django has ~23 instances in SWE-bench Lite" in one config while the blog says 114), single runs, no variance reported, and loop selection appears to use test accuracy. Conflicts with Zhang (random rules match curated) and Gloaguen. Not lintable.

### 1.2 Instruction count and density

**Harada et al., "When Instructions Multiply: Measuring and Estimating LLM Capabilities of Multiple Instructions Following" (ManyIFEval / StyleMBPP; earlier OpenReview title "Curse of Instructions"), EMNLP Findings 2025.** https://aclanthology.org/2025.findings-emnlp.896.pdf

- Claim: "performance consistently degrades as the number of instructions increases"; "a logistic regression model using instruction count as an explanatory variable can predict performance ... with approximately 10% error".
- Scale: up to 10 instructions (text) and up to 6 (code); models GPT-4o, Claude 3.5 Sonnet, Gemini 1.5 Pro, o3-mini, Llama 3.1 8B, Gemma2, Qwen2.5 72B, DeepSeek-V3/R1.
- The popular "P(all) = P(one)^n" formula circulates via secondary summaries (e.g. maxpool.dev); the ACL version frames it as a fitted logistic model. Cite the ACL paper, not the summary.
- Grade A for 2024-25 models and prompt-level "all instructions satisfied" at n ≤ 10. Applicability to 2026 agents: unknown; models are two generations old.

**Jaroslawicz, Whiting, Shah, Maamari (Distyl AI), "How Many Instructions Can LLMs Follow at Once?" (IFScale), arXiv 2507.11538, v1 2025-07-15.** https://arxiv.org/abs/2507.11538

- Claim: "even the best frontier models only achieve 68% accuracy at the max density of 500 instructions". Three curves: "threshold decay ... (reasoning models like o3, gemini-2.5-pro), (2) linear decay (gpt-4.1, claude-sonnet-4), and (3) exponential decay (gpt-4o, llama-4-scout)". Primacy: "Nearly all models exhibit mid-range peaks around 150-200 instructions where selective attention mechanisms favor earlier instructions".
- Task: each instruction is "Include the exact word: '{keyword}'" in a business report. Not behavioural rules.
- Grade A for its task and 2025 models. Transfer to coding-agent rules is not shown.

**Arize-ai/instruction-budget, "IFSCALE_REPLICATION.md", repo created 2026-05-08.** https://github.com/Arize-ai/instruction-budget/blob/main/IFSCALE_REPLICATION.md

- Claim: "The paper's headline is dead. GPT-5.5 hits 100% accuracy at N=5000 simultaneous instructions." Opus 4.7 "Decay starts at N=750 (drops to ~89%) and reaches 75-80% by N=2000", with a 20-50% refusal-classifier rate at densities ≥100 on the original vocabulary; DeepSeek V4 Pro shows the classic linear decay.
- Grade B. Raw results and scripts are in the repo (`results/raw/`, `results/aggregated/`), so it is checkable, but it is an unreviewed vendor write-up (Arize sells eval/observability), and the aggregation "takes the first 5 successes" after refusals/truncations, which biases accuracy upward.
- Implication: the "instruction budget" argument (claim #7) was already a transfer from a keyword task; on 2026 frontier models even that task has saturated. There is no current evidence for a numeric instruction cap.

### 1.3 Length, position, context rot

**Liu et al., "Lost in the Middle: How Language Models Use Long Contexts", arXiv 2307.03172, v1 2023-07-06 (TACL 2024).** https://arxiv.org/abs/2307.03172

- Claim: "performance is often highest when relevant information occurs at the beginning or end of the input context, and significantly degrades when models must access relevant information in the middle". Multi-document QA and key-value retrieval on 2023 models.
- Grade A for 2023 models; B as a statement about 2026 models.

**Veseli, Chibane, Toneva, Koller, "Positional Biases Shift as Inputs Approach Context Window Limits", arXiv 2508.07479, v1 2025-08-10.** https://arxiv.org/abs/2508.07479

- Claim: the LiM effect "is strongest when inputs occupy up to 50% of a model's context window. Beyond that, the primacy bias weakens, while recency bias remains relatively stable." Grade A. Retrieval tasks, not rule adherence.

**Hong, Troynikov, Huber (Chroma), "Context Rot: How Increasing Input Tokens Impacts LLM Performance", technical report, 2025-07-14.** https://www.trychroma.com/research/context-rot (code: https://github.com/chroma-core/context-rot)

- Claim: "we evaluate 18 LLMs, including the state-of-the-art GPT-4.1, Claude 4, Gemini 2.5, and Qwen3 models. Our results reveal that models do not use their context uniformly; instead, their performance grows increasingly unreliable as input length grows." Distractors and low needle-question similarity make it worse.
- Grade A- (controlled, open code, 2025 models) with COI: Chroma sells retrieval infrastructure, which benefits from "context engineering" framing. Not peer reviewed.
- Lint implication: supports a token-budget warning on always-loaded content (everything in CLAUDE.md, imported files, auto-memory index), because that content is paid on every turn and competes with task context. It does not support a specific line number; the files in question are small relative to the lengths tested.

**Coding-agent-specific evidence on position and length**: McMillan (above) found no position or size effect up to 500 lines; Gloaguen found no length/success correlation. These are the only controlled tests on real agent config files located. Both conflict with "keep instructions near the top" and "under N lines or it gets ignored" as hard rules.

### 1.4 Skills

**SkillsBench, arXiv 2602.12670, v1 2026-02-13, v4 2026-06-14.** https://arxiv.org/abs/2602.12670

- v4 claim: "Curated Skills raise the average pass rate from 33.9% to 50.5% (+16.6 percentage points; 25.5% normalized gain), with configuration-level gains ranging from +4.1 to +25.7 pp" across 18 model-harness configurations, 87 tasks.
- v1 abstract (7 configs) additionally said "16 of 84 tasks show negative deltas" and "Self-generated Skills provide no benefit on average". v4 moved self-generation to an appendix and strengthened it: "self-generated Skills land below the no-Skills baseline" on all three tested configurations, with the caveat that the deficit "mixes content quality with skill-discovery and creator/solver interference effects".
- Size claim: "compact and standard-length Skills (+19.0 and +21.5 pp) outperform detailed (+14.5 pp) and comprehensive documentation (+0.7 pp)". Table 9 shows the Comprehensive bucket has **5 tasks**, and length is not manipulated (different tasks have different skills), so this is observational and confounded. Grade B for the size claim, A for the headline.
- Failure modes worth encoding as advisory (J) rules: "Skills should include applicability boundaries, not just preferred procedures" and "authors should mark optional steps and supply a fast path."
- Corpus fact: across 767,425 cloned skills, "SKILL.md instructions ... have a median of 4.8 KB (1.2k tokens ...)".

**Vercel (Jude Gao), "AGENTS.md outperforms skills in our agent evals", 2026-01-27.** https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals

- Claim: "In 56% of eval cases, the skill was never invoked"; skill default 53% (= baseline), skill with explicit instruction 79%, compressed 8 KB docs index in AGENTS.md 100%. Wording sensitivity: "You MUST invoke the skill" anchored on docs and missed project context; "Explore project first, then invoke skill" did better.
- Grade C: vendor (the fix is a Next.js codemod), number of eval cases and model not stated, "retries to rule out model variance" not quantified. Useful hypothesis: skill routing is a failure point, and forceful wording can change behaviour in unintended ways.
- Misquote in the wild: agnix's README says Vercel found skills "invoke at 0%"; the post says the skill was not invoked in 56% of cases and gave +0 pp.

**Skill security studies (2026).**

- Liu et al., "Agent Skills in the Wild: An Empirical Study of Security Vulnerabilities at Scale", arXiv 2601.10338, 2026-01-15: "26.1% of skills contain at least one vulnerability"; "skills bundling executable scripts are 2.12x more likely to contain vulnerabilities than instruction-only skills (OR=2.12, p<0.001)"; detector "86.7% precision and 82.5% recall". Grade B (scanner plus LLM classification). https://arxiv.org/abs/2601.10338
- "Do Not Mention This to the User", arXiv 2602.06547, 2026-02-06: 98,380 skills, "157 skills exhibiting confirmed malicious behavior"; "Over half of all confirmed cases originate from a single threat actor". Grade B. https://arxiv.org/abs/2602.06547
- "How Your Credentials Are Leaked by LLM Agent Skills", arXiv 2604.03070, 2026-04-03: "debug logging accounts for 73.5% of vulnerabilities because agent frameworks feed stdout into the LLM context window". Grade B. https://arxiv.org/abs/2604.03070
- Counterpoint, "Context Matters: Repository-Aware Security Analysis of the Agent Skill Ecosystem", arXiv 2603.16572, 2026-03-17: marketplace scanners "classify up to 46.8% of skills as malicious", but "only 0.52% remain suspicious after repository-aware analysis". Grade B. https://arxiv.org/abs/2603.16572
- Lint implications (M): secrets in SKILL.md/scripts/memory; `curl ... | sh`; scripts that print environment variables or tokens; broad tool grants (`Bash(*)`); references to abandoned remote sources. Expect false positives; severity should be warning unless the pattern is unambiguous (literal key formats).

### 1.5 Emphasis, ALL-CAPS, framing

- **"Attention is Case-Sensitive", arXiv 2608.03711, 2026-08-04.** Uppercase spans concentrate attention in all evaluated non-reasoning models, but "increased concentration does not inherently improve task accuracy and, in high-entropy contexts like alternating case, can degrade it"; "the deliberative 'thinking' phase in reasoning models acts as a semantic buffer that mitigates typographic sensitivity". Grade A for the attention finding; accuracy effect null-to-negative. https://arxiv.org/abs/2608.03711
- **S. Anand, "Shouting at LLMs", 2025-06-11.** Caps gave "~2-3%" more obedience in a system-override test; the author notes "This is a sample size of 10 per model" and "The effect is weak". Grade C. http://www.s-anand.net/blog/shouting-at-llms/
- **"Control Illusion: The Failure of Instruction Hierarchies in Large Language Models", arXiv 2502.15851, v1 2025-02-21 (v4 2025-12-04).** "societal hierarchy framings (e.g., authority, expertise, consensus) show stronger influence on model behavior than system/user roles". Grade A (six 2025 models). https://arxiv.org/abs/2502.15851
- **"Measuring Pragmatic Influence in Large Language Model Instructions", arXiv 2602.21223, v1 2026-02-02.** Framing like "This is urgent" "produces systematic shifts in directive prioritization"; five open-weight models only. Grade B for frontier transfer. https://arxiv.org/abs/2602.21223
- **Meincke et al., "Prompting Science Report 3: I'll pay you or I'll kill you", arXiv 2508.00614, 2025-08-01.** "Threatening or tipping a model generally has no significant effect on benchmark performance." Grade A (GPQA, MMLU-Pro). https://arxiv.org/abs/2508.00614
- **Hyground, "Stop Shouting at Your LLM", 2026-03-18** ("emphasis saturation": as prompts accumulate IMPORTANT/CRITICAL markers, priority order becomes unclear). Grade C; plausible design argument, no measurement. https://hyground.ai/blog/stop-shouting
- Net for rigcheck: no evidence that emphasis raises compliance on 2025-26 reasoning models; weak evidence it can distort behaviour (Vercel's "You MUST invoke" anecdote). An info-level "emphasis density" metric (count of all-caps words, IMPORTANT/MUST/NEVER per 100 lines) is mechanically trivial and harmless as information; an error-level rule is not justified.

### 1.6 Positive versus negative phrasing

- **Zhang et al. 2604.11088** (above): the beneficial rules were all negative, the harmful ones all positive; suggestive, not significant after correction. Grade B.
- **"Semantic Gravity Wells: Why Negative Constraints Backfire", arXiv 2601.08070, 2026-01-12.** For "do not use word X" constraints, "In priming failure (87.5% of violations), the instruction's explicit mention of the forbidden word paradoxically activates rather than suppresses the target representation." Mechanistic work on Qwen2-family and GPT-2 small models. Grade A for mechanism on small open models; transfer to frontier coding agents not shown. https://arxiv.org/abs/2601.08070
- **Bleakley, "Saying what not to do", 2023-09-26.** 10 hand-built positive/negative instruction pairs: "state-of-the-art language models typically achieve similar results in each case"; "prompt engineers need not apply a blanket rule of avoiding negation". Grade C (2023 models, tiny n). https://alexbleakley.com/blog/saying-what-not-to-do
- **Jang et al., "Can Large Language Models Truly Understand Prompts? A Case Study with Negated Prompts", PMLR v203 (2022-23).** Inverse scaling on negated prompts for OPT/GPT-3/InstructGPT. Grade A for those models; obsolete generation. https://proceedings.mlr.press/v203/jang23a/jang23a.pdf
- Net: the evidence points in both directions depending on task (word avoidance vs scope restraint) and model generation. rigcheck should not encode "negative without positive" or "prefer negative" as rules. agnix's CC-MEM-006 "Negative Without Positive" (severity HIGH) cites only arXiv 2201.11903, which is the chain-of-thought prompting paper and does not address negation (see section 3).

### 1.7 Examples versus rules

- **Fu, Cho, Lee, Kim, "LLMs Learn Better In-Context from Rules than from Examples", arXiv 2609.03213, 2026-09-02.** "models generally learn more reliably from rules than from examples alone, and additional examples on top of rules or simply scaling up the number of examples do not lead to consistent and significant gains." Open-weight OLMo/Qwen models plus GPT-5.4 as reference; tasks are games, arithmetic, linguistic inference, not coding. Grade A in scope. https://arxiv.org/abs/2609.03213
- **dev.to, "Less Is More: Why 3 Code Examples Beat 10 Rules", 2026-06-06.** One task, one run; both variants passed 26/26 tests; the "win" is 15% shorter code. Grade C. https://dev.to/zxpmail/less-is-more-why-3-code-examples-beat-10-rules-for-llm-code-generation-3n08
- **aictrl-dev/skill-md-research (2026-02-21)**: pseudocode-format skills beat markdown on rule compliance across 6 domains; small repo, no paper. Grade C. https://github.com/aictrl-dev/skill-md-research
- **HumanLayer's counter-advice** "Prefer pointers to copies. Don't include code snippets ... they will become out-of-date quickly" is a maintenance argument (C), and is the one part that is mechanically checkable: a code block in an instruction file that no longer matches the referenced source.
- Net: no lint rule on "has examples" or "has no examples".

### 1.8 Specificity (naming constructs)

- Reporails' claim: "In previous controlled experiments, specificity produced a 10.9x odds ratio in compliance (N=1000, p<10⁻³⁰)" (dev.to, 2026-04-21). The source post (Mészáros, "Precision Beats Clarity", Medium, 2026-03-24) says only "same model, same context window ... Over a thousand runs per finding"; the model, task, prompts and data are not published. Grade C, vendor COI (Reporails sells the linter that scores specificity). https://cleverhoods.medium.com/instruction-best-practices-precision-beats-clarity-e1bcae806671
- Independent partial support: Gloaguen's tool-mention result (agents use `uv` only when the file names it). That shows named commands get used, not that abstract phrasing is ignored. Grade A for the narrower claim.
- Net: a "names no concrete construct" heuristic (no backticked token, path, command, or flag in an imperative sentence) is mechanically cheap and defensible as info-level. Scoring files by it, or calling abstract lines "vague instructions" at error severity, overstates the evidence.

## 2. Datasets and corpus analyses

| Study | Date | Corpus | Key descriptive finding | Grade |
|---|---|---|---|---|
| Chatlatanagulchai et al., "On the Use of Agentic Coding Manifests: An Empirical Study of Claude Code", arXiv 2509.14744 | 2025-09-18 | 253 CLAUDE.md from 242 repos | "manifests typically have shallow hierarchies with one main heading and several subsections, with content dominated by operational commands, technical implementation notes, and high-level architecture" | B |
| Chatlatanagulchai et al., "Agent READMEs: An Empirical Study of Context Files for Agentic Coding", arXiv 2511.12884 | 2025-11-17 | 2,303 files, 1,925 repos | Files "evolve like configuration code through frequent, small additions"; median length Copilot 535 words, Claude Code 485, Codex 335.5; "security (14.8%) and performance (14.5%) are rarely specified" | B |
| Jiang & Nam, "Beyond the Prompt: An Empirical Study of Cursor Rules", arXiv 2512.18925 | 2025-12-21 | 401 repos, qualitative | Taxonomy: "Conventions, Guidelines, Project Information, LLM Directives, and Examples" | B |
| Galster et al., "Harness Engineering for Agentic AI Coding Tools", arXiv 2602.14690 | 2026-02-16 | 2,853 repos | "Context Files dominate ... often the sole mechanism"; "few repositories adopt advanced mechanisms such as Skills and Subagents"; "Skills predominantly rely on static instructions rather than executable scripts" | B |
| Sun et al., "A Study of Cursorrules Files in GitHub Open Source Projects", arXiv 2608.10622 | 2026-08-11 | 12,110 .cursorrules, 11,427 repos; 65-file qualitative sample | Adoption "concentrated in small-scale, low-activity, single-maintainer repositories, suggesting toy projects" | B |
| Reporails, "The State of AI Instruction Quality" + reporails/30k-corpus | 2026-04-21 | 28,721 repos, 165,063 files | See critique below | B descriptive / D quality |

None of these corpus studies links a file property to an outcome (adherence or success). They describe what exists; they cannot say what is good. Corpus prevalence is useful for rigcheck in one way only: estimating how noisy a rule will be in the wild.

### 2.1 reporails/30k-corpus: methodology examined

Sources: https://github.com/reporails/30k-corpus (created 2026-04-21, 7 stars, license NOASSERTION), https://dev.to/reporails/the-state-of-ai-instruction-quality-35mn (2026-04-21), the earlier partial-sample post https://dev.to/reporails/the-undiagnosed-input-problem-4pmc (2026-04-08), and `stats_public.json` (`_timestamp` 2026-04-15) downloaded 2026-09-27.

- **Sampling.** "GitHub REST API search ... Collected March-April 2026". Public repos, English-skewed, no popularity weighting; the authors list these limits themselves ("This is not a random sample"; "A 10-star hobby project counts the same as a 50K-star production repo"). Sun et al. 2608.10622 independently find such files concentrated in toy projects, so the population is skewed toward low-effort files.
- **Unit of analysis.** Markdown split into "atoms"; "A heading is one atom. A bullet point is one atom. A paragraph is one atom." A paragraph with five instructions is one atom, so "instructions" counts and the "27% of your file is instructions" figure depend on formatting, not content.
- **Classifier.** "Three-phase deterministic pipeline (negation detection, modal auxiliary detection, syntactic dependency parsing). No LLM." Specificity "uses backtick/code-token patterns". The published `validation_key.csv` (2,814 rows) contains only the tool's own labels (`tool_charge`, `tool_modality`, `tool_specificity`); there is no human label column, so classifier accuracy is not measured anywhere. Deterministic is not the same as correct. Example rows: id 1 "Use non_blocking=True -- Make transfers async ..." is labelled CONSTRAINT; id 6 "... Re-stage (git add) and commit again." is labelled NEUTRAL.
- **Circular quality.** The "quality score" and LOW/MODERATE/HIGH bands are computed from Reporails' own rules (top rules by count in `stats_public.json`: `CORE:C:0042` "Vague (no named constructs)", `CORE:C:0047` "Position decay (buried instruction)", `CORE:E:0004` "Terse (too few tokens)"). The article's claim "The models are fine ... What if the instructions are the problem?" is therefore a restatement of the rule set, not a finding. No outcome variable (agent behaviour, task success) exists in the dataset. The site's "8.8M diagnostic runs replayed" are linter runs, not agent runs.
- **Headline versus data.** Section title "90% of instructions don't name what they're talking about"; the body says "Two-thirds of all instructions are abstract"; `stats_public.json` has `abstract_pct: 66.5` and `pct_repos: 89.9` for repos with at least one abstract instruction. The 90% is a repo-level figure presented as an instruction-level one.
- **Stability claim versus data.** The April 8 post reported "bottom tier: 40.3%" on 12,076 repos and, by file count, top-tier share falling "from 16.9% in single-file setups to 5.4% in repositories with 51 to 500 instruction files". The April 21 article says "The final 28,721-repo corpus moved nothing." The released `stats_public.json` shows global LOW 21.4% and, by file count, HIGH 31.2% for 1 file versus 43.4% for 51+ files, the opposite direction. Tier definitions may have changed between posts, but nothing published reconciles them; treat the file-count claim as unsupported.
- **Conflict with controlled work.** Rule `CORE:C:0047` "Position decay (buried instruction)" fires in 87.3% of repos; McMillan's factorial test found no position effect in a 250-line CLAUDE.md for Sonnet 4.6/Opus 4.6.
- **What is reusable.** File-name frequencies (`agents.md` 17,335, `claude.md` 10,642, `CLAUDE.md` 3,372, `.github/copilot-instructions.md` 5,647), multi-agent co-occurrence (37% configure 2+ agents; Claude+Codex 5,038), config-type counts, and the observation that shared skills and subagent persona files name fewer concrete constructs. These are descriptive, B grade, and useful for estimating rule prevalence.
- **COI.** The dataset is marketing for a BUSL-1.1 source-available CLI (`npx @reporails/cli`, 210 npm downloads 2026-08-28..2026-09-26).

## 3. Prior-art tools

Metadata from the GitHub API and npm downloads API on 2026-09-27. "Last push" is `pushed_at`. Stars and downloads are adoption proxies only.

| Tool | Scope | What it checks | Evidence claims | Adoption | License | Maintenance |
|---|---|---|---|---|---|---|
| [agent-sh/agnix](https://github.com/agent-sh/agnix) (Rust; npm/pip/cargo; LSP + IDE plugins) | CLAUDE.md, AGENTS.md, SKILL.md, hooks, MCP, Cursor, Copilot, Codex, Kiro, Gemini | "457 rules" (README; 454 in an earlier snapshot): schema/frontmatter, naming, hooks, MCP, plus prompt-style rules (generic instruction, weak imperative, negative without positive), autofix | Claims rules "sourced from official specs, academic research". Spot check: PE-002, PE-003, CC-MEM-005/006/007 list https://arxiv.org/abs/2201.11903 (Wei et al., chain-of-thought) as evidence, which does not address generic instructions, negation or weak modals. Misquotes Vercel ("invoke at 0%") | ★425; npm `agnix` 37,461/month | Apache-2.0 / MIT | Very active (push 2026-09-27) |
| [pdugan20/claudelint](https://github.com/pdugan20/claudelint) (npm `claude-code-lint`) | Claude Code project | CLAUDE.md size limits, import syntax, circular refs; skills frontmatter/structure/referenced files/security; settings JSON schema, permissions, tool names; hooks event names, script existence; MCP; plugins | Spec-based | ★12; npm 21,071/month | MIT | Active (2026-09-26) |
| [carlrannaberg/cclint](https://github.com/carlrannaberg/cclint) (npm `@carlrannaberg/cclint`) | Claude Code | Agent/subagent and command frontmatter (Zod schemas), settings.json hook structure, unknown hook events/tools; custom schemas | Spec-based | ★22; npm 6,788/month | none declared | Stale (push 2025-09-10) |
| [felixgeelhaar/cclint](https://github.com/felixgeelhaar/cclint) | CLAUDE.md, AGENTS.md, skills, subagents, hooks, MCP | `@path` import resolution and cycles, stale model IDs, monorepo hierarchy, command safety, skill/subagent structure, "vague language detection", "Emphasis markers (IMPORTANT, YOU MUST)" | Style rules unsourced | ★12 | MIT | Active (2026-09-21) |
| [dotcommander/cclint](https://github.com/dotcommander/cclint) (Go) | agents, commands, skills, settings | CUE-schema frontmatter; settings hooks, permissions, MCP, security | Spec-based | ★17 | MIT | Active (2026-09-18) |
| [giacomo/agents-lint](https://github.com/giacomo/agents-lint) (npm `agents-lint`) | AGENTS.md, CLAUDE.md, Claude auto-memory | Paths that no longer exist, framework/dependency staleness, cross-file path asymmetry, memory frontmatter | Misquotes Gloaguen as "ICSE 2026" and "2-3%" | ★15; npm 2,428/month | none declared | Active (2026-09-25) |
| [midori-profile/claudelint](https://github.com/midori-profile/claudelint) | CLAUDE.md, memory, settings hooks, skills | `stale-path`, `dead-script` (npm script gone), `broken-hook`, `secret-in-memory`, `stale-symbol` (backticked identifier not in codebase), `oversized-memory`, `invalid-skill`; suggests running as SessionStart hook | Author reports tuning path heuristics against own files to cut false positives | ★2 | MIT | New (2026-08) |
| [openintelligence-labs/agents-md-lint](https://github.com/openintelligence-labs/agents-md-lint) (Python) | CLAUDE.md, AGENTS.md | Backticked paths exist (with move suggestions), commands resolvable on PATH; "Commands are resolved, never run" | None beyond mechanism | ★0 | MIT | 2026-08 |
| [bitflight-devops/skilllint](https://github.com/bitflight-devops/agentskills-linter) (pip `skilllint`) | plugins, skills, agents, commands, Cursor .mdc | Frontmatter schema (FM*), skill description/token limits/internal links (SK*), hook script existence (HK*), agent tool wildcards and MCP refs (AG*), token counting | Token threshold 8192 is a chosen default | ★7 | MIT | Active (2026-09-27) |
| [xyiqq/skilldoctor](https://github.com/xyiqq/skilldoctor) | SKILL.md | name/description, dir match, YAML, "500-line budget", broken references/scripts/assets links; audit for prompt injection, secrets, credential paths, `Bash(*)`, `curl | sh`; cross-tool frontmatter compatibility | Spec-based + security heuristics | ★12 | MIT | 2026-08 |
| [retif/claudecode-linter](https://github.com/retif/claudecode-linter) | plugin.json, SKILL.md, agent/command md, hooks.json, mcp.json, settings.json, CLAUDE.md | Schema + formatter/fixer; static only, runs sandboxed | Spec-based | ★3 | MIT | Active (2026-09-25) |
| [stbenjam/claudelint](https://github.com/stbenjam/claudelint) | Claude marketplaces and plugins | Plugin/marketplace structure | Spec-based | ★7 | Apache-2.0 | Archived |
| [agentskills/agentskills](https://github.com/agentskills/agentskills) (`skills-ref validate`) | Agent Skills open spec | Reference validator for SKILL.md frontmatter and naming | Spec owner (Anthropic-originated open standard; out of scope beyond noting it exists) | ★25,736 | Apache-2.0 | 2026-08 |
| [reporails/cli](https://github.com/reporails/cli) (npm `@reporails/cli`) | Claude, Codex, Copilot, Cursor, Gemini | 97-120+ deterministic rules; charge/specificity classifier; 0-10 score (rule packs covered by the other agent) | Corpus-derived, circular (section 2.1) | ★88; npm 210/month | BUSL-1.1 (NOASSERTION on GitHub) | Last push 2026-06-27 |
| [Penloom-Studio/claude-md-lint](https://github.com/Penloom-Studio/claude-md-lint) | CLAUDE.md | "Instruction budget" count vs 150 soft budget, rules over 40 words, must-happen rules that should be hooks | "frontier models reliably hold roughly 150-200 instructions"; "rules land ~80% of the time as prose, but a deterministic hook fires ~100%": no source; sells a $17 pack | ★0 | MIT | 2026-07 |
| [dyoshikawa/rulesync](https://github.com/dyoshikawa/rulesync) | Cross-tool rule sync | Generates per-tool files from one source (not a linter, but the main cross-tool consistency tool) | n/a | ★1,478 | MIT | Very active |

Observations for rigcheck:

- Two families exist. **Schema/reference checkers** (frontmatter, hook events, script existence, import resolution, stale paths/commands/symbols, secrets) are mechanical, evidence-light but defect-oriented, and the tools agree with each other. **Prose-style scorers** (vague, weak modal, emphasis, negative-without-positive, instruction budget, position) are where evidence citations are absent, misattributed, or circular.
- The best-motivated niche is **reference integrity**: Gloaguen shows agents act on named tools and commands, so a dangling path, renamed npm script, missing hook script, or deleted symbol is a defect that propagates. Four small tools do this, none with meaningful adoption.
- Hook validation beyond schema (does the command exist, is it executable on this OS, does the matcher name a real tool) is done by claudelint, skilllint and midori; none validate hook exit-code semantics.
- Nothing located checks cross-file contradictions mechanically; the tools that mention conflicts use LLM judgment or skip it. McMillan's null for adherence means a contradiction is a maintenance defect rather than a demonstrated compliance hazard.

## 4. Practitioner writing (hypotheses only)

- **HumanLayer (Kyle), "Writing a good CLAUDE.md", 2025-11-25.** https://www.humanlayer.dev/blog/writing-a-good-claude-md
  - "Frontier thinking LLMs can follow ~ 150-200 instructions with reasonable consistency." Traceable to IFScale's keyword-inclusion curves; the post itself says "the topic hasn't been investigated in an incredibly rigorous manner". Grade C as applied to rules; superseded on 2026 models by the Arize replication.
  - "As instruction count increases, instruction-following quality decreases uniformly ... it begins to ignore all of them uniformly". IFScale reports a primacy peak around 150-200 instructions and convergence to uniform failure only at extreme densities, so this is a partial reading.
  - "Claude Code's system prompt contains ~50 individual instructions." Own analysis, not reproducible from the post. Grade C.
  - "general consensus is that < 300 lines is best". No source. Grade D. McMillan tested up to 500 lines with no effect.
  - "Never send an LLM to do a linter's job" and "Prefer pointers to copies" (`file:line` references instead of snippets). Grade C, but the second yields a mechanical check (snippets that drift from source).
  - Also reports that Claude Code wraps CLAUDE.md in a reminder saying it "may or may not be relevant", captured via a logging proxy; a harness detail that may have changed since.
- **Vercel, 2026-01-27** (section 1.4). Hypotheses: passive context beats on-demand skills for general framework knowledge; forceful wording ("You MUST") can reorder agent behaviour badly. Grade C.
- **Arize prompt learning, 2025-11-20** (section 1.1). Hypothesis: repo-specific rules learned from past failures help. Grade C; conflicts with Zhang.
- **Simon Willison, "Claude Skills are awesome, maybe a bigger deal than MCP", 2025-10-16.** https://simonwillison.net/2025/Oct/16/claude-skills/ Argument is about token economy of progressive disclosure versus MCP tool definitions, not about writing quality. Grade C; no measurable claim to lint.
- **Hyground, 2026-03-18** (section 1.5): emphasis saturation. Grade C.
- **Mészáros/Reporails blog series** ("Precision Beats Clarity" 2026-03-24, "Do NOT Think of a Pink Elephant", "7 Formatting Rules for the Machine" 2026-03-03, "The Undiagnosed Input Problem" 2026-04-08): claims of "Instruction ordering moved compliance by 25 percentage points" and "roughly a 10x compliance effect" with unpublished models and data. Grade C, vendor COI.

## 5. Candidate rules that the evidence supports

Ordered by strength of support. Severity suggestions assume rigcheck's default is to avoid false authority.

1. **Referenced path does not exist** (backticked or link paths in CLAUDE.md/AGENTS.md/rules/skills/memory, and `@imports`). M. Basis: Gloaguen (agents follow named things), tool consensus. Error.
2. **Referenced command/script not resolvable** (npm/pnpm script names, Makefile targets, `just` recipes, executables in hooks). M. Same basis. Error for hooks, warning for prose.
3. **Hook configuration invalid** (unknown event, matcher naming a non-existent tool, missing or non-executable script, OS-incompatible shell). M. Basis: spec plus tool consensus. Error.
4. **Frontmatter schema** for skills, subagents, commands, rules (`name` format, `description` present and non-empty, directory/name match, unknown keys, model IDs). M. Basis: spec; Vercel/SkillsBench show routing and invocation are real failure points. Error for schema, warning for empty/very short descriptions.
5. **Secrets and dangerous patterns** in skills, scripts, memory (literal key formats, `curl|sh`, printing env/tokens, `Bash(*)`-style grants). M. Basis: skill security studies (B). Warning, error for literal credentials.
6. **Always-loaded token budget** (sum of CLAUDE.md + imports + auto-memory index + rules without path scoping), reported as a number with a configurable warning threshold. M. Basis: Gloaguen (+20% cost), context-rot (A-). Info/warning; no evidence for any universal threshold.
7. **Skill size** (SKILL.md tokens, bundle size) as a soft warning. M. Basis: SkillsBench (B, confounded). Info.
8. **Stale snippet** (fenced code in an instruction file whose referenced source changed). M with heuristics. Basis: practitioner (C) plus mechanism of #1. Info.
9. **Cross-file duplication/contradiction** (same rule restated differently across CLAUDE.md/AGENTS.md/rules). J for contradiction, M for exact/near duplicates. Basis: maintenance only; McMillan shows no adherence effect. Info.
10. **Overview duplicating README** (LLM-generated `/init`-style repo overview). J or similarity heuristic. Basis: Gloaguen (A). Info.

## 6. Folklore: do not encode

- **A numeric instruction budget (150, 200) or "instruction count" as a quality score.** Source is a keyword-inclusion benchmark on 2025 models; on 2026 frontier models the same benchmark saturates; Zhang found no pass-rate change from 0 to 50 rules.
- **Hard line caps ("under 300 lines or it gets ignored", "500-line SKILL.md budget" as an error).** No source for 300; McMillan found no adherence change from 25 to 500 lines; Gloaguen found no length/success correlation. A token-budget number is fine; a pass/fail cap is folklore.
- **"Instructions in the middle get lost" / "position decay".** From 2023 retrieval studies; McMillan found no position effect in config files; newer work shows the bias shifts with input length. Do not lint position.
- **"Tell it what to do, not what not to do" (flag negatives).** Contradicted by Zhang (negatives were the helpful rules) and Bleakley; supported only for word-avoidance priming on small models. Also do not encode the reverse.
- **"ALL-CAPS / IMPORTANT / MUST make rules stick."** Small or no effect on current models; reasoning models buffer typography. At most an info metric.
- **"Specific instructions are followed 10x more."** Untraceable experiment by a vendor. A "no concrete construct" hint is acceptable as info; do not score or fail on it.
- **"Examples beat rules" (or the reverse).** Controlled evidence favours rules on novel non-coding tasks; coding-convention evidence is anecdotal.
- **Corpus-derived "quality scores".** Any score defined by the scorer's own rules (reporails 30k) measures conformity to those rules, not agent behaviour. Do not import thresholds or bands from it.
- **"Context files make agents better at tasks."** Not supported on average (Gloaguen, Khatri, Zhang); what is supported is that agents follow them and that they cost tokens. rigcheck should present itself as a defect and cost linter, not a success optimizer.
- **"Contradictory instructions reduce compliance."** McMillan's conflict null has Bayes-factor support for a simple marker rule. Flag contradictions as maintenance debt, not as a compliance error.
- **Tipping, threats, politeness, authority framing as levers.** Null on average (Meincke 2025); framing effects exist on open models but are not a file-quality property.

## References

- Gloaguen et al., Evaluating AGENTS.md, arXiv 2602.11988 (2026-02-12): https://arxiv.org/abs/2602.11988
- Lulla et al., Impact of AGENTS.md on efficiency, arXiv 2601.20404 (2026-01-28): https://arxiv.org/abs/2601.20404
- Khatri, Two-Agent Ablation, arXiv 2607.27250 (2026-07-28): https://arxiv.org/abs/2607.27250
- Zhang et al., Guardrails Beat Guidance, arXiv 2604.11088 (2026-04-13): https://arxiv.org/abs/2604.11088
- McMillan, Instruction Adherence factorial study, arXiv 2605.10039 (2026-05-11): https://arxiv.org/abs/2605.10039
- Harada et al., When Instructions Multiply (ManyIFEval), EMNLP Findings 2025: https://aclanthology.org/2025.findings-emnlp.896.pdf
- Jaroslawicz et al., IFScale, arXiv 2507.11538 (2025-07-15): https://arxiv.org/abs/2507.11538
- Arize, IFScale replication (2026-05-08): https://github.com/Arize-ai/instruction-budget
- Liu et al., Lost in the Middle, arXiv 2307.03172 (2023-07-06): https://arxiv.org/abs/2307.03172
- Veseli et al., Positional Biases Shift, arXiv 2508.07479 (2025-08-10): https://arxiv.org/abs/2508.07479
- Chroma, Context Rot (2025-07-14): https://www.trychroma.com/research/context-rot
- SkillsBench, arXiv 2602.12670 (v1 2026-02-13, v4 2026-06-14): https://arxiv.org/abs/2602.12670
- Vercel, AGENTS.md outperforms skills (2026-01-27): https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals
- Liu et al., Agent Skills in the Wild, arXiv 2601.10338 (2026-01-15): https://arxiv.org/abs/2601.10338
- Do Not Mention This to the User, arXiv 2602.06547 (2026-02-06): https://arxiv.org/abs/2602.06547
- Credentials leaked by skills, arXiv 2604.03070 (2026-04-03): https://arxiv.org/abs/2604.03070
- Context Matters (skill ecosystem), arXiv 2603.16572 (2026-03-17): https://arxiv.org/abs/2603.16572
- Attention is Case-Sensitive, arXiv 2608.03711 (2026-08-04): https://arxiv.org/abs/2608.03711
- Control Illusion, arXiv 2502.15851 (2025-02-21): https://arxiv.org/abs/2502.15851
- Pragmatic Influence, arXiv 2602.21223 (2026-02-02): https://arxiv.org/abs/2602.21223
- Prompting Science Report 3, arXiv 2508.00614 (2025-08-01): https://arxiv.org/abs/2508.00614
- Semantic Gravity Wells, arXiv 2601.08070 (2026-01-12): https://arxiv.org/abs/2601.08070
- Jang et al., Negated Prompts, PMLR v203: https://proceedings.mlr.press/v203/jang23a/jang23a.pdf
- Bleakley, Saying what not to do (2023-09-26): https://alexbleakley.com/blog/saying-what-not-to-do
- Fu et al., Rules than Examples, arXiv 2609.03213 (2026-09-02): https://arxiv.org/abs/2609.03213
- Chatlatanagulchai et al., Agentic Coding Manifests, arXiv 2509.14744 (2025-09-18): https://arxiv.org/abs/2509.14744
- Chatlatanagulchai et al., Agent READMEs, arXiv 2511.12884 (2025-11-17): https://arxiv.org/abs/2511.12884
- Jiang & Nam, Cursor Rules, arXiv 2512.18925 (2025-12-21): https://arxiv.org/abs/2512.18925
- Galster et al., Harness Engineering, arXiv 2602.14690 (2026-02-16): https://arxiv.org/abs/2602.14690
- Sun et al., Cursorrules files, arXiv 2608.10622 (2026-08-11): https://arxiv.org/abs/2608.10622
- Reporails, State of AI Instruction Quality (2026-04-21): https://dev.to/reporails/the-state-of-ai-instruction-quality-35mn
- Reporails, 30k corpus: https://github.com/reporails/30k-corpus
- Reporails, Undiagnosed Input Problem (2026-04-08): https://dev.to/reporails/the-undiagnosed-input-problem-4pmc
- Mészáros, Precision Beats Clarity (2026-03-24): https://cleverhoods.medium.com/instruction-best-practices-precision-beats-clarity-e1bcae806671
- HumanLayer, Writing a good CLAUDE.md (2025-11-25): https://www.humanlayer.dev/blog/writing-a-good-claude-md
- Arize, CLAUDE.md prompt learning (2025-11-20): https://arize.com/blog/claude-md-best-practices-learned-from-optimizing-claude-code-with-prompt-learning/
- Willison, Claude Skills (2025-10-16): https://simonwillison.net/2025/Oct/16/claude-skills/
- Anand, Shouting at LLMs (2025-06-11): http://www.s-anand.net/blog/shouting-at-llms/
- Hyground, Stop Shouting (2026-03-18): https://hyground.ai/blog/stop-shouting
- InfoQ coverage of Gloaguen (2026-03): https://www.infoq.com/news/2026/03/agents-context-file-value-review/
