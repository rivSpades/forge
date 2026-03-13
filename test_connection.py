"""Quick connectivity test for the Anthropic SDK.

Run with:
    python test_connection.py

Expected output:
    OK

If you see an authentication error, ensure:
  - ANTHROPIC_API_KEY is set in your .env
  - utils/env.py is loading .env (it does on import)
"""

from anthropic import Anthropic, HUMAN_PROMPT, AI_PROMPT

from utils.env import settings


def main() -> None:
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    prompt = HUMAN_PROMPT + "reply with the single word OK" + AI_PROMPT

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=10,
        messages=[{"role": "user", "content": "reply with the single word OK"}],
    )

    # The Messages API returns a list of content blocks; the first is the model reply.
    print(resp.content[0].text.strip())


if __name__ == "__main__":
    main()
