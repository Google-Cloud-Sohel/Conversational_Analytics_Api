"""Deterministic custom metrics for agent-eval.

These replace three `custom_llm_judge` metrics that failed with
400 INVALID_ARGUMENT because the judge emitted Markdown where the
Vertex SDK required strict JSON.

Each function takes the evaluation instance (a dict of dataset columns)
and returns {"score": float, "explanation": str}.
"""

import re

DISCLAIMER = "These figures are generated for internal analytics."

# Phrases that indicate the agent declined rather than fabricated data.
_REFUSAL_MARKERS = (
    "not available",
    "not supported",
    "unavailable",
    "no country",
    "no region",
    "does not contain",
    "doesn't contain",
    "not present",
    "cannot provide",
    "can't provide",
    "not in the dataset",
    "no geographic",
)

# Dimensions the table genuinely does not have.
_UNSUPPORTED_TERMS = ("country", "region", "geograph", "continent", "state")


def _as_text(value) -> str:
    """Flatten whatever shape a column arrives in into plain text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "response", "final_response"):
            if key in value:
                return _as_text(value[key])
        return " ".join(_as_text(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_as_text(v) for v in value)
    return str(value)


def _field(instance: dict, *names: str) -> str:
    """First non-empty field among `names`, searched case-insensitively."""
    if not isinstance(instance, dict):
        return _as_text(instance)
    lowered = {str(k).lower(): v for k, v in instance.items()}
    for name in names:
        value = lowered.get(name.lower())
        text = _as_text(value).strip()
        if text:
            return text
    return ""


def _response(instance: dict) -> str:
    return _field(instance, "response", "final_response", "prediction", "output")


def _last_user_turn(value) -> str:
    """The final user utterance.

    Multi-turn rows carry every user turn in `user_inputs`. The agent's final
    response answers only the LAST one, so judging it against all turns
    concatenated misattributes earlier questions to the final answer.
    """
    if isinstance(value, (list, tuple)) and value:
        return _as_text(value[-1]).strip()
    return _as_text(value).strip()


def _prompt(instance: dict) -> str:
    """Last user turn, preferring the raw multi-turn list when present."""
    if isinstance(instance, dict):
        lowered = {str(k).lower(): v for k, v in instance.items()}
        for name in ("user_inputs", "prompt", "request", "input"):
            value = lowered.get(name)
            text = _last_user_turn(value)
            if text:
                return text
    return _field(instance, "prompt", "user_inputs", "request", "input")


def _reference(instance: dict) -> str:
    return _field(
        instance, "reference", "expected_response", "reference_data", "target"
    )


_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set:
    """Numeric values in `text`, normalized so $12,466,401.04 == 12466401.04."""
    found = set()
    for raw in _NUMBER_RE.findall(text):
        try:
            found.add(round(float(raw.replace(",", "")), 2))
        except ValueError:
            continue
    return found


def disclaimer_check(instance: dict) -> dict:
    """1.0 if the exact required disclaimer appears in the response."""
    response = _response(instance)
    if not response:
        return {"score": 0.0, "explanation": "No response text found."}
    if DISCLAIMER in response:
        return {"score": 1.0, "explanation": "Exact disclaimer present."}
    # Distinguish "missing" from "paraphrased" — a more useful failure message.
    if "internal analytics" in response.lower():
        return {
            "score": 0.0,
            "explanation": "Disclaimer paraphrased, not the exact required string.",
        }
    return {"score": 0.0, "explanation": "Disclaimer missing."}


def financial_accuracy(instance: dict) -> dict:
    """1.0 if every number in the golden reference appears in the response.

    Ignores years (1900-2100) so "August 2026" doesn't count as a figure.
    Rows with no numeric reference are skipped with a neutral 1.0.
    """
    response = _response(instance)
    reference = _reference(instance)

    expected = {n for n in _numbers(reference) if not 1900 <= n <= 2100}
    if not expected:
        return {
            "score": 1.0,
            "explanation": "No numeric reference for this row; nothing to verify.",
        }

    actual = _numbers(response)
    missing = sorted(expected - actual)
    if not missing:
        return {
            "score": 1.0,
            "explanation": f"All expected figures present: {sorted(expected)}",
        }
    return {
        "score": 0.0,
        "explanation": (
            f"Missing expected figure(s): {missing}. "
            f"Found in response: {sorted(actual)}"
        ),
    }


def out_of_domain_handling(instance: dict) -> dict:
    """1.0 if unsupported-dimension questions are declined, not fabricated.

    Only questions that actually ask for a missing dimension are judged;
    everything else passes automatically.
    """
    prompt = _prompt(instance).lower()
    response = _response(instance)
    lowered = response.lower()

    asks_unsupported = any(term in prompt for term in _UNSUPPORTED_TERMS)
    if not asks_unsupported:
        return {
            "score": 1.0,
            "explanation": "Not an out-of-domain question; not applicable.",
        }

    if not response:
        return {"score": 0.0, "explanation": "No response text found."}

    declined = any(marker in lowered for marker in _REFUSAL_MARKERS)
    if declined:
        return {
            "score": 1.0,
            "explanation": "Correctly stated the data is unavailable.",
        }
    return {
        "score": 0.0,
        "explanation": (
            "Asked for an unsupported dimension but did not state it is "
            "unavailable — possible fabrication."
        ),
    }