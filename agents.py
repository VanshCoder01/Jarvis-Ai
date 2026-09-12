"""
agents.py — Jarvis's multi-agent group chat.

You create named agents, each with a role, a model, an avatar and a colour.
Drop a task in and they discuss it in turns, each one reading everything said
before it, for a set number of rounds. A designated lead agent then delivers
the final answer.

Discussion-only by design: agents talk and reason, they do NOT run PC actions.
That's a deliberate safety line — a room of AIs reasoning is safe; a room of
AIs autonomously running commands is not, and that's a separate, guardrailed
feature if it's ever built.

Agents persist to agents.json alongside the other Jarvis data files.
"""
import json
import os
import time
import uuid

import config

_APPDATA = os.environ.get("APPDATA") or os.path.expanduser("~")
_DIR = os.path.join(_APPDATA, "Jarvis")
os.makedirs(_DIR, exist_ok=True)
_PATH = os.path.join(_DIR, "agents.json")

# OpenRouter free models rate-limit; a pause between turns keeps a multi-agent
# round from bursting straight into a 429.
TURN_DELAY_SECONDS = 3
MAX_ROUNDS = 5

_DEFAULT_COLORS = ["#6fe9f5", "#a78bfa", "#ffb454", "#7ef58c", "#ff7a9c", "#8fb8ff"]


def _load() -> list:
    if not os.path.exists(_PATH):
        return []
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(agents: list):
    try:
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(agents, f, indent=2)
    except Exception:
        pass


def list_agents() -> list:
    return _load()


def save_agent(agent: dict) -> dict:
    """Create (no id) or update (existing id). Returns the saved agent."""
    agents = _load()
    aid = agent.get("id")
    clean = {
        "id": aid or uuid.uuid4().hex[:12],
        "name": (agent.get("name") or "Agent").strip()[:40],
        "avatar": agent.get("avatar", ""),        # emoji or base64 image
        "role": (agent.get("role") or "").strip(),
        "model": agent.get("model", ""),
        "color": agent.get("color") or _DEFAULT_COLORS[len(agents) % len(_DEFAULT_COLORS)],
    }
    if aid:
        for i, a in enumerate(agents):
            if a["id"] == aid:
                agents[i] = clean
                break
        else:
            agents.append(clean)
    else:
        agents.append(clean)
    _save(agents)
    return clean


def delete_agent(agent_id: str) -> bool:
    agents = _load()
    remaining = [a for a in agents if a["id"] != agent_id]
    _save(remaining)
    return len(remaining) < len(agents)


def _agent_by_id(aid: str):
    for a in _load():
        if a["id"] == aid:
            return a
    return None


def run_discussion(task: str, agent_ids: list, rounds: int = 2, lead_id: str = ""):
    """Runs the group discussion and returns a list of turn dicts:
    {agent_id, name, avatar, color, text, round, final}.

    Progress is returned all at once here; server.py streams it turn by turn.
    Never raises — a failed turn becomes a visible error message in the
    transcript rather than sinking the whole run."""
    import llm

    task = (task or "").strip()
    if not task:
        return [{"name": "System", "text": "No task given.", "error": True}]

    roster = [a for a in (_agent_by_id(i) for i in agent_ids) if a]
    if not roster:
        return [{"name": "System", "text": "No agents selected.", "error": True}]

    rounds = max(1, min(int(rounds or 1), MAX_ROUNDS))
    transcript = []          # what the UI gets back
    convo = f"TASK: {task}\n\n"   # the running text every agent reads

    def one_turn(agent, is_final=False):
        instruction = agent["role"] or f"You are {agent['name']}, a helpful collaborator."
        if is_final:
            instruction += ("\n\nYou are the lead. The discussion is over. Give the final, "
                            "consolidated answer to the task. Be decisive and concise.")
        else:
            instruction += ("\n\nYou are in a group discussion with other agents. Read what's "
                            "been said, then add your contribution in a few sentences. Build on "
                            "or challenge the others — don't just agree. Stay in your role.")
        try:
            text, err = llm.call_text(
                api_key=config.API_KEY,
                system_instruction=instruction,
                user_content=convo + f"\n{agent['name']}, your turn:",
                model=agent.get("model") or None,
            )
            if err:
                text = f"({agent['name']} couldn't respond: {err})"
        except Exception as e:
            text = f"({agent['name']} errored: {e})"
        return text

    for r in range(rounds):
        for agent in roster:
            text = one_turn(agent)
            transcript.append({
                "agent_id": agent["id"], "name": agent["name"],
                "avatar": agent["avatar"], "color": agent["color"],
                "text": text, "round": r + 1, "final": False,
            })
            convo += f"\n[{agent['name']}]: {text}\n"
            time.sleep(TURN_DELAY_SECONDS)

    lead = _agent_by_id(lead_id) or roster[0]
    final_text = one_turn(lead, is_final=True)
    transcript.append({
        "agent_id": lead["id"], "name": lead["name"] + " (final)",
        "avatar": lead["avatar"], "color": lead["color"],
        "text": final_text, "round": rounds + 1, "final": True,
    })
    return transcript
