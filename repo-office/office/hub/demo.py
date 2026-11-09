"""
Scripted walk-through so the office can be seen without any agent running.
Every event is flagged simulated=True and the UI marks them as such — this
is not real agent output. Several tracks run at once so people talk inside
their team and across teams at the same time.
"""

import asyncio
from typing import List, Optional, Tuple

from .bus import bus
from .models import AgentEvent, EventKind, MemberState

W, I, WT = MemberState.working, MemberState.idle, MemberState.waiting
K = EventKind

# (delay_after_previous_s, team, member, kind, text, state, (to_team, to_member))
Step = Tuple[float, str, str, EventKind, str, Optional[MemberState], Optional[Tuple[str, str]]]


def say(d, team, member, text, state=None):
    return (d, team, member, K.message, text, state, None)


def think(d, team, member, text="Thinking...", state=W):
    return (d, team, member, K.thinking, text, state, None)


def tool(d, team, member, text, state=W):
    return (d, team, member, K.tool_call, text, state, None)


def result(d, team, member, text, state=None):
    return (d, team, member, K.tool_result, text, state, None)


def hand(d, team, member, text, to_team, to_member, state=I):
    return (d, team, member, K.handoff, text, state, (to_team, to_member))


def inbound(d, team, member, text, state=W):
    return (d, team, member, K.inbound, text, state, None)


def done(d, team, member, text):
    return (d, team, member, K.done, text, I, None)


IAC: List[Step] = [
    inbound(0.5, "iac", "requirements", "You: small web app on Hetzner, Postgres DB and a bucket for uploads, Falkenstein."),
    think(1.6, "iac", "requirements", "Pulling components out of the conversation..."),
    say(2.2, "iac", "requirements", "Hetzner, fsn1. Three components: server, SQL database, object storage."),
    hand(2.4, "iac", "requirements", "Requirements are clear. Arjun, your turn.", "iac", "architect"),
    tool(2.2, "iac", "architect", "search_terraform_providers('hetzner')"),
    result(1.8, "iac", "architect", "hetznercloud/hcloud 1.70, auth: HCLOUD_TOKEN"),
    tool(2.0, "iac", "architect", "list_provider_resources(keyword='database')"),
    result(1.8, "iac", "architect", "No managed Postgres on this cloud."),
    say(2.2, "iac", "architect", "Workaround: a server plus volume running Postgres via cloud-init."),
    hand(2.6, "iac", "architect", "Design ready. Tara, over to you.", "iac", "writer"),
    tool(2.2, "iac", "writer", "get_resource_doc('hcloud_server')"),
    say(2.2, "iac", "writer", "Writing main.tf, variables.tf and outputs.tf."),
    tool(2.4, "iac", "writer", "validate_terraform(3 files)"),
    result(1.8, "iac", "writer", "HCL syntax OK"),
    hand(2.0, "iac", "writer", "Validates. Rex, please review.", "iac", "reviewer"),
    tool(2.4, "iac", "reviewer", "scan_for_risky_patterns(3 files)"),
    say(2.0, "iac", "reviewer", "Warning: firewall opens port 22 to 0.0.0.0/0."),
    hand(2.6, "iac", "reviewer", "No blockers. Ira, it's ready to plan.", "iac", "operator", WT),
    say(2.0, "iac", "operator", "Waiting for a human to ask for a plan.", WT),
    hand(6.0, "iac", "operator", "Rae asked about capacity; checking drift state with Dev.", "iac", "drift", WT),
    say(2.0, "iac", "drift", "No drift on the current state. All clear."),
    done(2.0, "iac", "drift", "Scan finished."),
]

SUPPORT: List[Step] = [
    inbound(3.0, "support", "desk", "Customer: where is my order 4412?"),
    hand(2.2, "support", "desk", "Nia, call coming in about an order.", "support", "agent"),
    think(1.8, "support", "agent", "They want an order status..."),
    hand(2.0, "support", "agent", "Theo, can you look up order 4412?", "support", "tools"),
    tool(1.8, "support", "tools", "lookup_order_status('4412')"),
    result(1.8, "support", "tools", "Order 4412 is 'processing'", I),
    hand(1.6, "support", "tools", "It's processing.", "support", "agent"),
    say(2.2, "support", "agent", "Your order 4412 is being processed. I'll keep an eye on it."),
    hand(2.4, "support", "agent", "Vera, please voice this.", "support", "voice"),
    say(1.8, "support", "voice", "Speaking the reply with the browser voice...", W),
    done(2.0, "support", "voice", "Reply played to the customer."),
]

CICD: List[Step] = [
    inbound(5.0, "cicd", "reviewer", "git push to main: 14 files changed."),
    think(1.6, "cicd", "reviewer", "Reading the diff..."),
    say(2.4, "cicd", "reviewer", "Summary: adds order lookup retries. Low risk."),
    hand(2.4, "cicd", "reviewer", "Tess, tests please.", "cicd", "tester"),
    tool(2.0, "cicd", "tester", "locust: 500 requests"),
    result(2.0, "cicd", "tester", "p95 340ms, 0 errors"),
    hand(1.6, "cicd", "tester", "Gate passed. Sasha, scan it.", "cicd", "scanner"),
    tool(2.0, "cicd", "scanner", "trivy image scan + sonar analysis"),
    result(2.2, "cicd", "scanner", "0 critical, 2 medium"),
    hand(1.6, "cicd", "scanner", "Clean enough. Bo, build and push.", "cicd", "builder"),
    tool(2.0, "cicd", "builder", "docker push :4412abc"),
    hand(2.4, "cicd", "builder", "Image is pushed. Rae, you can roll out.", "cicd", "release"),
    say(1.8, "cicd", "release", "I need spare capacity for blue/green. Asking infra.", W),
    hand(1.8, "cicd", "release", "Ira, is there room for a second replica set?", "iac", "operator"),
    say(3.2, "iac", "operator", "Yes, the cluster has headroom. Go ahead.", W),
    hand(1.8, "iac", "operator", "Capacity confirmed, Rae.", "cicd", "release", WT),
    tool(2.0, "cicd", "release", "argo rollouts: shift 20% to green", W),
    result(2.2, "cicd", "release", "green healthy"),
    hand(1.8, "cicd", "release", "Otis, FYI: rollout finished.", "cicd", "oncall"),
    done(1.8, "cicd", "oncall", "Nothing to page. Quiet night."),
]

OBS: List[Step] = [
    say(4.0, "observability", "collector", "Pulling traces from every agent.", W),
    hand(2.0, "observability", "collector", "Sam, anything fresh from the front desk?", "support", "desk"),
    hand(2.0, "observability", "collector", "Nia, I need your LLM traces.", "support", "agent"),
    hand(1.8, "observability", "collector", "Ira, drift scan timings please.", "iac", "operator"),
    hand(1.8, "observability", "collector", "Cody, pipeline traces?", "cicd", "reviewer", W),
    hand(2.0, "observability", "collector", "Otto, route these into the pipeline.", "observability", "otel"),
    tool(1.8, "observability", "otel", "otel: 412 spans/min received"),
    hand(2.0, "observability", "otel", "Sam-P, sample before storing.", "observability", "sampler"),
    say(1.8, "observability", "sampler", "Keeping all errors, 10% of the rest."),
    hand(2.0, "observability", "sampler", "Mira, store these.", "observability", "store"),
    say(1.8, "observability", "store", "Written to the time-series store."),
    hand(1.8, "observability", "store", "Tobi, tokens for this window?", "observability", "tokens"),
    tool(1.8, "observability", "tokens", "sum tokens by agent, env=blue"),
    say(2.0, "observability", "tokens", "Support: 184k tokens. IaC: 96k."),
    hand(1.8, "observability", "tokens", "Cora, price that.", "observability", "cost"),
    say(2.0, "observability", "cost", "About $0.62 this hour. Within budget."),
    hand(1.8, "observability", "cost", "Lena, latency view?", "observability", "latency"),
    say(2.0, "observability", "latency", "Support p95 is 1.9s, mostly model time."),
    hand(1.8, "observability", "latency", "The model call is the slow part. Finn, errors?", "observability", "failures"),
    say(2.0, "observability", "failures", "0.4% failed. Mostly timeouts."),
    hand(1.8, "observability", "failures", "Anya, does that look odd?", "observability", "anomaly"),
    think(2.0, "observability", "anomaly", "Comparing with last week..."),
    say(2.2, "observability", "anomaly", "Model latency is up 30%. Unusual."),
    hand(1.8, "observability", "anomaly", "Sloane, is the SLO at risk?", "observability", "slo"),
    say(2.2, "observability", "slo", "Budget 71% left. Watch it."),
    hand(1.8, "observability", "slo", "Alec, send a heads-up to the support team.", "observability", "alerts"),
    hand(2.0, "observability", "alerts", "Sam, replies are slower than last week.", "support", "desk", W),
    say(2.4, "support", "desk", "Thanks, we'll check the model choice.", W),
    hand(1.8, "observability", "alerts", "Quinn, any quality drop too?", "observability", "quality"),
    say(2.2, "observability", "quality", "Answer quality is steady. 94% pass."),
    hand(1.8, "observability", "quality", "Dana, update the board.", "observability", "dashboard"),
    say(2.0, "observability", "dashboard", "Dashboards refreshed for all agents."),
    hand(1.8, "observability", "dashboard", "Pip, GPU outlook?", "observability", "capacity"),
    hand(2.0, "observability", "capacity", "Ira, will we need another GPU node?", "iac", "operator", W),
    say(2.4, "iac", "operator", "Not this week. I'll flag it if the trend holds."),
    hand(1.8, "observability", "capacity", "Ivy, log this for the weekly notes.", "observability", "scribe"),
    say(2.2, "observability", "scribe", "Noted: model latency spike, no incident."),
    done(2.0, "observability", "scribe", "Report filed."),
]

TRACKS: List[List[Step]] = [IAC, SUPPORT, CICD, OBS]


# People now walk slowly between desks, so the script is slowed to match.
SPEED = 2.0


def demo_seconds() -> float:
    return max(sum(s[0] for s in t) for t in TRACKS) * SPEED


async def _play(track: List[Step]) -> None:
    for delay, team, member, kind, text, state, to in track:
        await asyncio.sleep(delay * SPEED)
        bus.publish(
            AgentEvent(
                team=team, member=member, kind=kind, text=text, state=state,
                to_team=to[0] if to else None, to_member=to[1] if to else None,
                simulated=True,
            )
        )


async def play_demo() -> None:
    await asyncio.gather(*[_play(t) for t in TRACKS])
