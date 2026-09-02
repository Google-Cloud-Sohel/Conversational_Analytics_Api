from google.adk.evaluation.eval_case import Invocation, ConversationScenario
from google.adk.evaluation.eval_metrics import EvalMetric
from google.adk.evaluation.evaluator import EvaluationResult, PerInvocationResult, EvalStatus


def disclaimer_check(
    eval_metric: EvalMetric,
    actual_invocations: list[Invocation],
    expected_invocations: list[Invocation] | None = None,
    conversation_scenario: ConversationScenario | None = None,
) -> EvaluationResult:
    """Custom metric: ensures every actual response contains the disclaimer."""
    disclaimer = "these figures are generated for internal analytics"
    per_invocation_results = []
    scores = []

    for inv in actual_invocations:
        text = ""
        if inv.final_response and inv.final_response.parts:
            text = " ".join(p.text or "" for p in inv.final_response.parts)
        passed = disclaimer in text.lower()
        score = 1.0 if passed else 0.0
        scores.append(score)
        per_invocation_results.append(
            PerInvocationResult(
                actual_invocation=inv,
                score=score,
                eval_status=EvalStatus.PASSED if passed else EvalStatus.FAILED,
            )
        )

    overall_score = sum(scores) / len(scores) if scores else 0.0
    return EvaluationResult(
        overall_score=overall_score,
        overall_eval_status=(
            EvalStatus.PASSED if overall_score >= (eval_metric.threshold or 1.0)
            else EvalStatus.FAILED
        ),
        per_invocation_results=per_invocation_results,
    )