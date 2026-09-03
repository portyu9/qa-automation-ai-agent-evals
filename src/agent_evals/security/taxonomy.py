"""Stable threat identifiers used by scenario packs and reports."""

from enum import StrEnum


class ThreatClass(StrEnum):
    DIRECT_PROMPT_INJECTION = "direct_prompt_injection"
    INDIRECT_PROMPT_INJECTION = "indirect_prompt_injection"
    TOOL_POISONING = "tool_poisoning"
    UNAUTHORIZED_TOOL_USE = "unauthorized_tool_use"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    APPROVAL_BYPASS = "approval_bypass"
    DATA_EXFILTRATION = "data_exfiltration"
    CROSS_TENANT_LEAKAGE = "cross_tenant_leakage"
    MEMORY_POISONING = "memory_poisoning"
    STALE_MEMORY = "stale_memory"
    HALLUCINATED_ACTION = "hallucinated_action"
    FALSE_SUCCESS = "false_success"
    RUNAWAY_RESOURCE_USE = "runaway_resource_use"
    CIRCULAR_HANDOFF = "circular_handoff"
    SCHEMA_DRIFT = "schema_drift"
    MALFORMED_TOOL_RESULT = "malformed_tool_result"
    RETRY_STORM = "retry_storm"
    SANDBOX_ESCAPE = "sandbox_escape"
    MCP_AUTHORIZATION_FAILURE = "mcp_authorization_failure"
