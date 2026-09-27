# Deep Technical Diagnosis: E-Commerce Analytics Agent

## Executive Summary
This report provides a technical diagnosis of the `ecom_orders_agent` based on evaluation run `eval-20260927_112207`. The agent demonstrates exceptional reliability, perfect data grounding, and strict adherence to business constraints (scoring 1.0 across hallucination, financial metric accuracy, and mandatory disclaimer checks). 

However, the evaluation reveals two primary areas requiring immediate engineering attention:
1. **Performance and Efficiency:** The agent suffers from high turn latency (averaging ~31 seconds) and a 0.0% cache hit rate, driving up API costs and degrading the user experience.
2. **Evaluation Misalignment:** Low scores in `general_quality` (0.67) and `instruction_following` (0.77) are false negatives. The LLM-judged rubrics heavily penalize the agent for adhering to explicit system prompt constraints (e.g., refusing to provide unavailable tax or geographic data).

---

## 1. Analysis of Calculation Methods & Metric Interpretation
To accurately interpret the evaluation, it is critical to distinguish between how the underlying metrics are calculated (referencing ADK evaluation standards):

*   **Deterministic Metrics (`token_usage`, `latency_metrics`, `tool_utilization`):** These are exact, code-level measurements captured via ADK framework hooks during the interaction. A `latency_metrics.tool_latency_seconds` score of 21.47s is an absolute measurement of network and execution time for the `query_conversational_analytics` function in `agent.py`.
*   **LLM-Judged Metrics (`general_quality`, `hallucination`, `instruction_following`):** These are calculated by a secondary LLM evaluator assessing the agent's output against predefined rubrics (as seen in the `rubric_verdicts`). Because these are subjective, conflicts between the agent's system prompt (e.g., "Answer briefly") and the evaluator's rubric (e.g., "The response provides a breakdown of the individual transactions") will artificially deflate scores.

---

## 2. Deep Dive: Grounding, Constraints, and Accuracy (The Successes)

### 2.1 Perfect Grounding and Financial Accuracy
*   **Metrics:** `hallucination` (1.0), `financial_metric_accuracy` (1.0), `out_of_domain_handling` (1.0). 
*   **Calculation Impact:** `hallucination` is an LLM-judged metric that verifies if every claim in the response maps to the retrieved context. `financial_metric_accuracy` is an LLM/deterministic hybrid checking for the exact presence of numerical values.
*   **Evidence:** Across all interactions, the agent scored a perfect 1.0 on `hallucination`. For example, in question `3cb18504`, the user asked, "And what is the total sales amount for all of them?". The tool returned `12466401.039999923`, and the agent outputted `$12,466,401.04`. The LLM judge confirmed every sentence was supported by the context.
*   **Code Diagnosis:** The logic in `_extract_text_from_chunk` within `agent.py` successfully parses structured `data` results from the BigQuery Data Agent into a readable string format (`"Query result:\n" + "\n".join(formatted_rows)`), ensuring the LLM receives clean, structured facts to base its answers on.

### 2.2 Strict Instruction Adherence vs. Rubric Misalignment
*   **Metrics:** `mandatory_disclaimer_check` (1.0), `general_quality` (0.67), `instruction_following` (0.77).
*   **Evidence:** The agent perfectly executed the `CRITICAL INSTRUCTION` in `agent.py` to append "These figures are generated for internal analytics." to every response (scoring 1.0 on the deterministic disclaimer check). However, `general_quality` dropped to 0.33 on question `single_turn_004` ("Give me a breakdown of revenue by region and country."). 
*   **Code Diagnosis:** The agent's `instruction` string in `agent.py` explicitly dictates: *"the data has NO country, region... say plainly that it is unavailable"*. The agent correctly outputted: *"I cannot break down revenue by region and country, as these dimensions are not available..."*. The LLM judge, blind to the agent's system constraints, penalized the agent because the `CONTENT_REQUIREMENT:REVENUE_BREAKDOWN` rubric expected a structured breakdown. **This indicates a flaw in the evaluation rubrics, not the agent.**

---

## 3. Deep Dive: Performance and Efficiency Bottlenecks

### 3.1 Zero Context Caching
*   **Metrics:** `cache_efficiency.cache_hit_rate` (0.0), `token_usage.total_fresh_prompt_tokens` (2075.2 avg).
*   **Calculation Impact:** Deterministically calculated by measuring the ratio of cached tokens to total prompt tokens billed by the Vertex/Gemini API.
*   **Evidence:** The evaluation summary shows exactly 0.0 cached tokens across all runs, meaning the API is recalculating the entire system prompt and tool schema on every single turn.
*   **Code Diagnosis:** In `agent.py`, the `root_agent` instantiation uses the `instruction` argument for its large, static system prompt and business logic. Because `instruction` is treated as dynamic context by the ADK, it bypasses the Gemini context caching layer.

### 3.2 High Latency and Multi-Step Over-Reasoning
*   **Metrics:** `latency_metrics.total_latency_seconds` (30.89s avg), `latency_metrics.tool_latency_seconds` (21.47s avg), `token_usage.llm_calls` (4.4 avg).
*   **Calculation Impact:** Deterministically calculated by timing the total session and the execution time of the `query_conversational_analytics` function.
*   **Evidence:** In question `4a6e9ce5` ("What was the total revenue from those recent customers?"), total latency spiked to 64.9 seconds with 6 LLM calls and 49 seconds of tool latency. The agent struggled to negotiate the "last 30 days" criteria, eventually realizing the calendar date didn't match the dataset date, resulting in excessive LLM reasoning loops.
*   **Code Diagnosis:** 
    1. The BigQuery Conversational Analytics API is inherently slow (averaging ~21s per response). 
    2. Because the tool signature simply takes a `query: str` without explicit boundaries on what the LLM should ask, the LLM engages in extensive internal reasoning (`thinking_metrics.reasoning_ratio` of 0.67) and multiple conversational turns with the data agent to figure out the schema.

---

## 4. Recommended Next Steps

Based on the ADK Design Patterns reference, the following architectural and code optimizations are recommended to address the identified bottlenecks.

### Recommendation 1: Enable Context Caching for System Prompts
**Pillar:** Cache
**ADK Pattern:** Low cache hit rate, high cost
**Diagnosis:** The agent's large system prompt is currently assigned to the dynamic `instruction` parameter, resulting in a 0% cache hit rate.
**Code Change:** Move the static rules to `global_instruction` in `agent.py`.
```python
root_agent = Agent(
    name="ecom_orders_agent",
    model="gemini-2.5-flash",
    description="E-Commerce Analytics Assistant powered by BigQuery.",
    # Move static, heavy text to global_instruction to enable prefix caching
    global_instruction="""
    You are an expert E-Commerce Data Analytics Assistant.
    
    Business definitions:
    - 'Revenue' or 'Total Sales' is the sum of 'order_amount'.
    - 'Customers' is the distinct count of 'customer_id'.
    - 'Active Orders' excludes orders where 'status' is 'Cancelled' or 'Refunded'.
    
    CRITICAL INSTRUCTION: Append this exact disclaimer as the last line of
    EVERY response: "These figures are generated for internal analytics."
    """,
    # Keep dynamic or session-specific instructions here (if any)
    instruction="Answer briefly: the figure first, then any caveat."
)
```
**Expected Impact:** Will increase `cache_efficiency.cache_hit_rate` from 0.0 to ~80-90% on multi-turn conversations, reducing `token_usage.estimated_cost_usd` and moderately improving `latency_metrics.time_to_first_response_seconds`.

### Recommendation 2: Restructure Tool Output for Error Handling
**Pillar:** Offload
**ADK Pattern:** Tool returns string errors instead of raising exceptions
**Diagnosis:** The `query_conversational_analytics` tool traps exceptions and returns a string (`"CRITICAL ERROR:..."`). This forces the LLM to parse text to determine success or failure, leading to edge-case hallucinations or excessive reasoning loops.
**Code Change:** Refactor the tool in `agent.py` to return a structured dictionary.
```python
def query_conversational_analytics(query: str, tool_context: ToolContext) -> dict:
    # ... existing setup code ...
    try:
        stream = client.chat(request=request)
        # ... processing stream ...
        result_text = "\n\n".join(full_response) if full_response else "No data returned."
        tool_context.state["latest_query_result"] = result_text
        
        return {"status": "success", "data": result_text}

    except Exception as e:
        print(f"\n[API ERROR EXPOSED] DataChatServiceClient failed: {e}\n")
        # Return structured dict so the LLM explicitly understands the failure
        return {
            "status": "error", 
            "error_message": f"CRITICAL ERROR: {str(e)}. Do NOT retry. Output this exact error message."
        }
```
**Expected Impact:** Will reduce `token_usage.llm_calls` and `latency_metrics.llm_latency_seconds` by preventing the LLM from attempting to parse or retry string-based failure messages, cleanly offloading state management.

### Recommendation 3: Add Explicit Tool Limitations
**Pillar:** Reduce
**ADK Pattern:** LLM retries failed tools in loops
**Diagnosis:** The agent required 6 LLM calls for a single question (`4a6e9ce5`) because it didn't know the dataset date boundaries.
**Code Change:** Update the docstring of `query_conversational_analytics` to inject boundary awareness directly into the tool schema.
```python
def query_conversational_analytics(query: str, tool_context: ToolContext) -> dict:
    """Queries the BigQuery Conversational Analytics Data Agent.

    **KNOWN LIMITATIONS:**
    - The dataset has NO country, region, state or city columns.
    - The dataset has no tax, cost, or margin columns.
    - If asking for "recent" or "last 30 days", clarify with the user or specify the latest dataset date to avoid querying future calendar dates.
    """
```
**Expected Impact:** Will drastically lower `token_usage.llm_calls` (currently 4.4 avg) and `latency_metrics.total_latency_seconds` by preventing the LLM from executing tools to search for unavailable data dimensions.