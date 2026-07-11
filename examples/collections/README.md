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

The example loads generic behavior and separate case data from:

```env
AGENT_INSTRUCTIONS_FILE=prompts/collections-es.md
CASE_CONTEXT_FILE=examples/collections/al-corriente.case.json
```

Run locally:

```bash
python -m voice_agent.app console
```

The demo speaks the outbound opening automatically. Set
`FSM_AUTO_OPENING_ENABLED=false` to wait for the caller's first turn instead.

After a call, evaluate its FSM trace with:

```bash
python scripts/evaluate-fsm-adherence.py --trace logs/fsm-adherence.jsonl
```
