"""Play as a human (default) or watch an agent: python play.py [--agent scripted]"""
import argparse

from env import SandEnv

KEYS = {"UP": "MOVE N", "DOWN": "MOVE S", "LEFT": "MOVE W", "RIGHT": "MOVE E",
        "g": "GATHER", "d": "DRINK", "r": "REST"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="worm_path")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--agent", choices=["human", "random", "scripted"], default="human")
    a = ap.parse_args()

    import pygame
    from agents import RandomAgent, ScriptedAgent
    from game.viewer import Viewer

    env = SandEnv(a.scenario, seed=a.seed)
    env.reset()
    view = Viewer(env)
    agent = {"random": RandomAgent(), "scripted": ScriptedAgent()}.get(a.agent)
    msgs = [env.scenario.description]
    clock = pygame.time.Clock()
    running = True
    while running:
        action = None
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN and agent is None:
                name = pygame.key.name(e.key)
                if name == "t":
                    text = view.prompt()
                    action = f'FREEFORM "{text}"' if text else None
                else:
                    action = KEYS.get(name.upper() if len(name) > 1 else name)
        if agent is not None and not env.engine.state.done:
            action = agent.act(env)
            pygame.time.wait(120)
        if action and not env.engine.state.done:
            _, _, _, _, info = env.step(action)
            msgs += info["events"]
        view.draw(msgs)
        clock.tick(30)
    pygame.quit()


if __name__ == "__main__":
    main()
