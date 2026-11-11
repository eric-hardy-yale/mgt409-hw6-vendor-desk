# Handbook Token and Cost Estimate

The vendor desk agent sends `data/shop_handbook.md` to gpt-6-luna on every call. This note estimates what that costs before any real runs. Problem 4 checks these numbers against real usage.

## 1. Token count: 10,058 tokens

| Method | Count |
|---|---|
| **tiktoken `o200k_base` (used)** | **10,058 tokens** |
| tiktoken `cl100k_base` (older GPT-4 tokenizer, for comparison) | 10,184 tokens |
| Rule of thumb, characters ÷ 4 | 7,226 tokens (28,903 characters) |

**How I got it:** I read the file as text and ran it through OpenAI's `tiktoken` library with `o200k_base`, the tokenizer used by the current OpenAI model family that gpt-6-luna belongs to:

```python
import tiktoken
text = open("data/shop_handbook.md", encoding="utf-8").read()
print(len(tiktoken.get_encoding("o200k_base").encode(text)))   # 10058
```

The characters ÷ 4 shortcut comes in about 28% low. The handbook is mostly markdown tables (`|`, `---`, SKU codes like `CC-HD-006`, prices), and those split into more tokens than ordinary English does. So I used the real tokenizer count.

The real `prompt_tokens` on a call will be a little higher. A few tokens wrap each chat message, and the vendor document and instructions are added on top. This estimate covers the handbook alone.

## 2. Prices (from `data/prices.json`, gpt-6-luna, per 1M tokens)

| Token type | Price per 1M | Price per token |
|---|---|---|
| Input, not cached | $0.10 | $0.0000001 |
| Input, cached (cache read) | $0.01 | $0.00000001 |
| Cache write | $0.125 | $0.000000125 |
| Output | $0.50 | not used here (the handbook is input only) |

## 3. Cost of the handbook alone

### Without caching

Every call pays the full input price for all 10,058 tokens.

- **One call:** 10,058 × $0.10 / 1,000,000 = **$0.0010058** (about a tenth of a cent)
- **1,000 calls:** 1,000 × $0.0010058 = **$1.0058** (about $1.01)

### With caching

The first call writes the handbook to the cache. Every later call reads it from the cache at the cached price.

- **First call (cache write):** 10,058 × $0.125 / 1,000,000 = **$0.00125725**
- **Each later call (cache hit):** 10,058 × $0.01 / 1,000,000 = **$0.00010058** (about a hundredth of a cent)
- **1,000 calls:** 1 write + 999 hits
  = $0.00125725 + 999 × $0.00010058
  = $0.00125725 + $0.10047942
  = **$0.10173667** (about $0.10)

### Side by side

| | One call | 1,000 calls |
|---|---|---|
| No caching | $0.0010058 | $1.0058 |
| With caching | $0.00125725 on the first call, then $0.00010058 per hit | $0.1017 |
| **Savings with caching** | a hit is 10× cheaper than an uncached call | **$0.904 saved (about 90% less)** |

On a single call, caching costs slightly *more*: the write price ($0.125/1M) is above the normal input price ($0.10/1M). Caching only pays off because the same handbook is re-sent on every call. By the second call it has already earned back the extra cost of the write.

## 4. Assumptions to check in Problem 4

- **Handbook first.** Caching only matches an identical *prefix*. The handbook has to come first in the prompt and stay byte-for-byte the same on every call, with the vendor document after it. If anything that changes per call (a file name, date, or document text) comes before the handbook, nothing is cached.
- **Size threshold and step size.** OpenAI only caches prompts of at least 1,024 tokens, and it counts cached tokens in 128-token steps. The handbook clears the minimum easily. Because of the steps, though, a real run may report a cached count that's a little off from 10,058 (for example 9,984, or a bit more once the instructions are added).
- **Calls close together.** The cache expires after a few minutes of no use. The 1,000-call figure assumes the calls run back to back, so the cache stays warm.
- **Cache-write pricing.** `prices.json` lists a $0.125/1M cache-write price, so I charged it on the first call. If the real usage report doesn't show a separate cache-write charge, the first call simply costs the normal $0.0010058, and the 1,000-call total drops to about $0.1015.
- **Output and the document are extra.** The model's answer is billed at $0.50/1M output tokens, and each vendor document adds its own input tokens. Neither is included here, because this is the handbook alone.
