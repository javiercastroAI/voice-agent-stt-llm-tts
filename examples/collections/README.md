# Collections Demo

This example configures the voice agent as a Spanish outbound collections demo.
The scenario is fictional: MacroHard calls Al Corriente S.L. about one pending
CloudX monthly charge for 1.527 euros.

## Use

From the repository root:

```bash
cp examples/collections/.env.example .env
```

Set your real `OPENAI_API_KEY`. Add LiveKit credentials only when using `dev` or
`start` modes.

The example loads its behavior from:

```env
AGENT_INSTRUCTIONS_FILE=prompts/collections-es.md
```

Run locally:

```bash
python -m voice_agent.app console
```
