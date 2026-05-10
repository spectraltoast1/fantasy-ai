import json
import os
import re
import time
from anthropic import Anthropic

client = Anthropic()

FOLDER = "fse_dynasty"
LEAGUE_TYPE = "dynasty"
CACHE_FILE = f"{FOLDER}_cache.json"
OUTPUT_FILE = f"{FOLDER}_strategy.md"
DELAY = 30  # seconds between Pass 1 API calls to stay under rate limit

PASS1_PROMPT = """Extract discrete, actionable fantasy football strategy rules from this transcript.
Rules should be:
- General (not player/week specific)
- Actionable (tells you what to DO)
- Concise (one sentence each)
- Relevant to DYNASTY leagues specifically

Return ONLY a numbered list. No commentary, no preamble."""


PASS2_PROMPT = f"""Below are strategy principles extracted from multiple videos by a fantasy football creator, focused on {LEAGUE_TYPE} leagues.

Synthesize these into a clean, deduplicated strategy document.
- Where principles conflict, note the conflict explicitly rather than silently picking one
- Organize by category (waiver wire, roster construction, trade strategy, startup drafts, etc.)
- Keep the voice actionable -- these should read as rules to follow
- Flag anything that seems {LEAGUE_TYPE}-specific vs general advice

Return a well-structured markdown document."""


def clean_transcript(text):
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2)


def extract_principles(transcript, filename):
    print(f"Pass 1: {filename}")
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=[{"type": "text", "text": PASS1_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": transcript}],
    )
    return response.content[0].text


def synthesize(all_principles):
    print("Pass 2: synthesizing...")
    combined = "\n\n---\n\n".join(all_principles)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": combined, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": PASS2_PROMPT},
            ],
        }],
    )
    return response.content[0].text


def main():
    cache = load_cache()
    principles_list = []

    # Pass 1
    for filename in sorted(os.listdir(FOLDER)):
        if not filename.endswith(".txt"):
            continue
        if filename in cache:
            print(f"Pass 1: {filename} (cached)")
            principles_list.append(f"### {filename}\n{cache[filename]}")
            continue
        filepath = os.path.join(FOLDER, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            transcript = clean_transcript(f.read())
        principles = extract_principles(transcript, filename)
        cache[filename] = principles
        save_cache(cache)
        principles_list.append(f"### {filename}\n{principles}")
        time.sleep(DELAY)

    # Pass 2
    final_doc = synthesize(principles_list)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(f"# {FOLDER.replace('_', ' ').title()} Strategy\n\n")
        f.write(final_doc)

    print(f"Done. Strategy doc saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()