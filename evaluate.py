"""Run an agent for N seeded episodes and print mean reward / endings."""
import argparse
from collections import Counter

from agents import RandomAgent, ScriptedAgent
from env import SandEnv


def run(agent, scenario, episodes, max_steps=500):
    endings, total = Counter(), 0.0
    for seed in range(episodes):
        env = SandEnv(scenario, seed=seed)
        env.reset()
        for _ in range(max_steps):
            _, r, term, trunc, info = env.step(agent.act(env))
            total += r
            if term or trunc:
                endings[info["ending"]] += 1
                break
    return total / episodes, endings


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", choices=["random", "scripted"], default="scripted")
    ap.add_argument("--scenario", default="worm_path")
    ap.add_argument("--episodes", type=int, default=50)
    a = ap.parse_args()
    agent = RandomAgent() if a.agent == "random" else ScriptedAgent()
    mean, ends = run(agent, a.scenario, a.episodes)
    print(f"{a.agent} on {a.scenario}: mean reward {mean:.2f}, endings {dict(ends)}")
