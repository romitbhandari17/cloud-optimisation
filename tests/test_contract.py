from cloudineer.core.contract import AgentResult, AssessmentRequest, Finding, Risk


def test_assessment_request_defaults():
    req = AssessmentRequest(customer_id="c1", account_id="123456789012")
    assert req.regions == ["us-east-1"]
    assert req.lookback_days == 30
    assert req.mode.value == "assessment"


def test_agent_result_total_savings():
    result = AgentResult(
        agent="compute-optimisation",
        account_id="123456789012",
        findings=[
            Finding(
                resource_id="i-1",
                finding="Idle",
                recommendation="Stop",
                estimated_monthly_savings=100,
                risk=Risk.MEDIUM,
            ),
            Finding(
                resource_id="i-2",
                finding="Underutilised",
                recommendation="Downsize",
                estimated_monthly_savings=50,
                risk=Risk.LOW,
            ),
        ],
    )
    assert result.total_estimated_monthly_savings == 150
