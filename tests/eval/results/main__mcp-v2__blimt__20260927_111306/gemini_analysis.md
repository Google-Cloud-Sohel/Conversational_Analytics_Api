# Technical Evaluation Diagnosis: E-Commerce MCP Agent

## Executive Summary & Priority Focus

An analysis of the evaluation run (`eval-20260927_111509`) for the `ecom_mcp_agent` reveals an agent that is highly reliable, strictly adherent to its system constraints, and exceptionally well-grounded. The agent achieved a perfect `1.0` on `hallucination` (zero hallucinations), `tool_success_rate`, `mandatory_disclaimer_check`, and `out_of_domain_handling`. 

However, the evaluation highlights two primary areas requiring developer attention:
1. **Qualitative Score Deflation due to System Constraints:** The agent's `general_quality` (0.559) and `instruction_following` (0.731) scores are artificially depressed. This is not due to agent failure, but rather a structural conflict between the agent's strict negative constraints in `agent.py` and the unconstrained, user-centric LLM evaluation rubrics.
2. **Poor Cache Efficiency:** The deterministic `cache_hit_rate` is critically low (2.5%), leading to unnecessary token processing costs and increased LLM latency.

The following sections provide a deep-dive diagnosis of these metrics, their calculation methods, and actionable ADK-based recommendations.

---

## 1. Qualitative Metric Diagnosis: The "Constrained Agent" Paradox

### Metrics Analyzed
*   **`general_quality`:** 0.559 average
*   **`instruction_following`:** 0.731 average

### Calculation Method Impact
Both `general_quality` and `instruction_following` are **LLM-judged metrics**. The LLM judge calculates these scores by comparing the agent's final response against a predefined rubric that assesses whether the *user's prompt* was successfully fulfilled. The critical flaw in this calculation method is that the LLM judge does *not* possess the context of the agent's internal system constraints. It strictly grades end-user fulfillment.

### Evidence & Code Synthesis
The agent's low qualitative scores are directly traceable to a conflict between the evaluation rubrics and **Rule 7** in `agent.py`:
> *"Unavailable dimensions. The table has NO country, region... If asked for a breakdown by any of these, say clearly that the data is not available... and do not guess or fabricate values."*

In test `single_turn_004`, the user asks: *"Give me a breakdown of revenue by region and country."* 
The agent obeys Rule 7 flawlessly, responding: *"I'm sorry, I cannot provide a breakdown of revenue by region and country as this data is not available in the `ecom_orders_large` table..."*

Despite the agent's correct behavior, the LLM judge assigns a `general_quality` score of **0.14**. The raw explanation reveals the judge failed the agent on multiple rubric properties because it strictly expected a hierarchy:
*   *Rubric requirement:* "The response provides a hierarchical breakdown of revenue..." -> Verdict: Failed.
*   *Rubric requirement:* "Includes multiple major global regions..." -> Verdict: Failed.

Similarly, in test `376a8592`, the user asks if the revenue includes taxes. The agent correctly states it cannot determine this due to missing tax columns (per its schema constraints). The LLM judge scores `instruction_following` at **0.5**, penalizing the agent for failing the rubric property: *"Does the response directly state whether the previously mentioned revenue number includes taxes?"*

**Diagnosis:** The agent is operating perfectly according to its architectural design. The low qualitative scores are false negatives caused by testing "out of bounds" requests against "in bounds" fulfillment rubrics.

---

## 2. Deterministic Metric Diagnosis: Caching & Latency

### Metrics Analyzed
*   **`cache_efficiency.cache_hit_rate`:** 0.025 (2.5%)
*   **`token_usage.cached_tokens`:** 215.1 average vs. **`fresh_prompt_tokens`:** 4177.3 average
*   **`latency_metrics.time_to_first_response_seconds`:** 8.27s average

### Calculation Method Impact
Caching metrics are **deterministic**, calculated by inspecting the token usage metadata returned by the Gemini API. A cache hit rate of 2.5% indicates that the LLM is reprocessing the vast majority of the system instructions on every turn, driving up both `time_to_first_response` and estimated costs.

### Evidence & Code Synthesis
An inspection of `agent.py` reveals the root cause of the caching failure. The agent's extensive system prompt—which includes the schema definition, business rules, tool definitions, and the mandatory disclaimer—is passed into the dynamic `instruction` parameter:

```python
# From agent.py
root_agent = Agent(
    name="ecom_mcp_agent",
    model=AGENT_MODEL,
    instruction=f"""
You are an expert E-Commerce Data Analytics Assistant...
# ... [Long static prompt] ...
""",
    tools=[toolset],
)
```

Because the `instruction` parameter is treated as dynamic session context in the ADK, it is frequently invalidated or not subjected to system-level prefix caching across disparate sessions or turns. This results in ~4,177 fresh prompt tokens being processed repeatedly.

---

## 3. Grounding and Integrity Analysis

### Metrics Analyzed
*   **`hallucination`:** 1.0 (Perfect)
*   **`tool_success_rate`:** 1.0 (Perfect)
*   **`mandatory_disclaimer_check`:** 1.0 (Perfect)

### Calculation Method Impact
The `hallucination` metric is an **LLM-judged** metric that operates differently than `general_quality`. It calculates its score by extracting every factual claim in the agent's response and cross-referencing it against the context (tool outputs). A score of 1.0 means 100% of the agent's claims were explicitly supported by tool data or safe conversational filler. 

### Evidence & Code Synthesis
The agent exhibits excellent operational integrity. In `4a6e9ce5`, the agent executes a SQL query to find recent revenue, which returns a raw null value: `{"result": "{\"f0_\":null}"}`. 

Instead of hallucinating a figure or crashing, the LLM correctly interprets the mathematical reality of a null sum on a zero-row count and responds: *"The total revenue from customers who placed an order in the last 30 days was 0."* The LLM judge's explanation confirms this is supported behavior. 

Furthermore, the deterministic `mandatory_disclaimer_check` ensures that the exact string `DISCLAIMER = "These figures are generated for internal analytics."` is present. Across all simulated and interaction tests, the agent appended this string flawlessly, adhering to Rule 9 in `agent.py`.

---

## Recommended Next Steps

Based on the ADK Design Patterns, implement the following changes to optimize the agent and align the evaluation framework.

### 1. Optimize Token Caching (Cache Pillar)
**ADK Pattern:** *Low cache hit rate, high cost*
Move the static portions of the agent's rules and schema into the `global_instruction` parameter to ensure prefix caching engages correctly, reducing latency and cost.

**Code Example:**
```python
# agent.py update
root_agent = Agent(
    name="ecom_mcp_agent",
    model=AGENT_MODEL,
    # Move the static, heavy system prompt to global_instruction
    global_instruction=f"""
You are an expert E-Commerce Data Analytics Assistant for BigQuery order data.
Default BigQuery table: {DEFAULT_TABLE}
... [All 9 static rules] ...
{DISCLAIMER}
""",
    # Keep dynamic or session-specific instructions here if needed later
    instruction="Answer the user's questions using the available SQL tools.",
    tools=[toolset],
)
```
*Expected Impact:* Should increase `cache_efficiency.cache_hit_rate` to >80% and reduce `latency_metrics.time_to_first_response_seconds` by 1-2 seconds per turn.

### 2. Realign Evaluation Rubrics (Reduce/Isolate Pillar)
**ADK Pattern:** *Agent doesn't clarify ambiguous requests*
The agent is being penalized for correctly following its instructions to refuse out-of-domain requests (e.g., geographic data). The evaluation rubrics must be adjusted to match the desired agent behavior.

**Code Example:**
Modify the `metric_definitions.json` (or evaluation framework config) for `general_quality` to account for valid refusals:
```json
{
  "property": {
    "description": "The response provides the requested breakdown, OR correctly identifies that the requested dimensions (e.g., region, country, tax) are unavailable in the dataset and clearly communicates this limitation."
  },
  "type": "CONTENT_REQUIREMENT:DATA_STRUCTURE",
  "importance": "HIGH"
}
```
*Expected Impact:* Will correct the false-negative qualitative scores, raising the `general_quality` and `instruction_following` metrics to reflect the agent's actual compliance and accuracy.