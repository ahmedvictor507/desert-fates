# Training (GRPO)

Plan: SFT warm-up on `ScriptedAgent` demonstrations, then GRPO with TRL on a rented 24GB GPU.

- Rollouts: `LLMAgent.prompt(env)` -> model -> `parse_action` -> `env.step`.
- Reward: sum of env rewards over an episode, plus a small format bonus when the raw output parses.
- Baselines to beat (`python evaluate.py`): random and scripted agents.
- Keep the policy small (Qwen3-1.7B/4B + LoRA) so players can run the result locally in 4-bit.

Scripts are not written yet; see the project plan in the root README.
