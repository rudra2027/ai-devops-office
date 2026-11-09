"""
The office floor plan: one cabin per agent, one colleague per internal
component of that agent. Teams marked built=False are described in their
repo's README but have no code yet; their cabins render as "onboarding".
"""

from typing import List

from .models import Member, Team

TEAMS: List[Team] = [
    Team(
        id="iac",
        name="Infrastructure (IaC)",
        tagline="Turns conversations into cloud infrastructure, on any cloud",
        accent="#7c5cff",
        chat_enabled=True,
        members=[
            Member(id="requirements", name="Rhea", role="Requirements Analyst",
                   component="provisioner.requirements -> InfraRequirements"),
            Member(id="architect", name="Arjun", role="Cloud Architect",
                   component="provisioner.architect -> ArchitecturePlan"),
            Member(id="writer", name="Tara", role="Terraform Engineer",
                   component="provisioner.writer -> GeneratedStack"),
            Member(id="reviewer", name="Rex", role="Policy Reviewer",
                   component="provisioner.reviewer -> ReviewReport"),
            Member(id="operator", name="Ira", role="Plan & Apply Operator",
                   component="provisioner.operator / app.apply_loop"),
            Member(id="drift", name="Dev", role="Drift Scout",
                   component="app.drift_scan + app.policy"),
        ],
    ),
    Team(
        id="support",
        name="Customer Support",
        tagline="Live call agent: LLM, tools and voice",
        accent="#18a999",
        chat_enabled=True,
        members=[
            Member(id="desk", name="Sam", role="Front Desk", component="app.main /chat"),
            Member(id="agent", name="Nia", role="Support Agent (LLM)", component="app.agent"),
            Member(id="tools", name="Theo", role="Tools Clerk", component="app.tools"),
            Member(id="voice", name="Vera", role="Voice Desk", component="browser STT (Gemini 3.5 Flash) + Edge speech"),
        ],
    ),
    Team(
        id="cicd",
        name="CI/CD",
        tagline="Review, scan, ship and roll out",
        accent="#e8913a",
        chat_enabled=True,
        members=[
            Member(id="reviewer", name="Cody", role="Code Reviewer (LLM)", component="planned"),
            Member(id="tester", name="Tess", role="Test & Load Gate", component="planned"),
            Member(id="scanner", name="Sasha", role="Security Scanner", component="planned: Trivy + SonarQube"),
            Member(id="builder", name="Bo", role="Image Builder", component="planned: ECR push"),
            Member(id="release", name="Rae", role="Release Manager", component="planned: ArgoCD / Rollouts"),
            Member(id="oncall", name="Otis", role="On-call Pager", component="planned: Telegram"),
        ],
    ),
    Team(
        id="observability",
        name="Observability",
        tagline="LLM performance and evaluation across agents",
        accent="#3b9ae1",
        chat_enabled=True,
        wide=True,
        members=[
            Member(id="collector", name="Cleo", role="Trace Collector", component="planned: LangSmith API client"),
            Member(id="otel", name="Otto", role="OTel Pipeline", component="planned: OpenTelemetry collector"),
            Member(id="sampler", name="Sam-P", role="Trace Sampler", component="planned: sampling policy"),
            Member(id="tokens", name="Tobi", role="Token Accountant", component="planned: token usage per agent/env"),
            Member(id="cost", name="Cora", role="Cost Estimator", component="planned: tokens x model price"),
            Member(id="latency", name="Lena", role="Latency Analyst", component="planned: p50/p95/p99"),
            Member(id="failures", name="Finn", role="Failure-rate Analyst", component="planned: error budgets"),
            Member(id="quality", name="Quinn", role="Quality Evaluator", component="planned: LLM output evals"),
            Member(id="anomaly", name="Anya", role="Anomaly Detector", component="planned"),
            Member(id="slo", name="Sloane", role="SLO Keeper", component="planned"),
            Member(id="store", name="Mira", role="Metrics Store", component="planned: time-series DB"),
            Member(id="dashboard", name="Dana", role="Dashboard Builder", component="planned: per-agent views"),
            Member(id="alerts", name="Alec", role="Alert Router", component="planned: Telegram / pager"),
            Member(id="capacity", name="Pip", role="Capacity Planner", component="planned: GPU / node forecasts"),
            Member(id="scribe", name="Ivy", role="Incident Scribe", component="planned: timelines and post-mortems"),
        ],
    ),
]

TEAM_IDS = {t.id for t in TEAMS}
MEMBER_IDS = {(t.id, m.id) for t in TEAMS for m in t.members}
