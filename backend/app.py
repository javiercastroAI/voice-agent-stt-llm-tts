from __future__ import annotations

"""Compatibility backend entrypoint for the copied voice agent app."""

def main() -> None:
    from voice_agent.app import main as voice_agent_main

    voice_agent_main()


if __name__ == "__main__":
    main()
