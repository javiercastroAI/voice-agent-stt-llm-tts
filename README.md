# Voice Agent

This repo packages the Lesson 4 and Lesson 5 notebook flow into a normal Python app using:

- OpenAI for LLM and speech-to-text
- OpenAI for text-to-speech
- Silero for voice activity detection
- LiveKit Agents for orchestration, console mode, and room execution

## Requirements

- Python 3.11 or newer
- A microphone and speaker for `console` mode
- An OpenAI API key
- LiveKit credentials for `dev` or `start`

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
cp .env.example .env
```

## Configuration

Set these values in `.env`:

- `OPENAI_API_KEY`
- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`

Optional overrides:

- `OPENAI_MODEL` defaults to `gpt-4o`
- `OPENAI_STT_MODEL` defaults to `gpt-4o-transcribe-diarize`
- `OPENAI_TTS_MODEL` defaults to `gpt-4o-mini-tts`
- `OPENAI_TTS_VOICE` defaults to `marin`
- `AGENT_INSTRUCTIONS` defaults to `You are a helpful assistant communicating via voice`
- Console mode starts a local transcript web page and prints its URL on startup
- The terminal still prints a speaker-labeled conversation trace for user diarization and agent replies

## Run

Local console mode with microphone and speaker:

```bash
python -m voice_agent.app console
```

When console mode starts, open the printed `Transcript Web UI` URL in your browser. The page shows:

- live agent text while the model is speaking
- user speaking state immediately
- final user diarization after each utterance completes
- the full conversation history outside the terminal

List local audio devices without requiring API keys:

```bash
python -m voice_agent.app console --list-devices
```

Run against a LiveKit room in development mode:

```bash
python -m voice_agent.app dev
```

Run in normal worker mode:

```bash
python -m voice_agent.app start
```

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## Notes

- `console` mode uses the LiveKit console audio path and does not require LiveKit room credentials.
- `OPENAI_API_KEY` falls back to `/Users/macjcp/.env` if it is not set in the repo environment.
- `dev` and `start` validate that both the OpenAI key and LiveKit credentials are present before the worker starts.
- The notebook's old `eou_metrics_collected` callback is replaced by the current unified `metrics_collected` event stream.
