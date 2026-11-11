# Cloudineer Cost Assessment Engine — Architecture

> Synthesised from `docs/context.txt`, `docs/context1.txt` and `docs/context2.txt`.
> This document defines the architecture for the first product slice of the Cloudineer
> FinOps Agent Platform: a **Cost Assessment Engine** that runs a small set of reusable,
> multi-account agents against a customer's AWS account and produces an **Assessment
> Dashboard**.

## 1. Goal

Build a reusable, customer-independent engine that can be pointed at *any* AWS account
(via cross-account IAM) and produce:

- Cost breakdown
- Potential savings
- Architecture risks
- AI opportunities
- Priority recommendations

The same agent code runs for customer A, B, C, … — only configuration (account id,
regions, excluded tags, enabled agents) changes.

## 2. Phase 1 scope — three agents

| Priority | Agent | Responsibility | Primary implementation |
|---|---|---|---|
| 1 | **Discovery Agent** | Enumerate accounts, regions, services and resources | Boto3 (deterministic) |
| 2 | **Cost Analysis Agent** | Cost Explorer / CUR trends, anomalies, cost-by-service breakdown | Boto3 + rules, AI for narrative explanation |
| 3 | **Compute Optimisation Agent** | CloudWatch utilisation (EC2, ECS, Lambda) + Compute Optimizer → right-sizing findings | Boto3 + rules, AI fallback for ambiguous cases |

Additional agents (ECS/EKS, Database, Storage, Network, Pricing, Non-Prod scheduling,
Savings Validation) are added later as independent, versioned modules without changing
the core framework — this is the reason the framework is built now, generically.

## 3. Guiding principles (from context docs)

1. **Agents are reusable modules, not customer-specific code.** Customer identity,
   account id, regions, thresholds and exclusions live in configuration, never in code.
2. **Python-first, AI as fallback.** Discovery, metric pulls, and rule-based scoring are
   deterministic Python. An LLM (via Bedrock, or any MCP-exposed model) is invoked only
   where reasoning/explanation/judgement adds value (e.g. explaining *why* a cost spike
   happened, or disambiguating a borderline right-sizing call).
3. **Standard agent contract.** Every agent accepts the same `AssessmentRequest` input
   and returns the same `AgentResult` (`agent`, `account_id`, `findings[]`) shape, so the
   orchestrator, dashboard and reporting layer never need agent-specific logic.
4. **Central control plane, customer-side execution via STS.** Cloudineer hosts the
   orchestrator/agents centrally (Option B / hybrid from `context2.txt`). Per-customer
   access is obtained via `sts:AssumeRole` against a read-only
   `CloudineerFinOpsReadOnlyRole` deployed by the customer. No long-lived customer
   credentials are stored.
5. **Two permission profiles.** `Assessment Role` (read-only: Cost Explorer, CloudWatch,
   describe/list APIs, Compute Optimizer) and `Remediation Role` (narrow, explicit,
   approval-gated — out of scope for this phase, modelled but not implemented yet).
6. **Tool-based, not monolithic-agent.** Each agent is a thin orchestration layer over a
   registry of *tools* (Python functions or MCP tool servers). This keeps agents testable
   and lets the same tools be reused by multiple agents (e.g. a `cost_explorer` tool used
   by both the Cost Analysis Agent and, later, the Pricing Optimisation Agent).

## 4. High-level architecture

```
                         ┌───────────────────────────────────────────┐
                         │        Cloudineer Central Platform         │
                         │                                             │
                         │  ┌───────────────┐   ┌────────────────────┐│
                         │  │  Orchestrator  │──▶│   Agent Registry    ││
                         │  │ (core engine)  │   │ (discovery/cost/ec2)││
                         │  └──────┬─────────┘   └────────────────────┘│
                         │         │                                   │
                         │         ▼                                   │
                         │  ┌───────────────┐   ┌────────────────────┐│
                         │  │  Tool Registry │──▶│  MCP tool servers   ││
                         │  │ (local Python  │   │ (optional, external ││
                         │  │   + MCP tools) │   │  tool processes)    ││
                         │  └──────┬─────────┘   └────────────────────┘│
                         │         │                                   │
                         │         ▼                                   │
                         │  ┌───────────────┐   ┌────────────────────┐│
                         │  │ AI Fallback    │   │ Config Store        ││
                         │  │ (Bedrock/LLM)  │   │ (YAML / DynamoDB)   ││
                         │  └───────────────┘   └────────────────────┘│
                         └───────────────────┬─────────────────────────┘
                                             │ sts:AssumeRole
                                             ▼
                         ┌───────────────────────────────────────────┐
                         │        Customer AWS Account                │
                         │  CloudineerFinOpsReadOnlyRole (read-only)  │
                         │  EC2 · RDS · S3 · CloudWatch · Cost Explorer│
                         └───────────────────────────────────────────┘
                                             │
                                             ▼
                         ┌───────────────────────────────────────────┐
                         │           Assessment Dashboard              │
                         │ Cost breakdown · Potential savings ·        │
                         │ Architecture risks · AI opportunities ·     │
                         │ Priority recommendations                    │
                         └───────────────────────────────────────────┘
```

## 5. Compute deployment — Step Functions + Lambda

The orchestrator and agents run as the **Phase 1 compute layer**: one Lambda per
agent, fanned out in parallel by a Step Functions state machine, with a final Lambda
that builds and persists the Assessment Dashboard.

```
EventBridge / manual StartExecution
        │  input: {"customer_config": {...}}
        ▼
┌─────────────────────────── Step Functions: assessment ───────────────────────────┐
│  Parallel                                                                        │
│   ├─ Lambda: discovery-agent         ──▶ AgentResult JSON (Catch → safe fallback) │
│   ├─ Lambda: cost-analysis-agent     ──▶ AgentResult JSON (Catch → safe fallback) │
│   └─ Lambda: compute-optimisation-agent  ──▶ AgentResult JSON (Catch → safe fallback) │
│        │                                                                         │
│        ▼                                                                         │
│  Lambda: dashboard  ──▶ builds Assessment Dashboard, writes to S3 reports bucket  │
└───────────────────────────────────────────────────────────────────────────────────┘
```

Why this and not a single Lambda or a managed agent platform:

- **One Lambda per agent** (`src/cloudineer/handlers/*.py`) means adding agent #4
  only needs a new handler + a new Step Functions branch; existing agents, their
  IAM permissions and their failure modes stay isolated.
- **Step Functions `Catch`** around each branch, *and* a try/except inside every
  handler (`handlers/_common.py::run_agent_handler`), mean one failing region/agent
  never aborts the whole assessment — it surfaces as a normal `AgentResult` with
  `errors` populated, same as the in-process `BaseAgent.safe_run` behaviour.
- **AWS Bedrock AgentCore was evaluated and deliberately deferred.** AgentCore's
  managed agent loop, Gateway (MCP tool exposure) and Identity (credential vending)
  are the right fit once an agent needs multi-step autonomous reasoning over many
  tools (e.g. a future conversational troubleshooting/incident-response agent).
  Phase 1's agents are deterministic Python with occasional AI calls — Step
  Functions + Lambda is simpler, cheaper and more transparent for that shape of
  work, and the `BaseAgent`/`ToolRegistry`/MCP-client abstractions already in
  `core/` are designed so tools can be re-exposed via AgentCore Gateway later
  without rewriting agent logic.

Terraform for this layer lives in `terraform/modules/agents` (Lambdas + layer) and
`terraform/modules/sfn` (state machine), composed by the root `terraform/main.tf`.
`terraform/modules/customer-role` (applied per customer via
`terraform/customer-onboarding`) now supports trusting the compute layer's specific
Lambda execution role ARN instead of the whole Cloudineer account root. See
`terraform/README.md` for the full module layout and deploy sequence, and
`scripts/build_lambda_artifacts.sh` for packaging.

## 6. Core framework components (this repo: `src/cloudineer/core`)

| Module | Purpose |
|---|---|
| `contract.py` | Pydantic models: `AssessmentRequest`, `Finding`, `AgentResult` — the standard agent I/O contract from `context1.txt` §4. |
| `agent.py` | `BaseAgent` abstract class every agent implements (`name`, `run(ctx) -> AgentResult`). |
| `context.py` | `AgentContext` — carries the request, a boto3 `Session` already scoped to the customer account, and the `ToolRegistry`/`AIFallback` handles. |
| `tools/base.py` | `Tool` base class — a named, callable unit of work with a JSON-schema-ish description (keeps the door open for exposing the same tools over MCP). |
| `tools/aws_session.py` | `AWSSessionFactory` — implements the `sts.assume_role` cross-account pattern from `context2.txt` §2, with an in-memory (stub) mode for local/dev use without real AWS access. |
| `tools/mcp_client.py` | Minimal MCP client wrapper so an agent can call tools exposed by an external MCP server (e.g. a shared "AWS cost MCP server") exactly like a local tool. Degrades gracefully (raises a clear error) if the `mcp` package isn't installed — this keeps the framework usable with Python-only tools today, and MCP-ready for tomorrow. |
| `ai/bedrock_client.py` | `AIFallback` — optional Bedrock-backed reasoning step. Every agent calls it through the same `explain()`/`decide()` interface; if Bedrock is unavailable/unconfigured it returns `None` and the agent continues with rule-based output only (AI is strictly a fallback, never a hard dependency). |
| `registry.py` | `AgentRegistry` — maps agent name → class, used by the orchestrator and by configuration (`enabled_agents: [...]`) to enable/disable agents per customer without code changes. |
| `orchestrator.py` | `AssessmentOrchestrator` — loads customer config, builds the `AgentContext`, runs the enabled agents (sequentially in this phase; swappable for Step Functions/async fan-out later), and hands all `AgentResult`s to the dashboard builder. |

`src/cloudineer/agents/` holds the three concrete agents; `src/cloudineer/reports/` holds
the `DashboardBuilder` that turns a list of `AgentResult` into the Assessment Dashboard
JSON (cost breakdown, potential savings, risks, AI opportunities, priority
recommendations) consumed by a future web UI.

## 7. Configuration, not code, per customer

`config/customers/<customer_id>.yaml`:

```yaml
customer_id: customer-001
account_id: "123456789012"
role_arn: "arn:aws:iam::123456789012:role/CloudineerFinOpsReadOnlyRole"
external_id: "cloudineer-customer-001"
regions: ["ap-south-1", "us-east-1"]
environment: ["production", "staging"]
lookback_days: 30
excluded_tags: ["critical", "do-not-modify"]
enabled_agents: ["discovery", "cost-analysis", "compute-optimisation", "db-optimisation"]
mode: assessment
```

Adding a new customer = adding a new YAML file. Disabling an agent = removing it from
`enabled_agents`. No code changes, no forks.

## 8. Dashboard output shape

```json
{
  "customer_id": "customer-001",
  "account_id": "123456789012",
  "generated_at": "2025-01-01T00:00:00Z",
  "cost_breakdown": { "...": "by service/category, from Cost Analysis Agent" },
  "potential_savings": { "total_monthly_usd": 0, "by_agent": {} },
  "architecture_risks": [ "..." ],
  "ai_opportunities": [ "..." ],
  "priority_recommendations": [ "ranked findings across all agents" ]
}
```

## 9. Roadmap alignment

This phase delivers the **engine** half of `context.txt` §8
("Cloudineer Cloud Assessment Engine"): Python + Boto3 discovery → cost analysis →
rule-based + AI recommendations → Assessment Dashboard JSON. The **AWS Engineer
Implementation Playbooks** (approval → execution → validation) and the remaining seven
FinOps agents are explicitly out of scope for this phase and are added as new modules
under `src/cloudineer/agents/` using the same `BaseAgent` contract.
