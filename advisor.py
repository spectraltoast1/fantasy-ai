import sys
import json
import anthropic
from context import assemble_prompt_context
from config import ANTHROPIC_API_KEY

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """\
You are a sharp, direct fantasy football coach. You give confident, data-grounded advice without hedging.

Guidelines:
- Lead with a clear recommendation — never bury the answer
- Keep it under 150 words unless the question genuinely requires more depth
- Reference specific players, positions, and scoring context from the data provided
- If it's the off-season and matchup data is unavailable, focus on roster construction and offseason moves instead
"""


def ask(question, league_id=None):
    ctx = assemble_prompt_context(league_id)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"My current fantasy context:\n\n{json.dumps(ctx, indent=2)}",
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": f"Question: {question}",
                    },
                ],
            }
        ],
    )

    return response.content[0].text


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python advisor.py \"Your question here\"")
        print('       python advisor.py --league <league_id> "Your question here"')
        sys.exit(1)

    league_id = None
    args = sys.argv[1:]
    if args[0] == "--league" and len(args) >= 3:
        league_id = args[1]
        question = " ".join(args[2:])
    else:
        question = " ".join(args)

    print(f"\nFetching context...\n")
    answer = ask(question, league_id)
    print(answer)
