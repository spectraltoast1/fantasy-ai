"""
Anthropic client seam for the Manager Dossiers AI layer (DECISION_READS.md §7 Phase B).

The project's FIRST AI-layer code — architecturally distinct from the deterministic polars
transforms. This module is the ONE place that knows *how* a dossier request reaches the model:
the API-key gate + the single synchronous call. Isolating the call here means a future Batch path
(for a high-volume hosted sweep) is a localized swap, not a rewrite — the same client/server-seam
philosophy the front-end uses.

Key gate: the read is opt-in and non-vital, LOCKED when `config.ANTHROPIC_API_KEY` is absent or a
placeholder. The call uses synchronous `messages.create` (Haiku 4.5) with JSON-in-prompt +
`json.loads` — NOT `messages.parse` — so it doesn't couple to the SDK's structured-outputs support
(version-safe per the §7 design).
"""

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
from application import config

DEFAULT_MODEL = "claude-haiku-4-5"             # the locked §7 tier (cheap; ample for this synthesis)
_PLACEHOLDER = "your-key-here"


def api_available() -> bool:
    """Whether the dossier read is unlocked — a real Claude API key is configured.

    Opt-in and non-vital: absent / placeholder / non-`sk-ant` key => locked (the writer skips
    cleanly). Deliberately does NOT import anthropic, so availability can be checked without the
    dependency loaded.
    """
    key = getattr(config, "ANTHROPIC_API_KEY", None)
    return bool(key) and key != _PLACEHOLDER and key.startswith("sk-ant")


def _strip_fences(text: str) -> str:
    """Drop a leading ```json fence and surrounding whitespace from a model reply."""
    s = text.strip()
    if s.startswith("```"):
        parts = s.split("```")
        s = parts[1] if len(parts) >= 2 else s
        if s.lstrip().startswith("json"):
            s = s.lstrip()[4:]
        s = s.strip()
    return s


def _extract_json(text: str) -> dict:
    """Parse a model reply into a dict, tolerating ```json fences or surrounding prose."""
    s = _strip_fences(text)
    if not s.startswith("{"):                  # fall back to the outermost {...} span
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j > i:
            s = s[i:j + 1]
    return json.loads(s)


def _extract_json_array(text: str) -> list:
    """Parse a model reply into a list, tolerating ```json fences or surrounding prose.

    The array analog of `_extract_json` — Stage B (team news sheets) returns a JSON ARRAY of claims,
    which `_extract_json` would mis-handle (it grabs the first inner object).
    """
    s = _strip_fences(text)
    if not s.startswith("["):                  # fall back to the outermost [...] span
        i, j = s.find("["), s.rfind("]")
        if i != -1 and j > i:
            s = s[i:j + 1]
    data = json.loads(s)
    if not isinstance(data, list):
        raise ValueError("expected a JSON array")
    return data


def _raw_call(system: str, user: str, *, model: str, max_tokens: int, cache_system: bool):
    """The single synchronous Haiku call → (reply text, usage dict). THE swap point for Batch later.

    No `thinking` / `effort` params (Haiku 4.5 rejects `effort` and doesn't need thinking).
    `cache_system` prompt-caches the shared prefix (only effective above Haiku's ~4096-token minimum).
    Shared by every AI read so a future Batch path is a single localized change.
    """
    import anthropic                            # lazy — only imported when a call is actually made
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    system_block = [{"type": "text", "text": system}]
    if cache_system:
        system_block[0]["cache_control"] = {"type": "ephemeral"}

    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_block,
        messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    u = resp.usage
    usage = {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }
    return text, usage


def generate_dossier(system: str, user: str, *, model: str = DEFAULT_MODEL,
                     max_tokens: int = 1500, cache_system: bool = False):
    """One synchronous Haiku call → (parsed dossier dict, usage dict).

    `system` / `user` are the pre-built prompts (dossier_prompt.py). Raises ValueError on an
    unparseable reply.
    """
    text, usage = _raw_call(system, user, model=model, max_tokens=max_tokens,
                            cache_system=cache_system)
    try:
        dossier = _extract_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"dossier reply was not valid JSON: {exc}\n---\n{text[:500]}") from exc
    return dossier, usage


def generate_claims(system: str, user: str, *, model: str = DEFAULT_MODEL,
                    max_tokens: int = 2000, cache_system: bool = False):
    """One synchronous Haiku call → (list of claim dicts, usage dict).

    The JSON-ARRAY analog of `generate_dossier` for the Stage B team news sheets (news_prompt.py).
    Raises ValueError on a reply that isn't a parseable array.
    """
    text, usage = _raw_call(system, user, model=model, max_tokens=max_tokens,
                            cache_system=cache_system)
    try:
        claims = _extract_json_array(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"claims reply was not a valid JSON array: {exc}\n---\n{text[:500]}") from exc
    return claims, usage
