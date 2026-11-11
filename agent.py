"""Campus Customs vendor desk agent (PydanticAI + gpt-6-luna via Portkey).

Usage:
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html [--cache on|off] [--defenses all|none|code,design,prompt]

Reads one vendor document, returns a VendorDecision, and appends to
output/usage_log.json (tokens + dollars) and output/audit_trail.json (tool calls + answer).

Defense layers (default: all three; --defenses none is the Problem 3 agent, unchanged):
  code   - strip text a person can't see (hidden HTML, white/tiny/off-page PDF text, hidden
           email parts, zero-width characters) before any model reads the document
  design - the model only extracts facts, has no tools at all, and plain Python applies the
           handbook checks and writes the decision
  prompt - the stronger safety rules in prompts/prompt.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart, RetryPromptPart
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from models import DeskDeps, Extraction, VendorDecision
from tools import ALL_TOOLS, append_json, covered_pdf_text, decide, extract_text, now_iso, wrap_document

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

HERE = Path(__file__).resolve().parent
PROMPT_FILE = HERE / "prompts" / "prompt.md"  # defended prompt (prompt layer)
BASELINE_PROMPT_FILE = HERE / "prompts" / "prompt_problem3.md"  # Problem 3 prompt, no new defenses
EXTRACTOR_PROMPT_FILE = HERE / "prompts" / "extractor.md"  # design layer: extract-only model
HANDBOOK_FILE = HERE / "data" / "shop_handbook.md"
PRICES_FILE = HERE / "data" / "prices.json"
OUTPUT_DIR = HERE / "output"

MODEL_NAME = "gpt-6-luna"  # the only model this homework may use
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
OUTPUT_TOOL_NAME = "final_result"  # PydanticAI's structured-output tool, not one of ours

LAYERS = ("code", "design", "prompt")
ALL_DEFENSES = frozenset(LAYERS)
NO_DEFENSES = frozenset()

load_dotenv(HERE / ".env")


def parse_defenses(value: str) -> frozenset[str]:
    value = value.strip().lower()
    if value == "all":
        return ALL_DEFENSES
    if value == "none":
        return NO_DEFENSES
    chosen = frozenset(v.strip() for v in value.split(",") if v.strip())
    unknown = chosen - ALL_DEFENSES
    if unknown:
        raise ValueError(f"Unknown defense layer(s): {', '.join(sorted(unknown))}. Use code, design, prompt.")
    return chosen


def defenses_label(defenses: frozenset[str]) -> str:
    return "+".join(l for l in LAYERS if l in defenses) or "none"


def safety_rules_section() -> str:
    """The '## Safety rules' section of prompts/prompt.md (used by the extractor when the prompt layer is on)."""
    text = PROMPT_FILE.read_text(encoding="utf-8")
    m = re.search(r"^## Safety rules.*?(?=^## |\Z)", text, flags=re.S | re.M)
    return m.group(0).strip() if m else ""


def build_instructions(defenses: frozenset[str]) -> str:
    """Prompt plus the full handbook. Static on every call, so it forms a cacheable prefix."""
    if "design" in defenses:
        prompt = EXTRACTOR_PROMPT_FILE.read_text(encoding="utf-8").strip()
        if "prompt" in defenses:
            prompt += "\n\n" + safety_rules_section()
    else:
        prompt = (PROMPT_FILE if "prompt" in defenses else BASELINE_PROMPT_FILE).read_text(encoding="utf-8").strip()
    handbook = HANDBOOK_FILE.read_text(encoding="utf-8").strip()
    return f"{prompt}\n\n<shop_handbook>\n{handbook}\n</shop_handbook>"


def cache_settings(cache: bool, defenses: frozenset[str]) -> OpenAIResponsesModelSettings:
    """Prompt-cache settings for the two setups.

    cache=True:  the static instructions (prompt + handbook) go first with an explicit cache
                 breakpoint after them. mode="explicit" turns off OpenAI's automatic breakpoint,
                 so only that prefix is cached; the per-run document is never written to cache.
    cache=False: mode="explicit" with no breakpoint at all. Per the OpenAI API, "if there are no
                 explicit breakpoints, the request does not use prompt caching", so nothing is
                 read from or written to cache. The token counts in the logs prove it.
    """
    if cache:
        return OpenAIResponsesModelSettings(
            openai_cache_instructions=True,
            openai_prompt_cache_options={"mode": "explicit"},
            openai_prompt_cache_key=f"campus-customs-vendor-desk-{defenses_label(defenses)}",
        )
    return OpenAIResponsesModelSettings(
        openai_cache_instructions=False,
        openai_prompt_cache_options={"mode": "explicit"},
    )


def build_agent(cache: bool = True, defenses: frozenset[str] = ALL_DEFENSES) -> Agent:
    key = os.getenv("PORTKEY_API_KEY", "").strip()
    if not key:
        sys.exit("PORTKEY_API_KEY is missing. Put it in hw6/.env.")
    client = AsyncOpenAI(
        api_key=key,
        base_url=PORTKEY_BASE_URL,
        default_headers={
            "x-portkey-provider": "openai",
            # Skip Portkey's response cache so every run is a real model call with real token counts.
            "x-portkey-cache-force-refresh": "true",
        },
    )
    model = OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))
    design = "design" in defenses
    return Agent(
        model,
        deps_type=DeskDeps,
        # Design layer: the model that reads the document gets no tools and no decision field.
        output_type=Extraction if design else VendorDecision,
        instructions=build_instructions(defenses),
        tools=[] if design else ALL_TOOLS,
        model_settings=cache_settings(cache, defenses),
    )


def load_prices() -> dict:
    return json.loads(PRICES_FILE.read_text())[MODEL_NAME]


def usage_dict(u) -> dict:
    """Token counts the API reported, from a PydanticAI RunUsage or RequestUsage."""
    details = u.details or {}
    return {
        "input_tokens": u.input_tokens,
        "cache_read_tokens": u.cache_read_tokens,
        "cache_write_tokens": u.cache_write_tokens,
        "output_tokens": u.output_tokens,
        "reasoning_tokens": details.get("reasoning_tokens", 0),
        "total_tokens": u.input_tokens + u.output_tokens,
    }


def cost_usd(usage: dict, prices: dict) -> dict:
    """Dollar cost from API token counts. input_tokens already includes cache reads and writes."""
    uncached = max(usage["input_tokens"] - usage["cache_read_tokens"] - usage["cache_write_tokens"], 0)
    parts = {
        "uncached_input": uncached * prices["input_per_1m"] / 1e6,
        "cached_input": usage["cache_read_tokens"] * prices["cached_input_per_1m"] / 1e6,
        "cache_write": usage["cache_write_tokens"] * prices["cache_write_per_1m"] / 1e6,
        "output": usage["output_tokens"] * prices["output_per_1m"] / 1e6,
    }
    return {"uncached_input_tokens": uncached, "breakdown_usd": {k: round(v, 8) for k, v in parts.items()},
            "total_usd": round(sum(parts.values()), 8)}


def short(value, limit: int = 200) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def tool_calls_from(messages) -> list[dict]:
    """Pair every tool call the model made with its result, in order."""
    calls, results = [], {}
    for msg in messages:
        for part in msg.parts:
            if isinstance(msg, ModelResponse) and isinstance(part, ToolCallPart):
                calls.append(part)
            elif isinstance(msg, ModelRequest) and isinstance(part, (ToolReturnPart, RetryPromptPart)):
                if part.tool_call_id:
                    results[part.tool_call_id] = part
    out = []
    for call in calls:
        if call.tool_name == OUTPUT_TOOL_NAME:
            continue
        res = results.get(call.tool_call_id)
        if isinstance(res, ToolReturnPart):
            result = short(res.content)
        elif isinstance(res, RetryPromptPart):
            result = "error: " + short(res.content)
        else:
            result = "no result"
        out.append({"tool": call.tool_name, "args": call.args_as_dict(), "result": result})
    return out


def model_calls_from(messages, prices: dict) -> list[dict]:
    """One record per model call (API request), with that call's own token counts and cost."""
    out = []
    for msg in messages:
        if isinstance(msg, ModelResponse):
            usage = usage_dict(msg.usage)
            tools = [p.tool_name for p in msg.parts if isinstance(p, ToolCallPart)]
            out.append({
                "call": len(out) + 1,
                "response_id": msg.provider_response_id,
                "model_reported": msg.model_name,
                "tools_called": tools,
                **usage,
                **cost_usd(usage, prices),
            })
    return out


@dataclass
class RunRecord:
    document: str
    time: str
    setup: str
    defenses: str
    answer: VendorDecision
    usage: dict
    cost: dict
    model_calls: list[dict]
    trap_hits: list[dict]
    hidden_removed: list[dict] = field(default_factory=list)
    defense_notes: list[str] = field(default_factory=list)
    extraction: dict | None = None


def run_document(doc: str | Path, cache: bool = True, defenses: frozenset[str] = ALL_DEFENSES) -> RunRecord:
    """Run the agent on one document and append to the usage log and audit trail."""
    doc_path = Path(doc).expanduser().resolve()
    if not doc_path.is_file():
        raise FileNotFoundError(f"No such document: {doc}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    trap_file = OUTPUT_DIR / "trap_calls.json"
    if not trap_file.exists():
        trap_file.write_text("[]\n", encoding="utf-8")

    deps = DeskDeps(doc_path=doc_path, output_dir=OUTPUT_DIR, sanitize="code" in defenses)
    started = now_iso()
    setup = "with_cache" if cache else "without_cache"
    label = defenses_label(defenses)
    agent = build_agent(cache, defenses)
    notes: list[str] = []
    extraction = None

    if "design" in defenses:
        # Code reads the document and hands the text over as data; the model has no tools to call.
        text, removed = extract_text(doc_path, sanitize=deps.sanitize)
        deps.removed_hidden.extend(removed)
        result = agent.run_sync(
            "Extract the facts from this vendor document.\n\n" + wrap_document(doc_path.name, text), deps=deps
        )
        extraction = result.output.model_dump()
        # plain Python applies the handbook checks (plus the scanned-quote rule for covered PDF text)
        answer, notes = decide(result.output, text, covered_pdf_text(doc_path))
    else:
        result = agent.run_sync(f"Review this vendor document and return your decision: {doc_path}", deps=deps)
        answer = result.output

    hidden_pieces = [r for r in deps.removed_hidden if r.get("text")]
    if hidden_pieces:
        notes.insert(0, f"code layer removed {len(hidden_pieces)} piece(s) of hidden text")
    doc_rel = os.path.relpath(doc_path, HERE)
    prices = load_prices()
    usage = {"requests": result.usage.requests, **usage_dict(result.usage)}
    cost = cost_usd(usage, prices)
    messages = result.all_messages()
    append_json(OUTPUT_DIR / "usage_log.json", {
        "document": doc_rel, "time": started, "model": MODEL_NAME, "setup": setup, "defenses": label,
        **usage, **cost,
    })
    append_json(OUTPUT_DIR / "audit_trail.json", {
        "document": doc_rel, "time": started, "setup": setup, "defenses": label,
        "decided_by": "code (handbook checks in tools.decide)" if "design" in defenses else "model",
        "hidden_text_removed": deps.removed_hidden,
        "tool_calls": tool_calls_from(messages),
        "trap_calls": deps.trap_hits,
        "extraction": extraction,
        "defense_notes": notes,
        "final_answer": answer.model_dump(),
    })
    return RunRecord(doc_rel, started, setup, label, answer, usage, cost, model_calls_from(messages, prices),
                     deps.trap_hits, deps.removed_hidden, notes, extraction)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the vendor desk agent on one vendor document.")
    parser.add_argument("--doc", required=True, help="Path to a vendor document (.html, .pdf, or .eml)")
    parser.add_argument("--cache", choices=["on", "off"], default="on",
                        help="Reuse the prompt + handbook from the prompt cache (default: on)")
    parser.add_argument("--defenses", default="all",
                        help="all (default), none (the Problem 3 agent), or a comma list of code,design,prompt")
    args = parser.parse_args()

    try:
        rec = run_document(args.doc, cache=args.cache == "on", defenses=parse_defenses(args.defenses))
    except (FileNotFoundError, ValueError) as e:
        sys.exit(str(e))

    u = rec.usage
    print(json.dumps(rec.answer.model_dump(), indent=2))
    for note in rec.defense_notes:
        print(f"note: {note}")
    print(f"\n[{rec.setup}, defenses={rec.defenses}] {u['requests']} model call(s) | {u['input_tokens']:,} input "
          f"({u['cache_read_tokens']:,} cached read, {u['cache_write_tokens']:,} cache write) | "
          f"{u['output_tokens']:,} output | ${rec.cost['total_usd']:.6f}")
    if rec.trap_hits:
        print(f"WARNING: {len(rec.trap_hits)} trap tool call(s) logged to output/trap_calls.json")


if __name__ == "__main__":
    main()
