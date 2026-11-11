# Cloudineer Terraform

```
terraform/
  main.tf, variables.tf, outputs.tf   # root: Cloudineer's central platform (one account)
  modules/
    s3/              # assessment reports bucket
    dynamodb/         # customer registry table
    agents/           # Lambda layer + one Lambda per agent + dashboard Lambda
    sfn/               # Step Functions state machine wiring the agent Lambdas together
    customer-role/     # reusable: the read-only IAM role a CUSTOMER deploys
  customer-onboarding/  # thin root wrapping modules/customer-role (customer's own account)
```

Modules are composed, not copy-pasted: the root `terraform/` applies `modules/s3`,
`modules/dynamodb`, `modules/agents` and `modules/sfn` together against Cloudineer's
account; `terraform/customer-onboarding` applies `modules/customer-role` against a
customer's account. Adding a new agent (e.g. RDS/database optimisation) means
extending `modules/agents` (new Lambda) and `modules/sfn` (new state machine
branch) — the storage and customer-role modules are untouched.

## Deploy order

### 1. Central platform (once, Cloudineer's account)

```bash
./scripts/build_lambda_artifacts.sh   # builds dist/cloudineer_function.zip + dist/cloudineer_layer.zip

cd terraform
terraform init
terraform apply
```

Note the `state_machine_arn`, `lambda_execution_role_arn`, `reports_bucket_name` and
`customer_registry_table_name` outputs.

### 2. Onboarding a new customer (customer's account)

```bash
cd terraform/customer-onboarding
terraform init
terraform apply \
  -var="cloudineer_account_id=<CLOUDINEER_ACCOUNT_ID>" \
  -var="external_id=cloudineer-<customer_id>" \
  -var='trusted_principal_arns=["<lambda_execution_role_arn from step 1>"]'
```

Copy the `role_arn` output (and the `external_id` you chose) into
`config/customers/<customer_id>.yaml`.

### 3. Run an assessment

```bash
aws stepfunctions start-execution \
  --state-machine-arn <state_machine_arn from step 1> \
  --input '{"customer_config": {...contents of config/customers/<customer_id>.yaml as JSON...}}'
```

The dashboard JSON is returned as the execution output and written to
`s3://<reports_bucket_name>/<customer_id>/<timestamp>.json`.

Rebuild and redeploy whenever `src/cloudineer` changes:
`./scripts/build_lambda_artifacts.sh && (cd terraform && terraform apply)`.
