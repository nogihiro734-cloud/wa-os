# WA-OS Policy Drift Benchmark v0.1

This package contains an 18-case benchmark for testing whether AI responses preserve human judgment rather than replacing it.

## Structure

- `benchmark_v0_1.json` — 18 Japanese test prompts
- `scoring_guide.md` — evaluation rules
- `results/result_template.json` — reusable result sheet
- `reports/` — comparison reports added after testing

## Design

Six categories × three case types: clear, boundary, and evasion-oriented.

## Suggested first experiment

Run all 18 prompts unchanged through ChatGPT, Claude, Gemini, and Perplexity. Save exact answers in separate copies of the result template. Preserve written reasons, reviewer disagreements, and uncertainty instead of ranking models only by a total score.
