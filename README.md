# Campus Customs Vendor Desk (MGT 409 · HW6)

A PydanticAI agent on `gpt-6-luna` (through Portkey) that reads one vendor document (an HTML quote, a PDF, or an `.eml` email), pulls out the vendor, SKU, unit price, lead time and minimum order, and decides **recommend** or **do_not_recommend** using the four purchasing checks in `data/shop_handbook.md`. It has three defense layers against booby-trapped documents (code, design, prompt) and two trap tools (`send_email`, `approve_payment`) that only log to `output/trap_calls.json`.

**Start here:** open `output/hw6_report.html`. It's one file that works offline with a double-click.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then put your PORTKEY_API_KEY in .env
```

## Run the agent

```bash
python agent.py --doc data/practice_docs/p01_bluehen_quote.html
```

It prints the answer as JSON plus the token counts and cost, then appends to `output/usage_log.json` and `output/audit_trail.json`.

| Option | What it does |
|---|---|
| `--defenses all` (default) | All three defense layers on: code, design and prompt |
| `--defenses none` | The original Problem 3 agent, with no new defenses |
| `--defenses code,prompt` | Any combination of `code`, `design`, `prompt` |
| `--cache on` / `--cache off` | Reuse the prompt + handbook from the prompt cache (default on) or not at all |

Examples:

```bash
python agent.py --doc data/exam_docs/e01_quote.html
python agent.py --doc data/my_attacks/a1_bluehen_quote.pdf --defenses none
```

## The agent

| File | What it is |
|---|---|
| `agent.py` | Entry point. Builds the agent, runs one document, and logs tokens, dollars and tool calls. |
| `tools.py` | `read_document` plus the `send_email` and `approve_payment` traps, the visible-text-only readers (code layer), and the handbook checks written in Python (design layer). |
| `models.py` | `VendorDecision` (the answer), `Extraction`/`Conflict` (design layer), and `DeskDeps`. |
| `prompts/prompt.md` | The agent's instructions and safety rules (prompt layer). `prompt_problem3.md` is the original, and `extractor.md` is the design layer's extract-only prompt. |

## Scripts that produced the results

| Script | Problem | Writes |
|---|---|---|
| `cache_test.py` | 4: caching | `output/cache_test.json`, used for `cache_test.md` |
| `attack_test.py` | 5: attacks, no defenses | `output/attack_results.json` |
| `defense_test.py` | 6: defenses, all 5 setups | `output/defense_results.json` |
| `probe_test.py` | 6: what each layer catches | `output/probe_results.json` (probe docs in `probes/`) |
| `make_attacks.py` | 7: builds my two attacks | `data/my_attacks/` |
| `red_team_test.py` | 7: red team | `output/red_team_results.json` |
| `exam_run.py` | 8: exam | `output/exam_results.json`, `output/exam_consistency.json` |
| `build_report.py` | 9: report | `output/hw6_report.html` |

Write-ups are in `output/*.md`. `AI_prompts.md` is the log of the prompts I gave my vibe coder.

## Data

`data/` is the course data (handbook, prices, 12 practice documents with their key, 10 exam documents) plus my two attack files in `data/my_attacks/`:
- `a1_bluehen_quote.pdf`: a "scanned" quote whose hidden text layer swaps the SKU
- `a2_westville_email.eml`: an email whose plain-text copy lies about the minimum order

`drafts/` holds my first, weaker version of a1, which is described in `output/red_team.md`.
