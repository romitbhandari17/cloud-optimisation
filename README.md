# Cloudineer Cost Assessment Engine

Reusable, multi-account Python framework for AWS FinOps agents. Phase 1 ships five
agents (Discovery, Cost Analysis, Compute Optimisation, DB Optimisation, Network
Optimisation) behind a common agent contract, so customer N is a config file, not a
code fork.

- **Architecture**: see [`docs/architecture.md`](docs/architecture.md).
- **Source of requirements**: [`docs/context.txt`](docs/context.txt),
  [`docs/context1.txt`](docs/context1.txt), [`docs/context2.txt`](docs/context2.txt).
- **Infra**: see [`terraform/README.md`](terraform/README.md) for the customer
  cross-account role, the central-platform storage layer, and the Step
  Functions + Lambda compute layer.

## Layout

```
src/cloudineer/
  core/            # framework: contract, base agent, context, registry, orchestrator
    tools/         # Tool/ToolRegistry, AWS cross-account session factory, MCP client
    ai/            # optional Bedrock-backed AI fallback
  agents/          # discovery_agent.py, cost_analysis_agent.py, compute_optimisation_agent.py, db_optimisation_agent.py, network_optimisation_agent.py
  reports/         # dashboard_builder.py -> Assessment Dashboard JSON
  cli.py           # `python -m cloudineer.cli run ...`
config/customers/  # one YAML file per customer (account id, role arn, enabled agents)
terraform/         # customer-role/ (customer account) + central-platform/ (Cloudineer account)
tests/             # pytest + moto, no live AWS access required
```

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q

# Run an assessment (uses local/default AWS credentials, no cross-account role needed)
python -m cloudineer.cli run \
  --customer-config config/customers/example-customer.yaml --stub -v
```

For a real customer: apply `terraform/customer-onboarding`, put the resulting `role_arn` and
your chosen `external_id` into a new `config/customers/<id>.yaml`, then run the CLI
without `--stub`.

## Adding a new agent

1. Create `src/cloudineer/agents/<name>_agent.py` implementing `BaseAgent`
   (`name`, `run(ctx) -> AgentResult`).
2. Register it in `core/registry.py::build_default_registry`.
3. Add it to a customer's `enabled_agents` list — no other code changes required.

AI (Bedrock, via `ctx.ai`) is optional and additive: call it only where a deterministic
rule isn't a confident enough signal; always handle a `None` response by falling back
to the rule-based result.
