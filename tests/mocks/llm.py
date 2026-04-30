"""Mock LLM clients for deterministic testing."""

import logging
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel
from pydantic.fields import PydanticUndefined

from spectra_ai.llm import LLMClient, LLMResponse

logger = logging.getLogger("spectra.services.ai.llm")

T = TypeVar("T", bound=BaseModel)


class MockLLMClient(LLMClient):
    """Mock LLM client for deterministic testing."""

    provider = "mock"

    def __init__(
        self,
        responses: list[str] | None = None,
        structured_responses: dict[str, Any] | None = None,
    ):
        """
        Initialize mock client.

        Args:
            responses: List of text responses to return in order.
            structured_responses: Dict mapping Pydantic model names to response data.
        """
        self.responses = responses or ["Mock response"]
        self.structured_responses = structured_responses or {}
        self._call_count = 0
        self.call_history: list[dict[str, Any]] = []

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> LLMResponse:
        """Return mock response."""
        self.call_history.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout": timeout,
            }
        )

        response_idx = self._call_count % len(self.responses)
        self._call_count += 1

        return LLMResponse(
            content=self.responses[response_idx],
            model="mock-model",
            provider=self.provider,
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            raw={},
        )

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> T:
        """Return mock structured response."""
        self.call_history.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "response_model": response_model.__name__,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout": timeout,
            }
        )

        model_name = response_model.__name__
        if model_name in self.structured_responses:
            return response_model.model_validate(self.structured_responses[model_name])

        # Generate default response from schema
        return self._generate_default(response_model)

    def _generate_default(self, response_model: type[T]) -> T:
        """Generate a default instance of a Pydantic model."""
        model_fields = response_model.model_fields
        schema = response_model.model_json_schema()
        props = schema.get("properties", {})
        defs = schema.get("$defs", {})

        data = {}
        for prop_name, field_info in model_fields.items():
            if field_info.default is not PydanticUndefined and field_info.default is not None:
                data[prop_name] = field_info.default
                continue

            annotation = field_info.annotation
            if isinstance(annotation, type) and issubclass(annotation, Enum):
                data[prop_name] = next(iter(annotation))
                continue

            prop_info = props.get(prop_name, {})
            # Check for enum via anyOf or $ref
            enum_vals = prop_info.get("enum")
            if not enum_vals:
                # Check $ref to enum definition
                ref = (
                    prop_info.get("$ref") or prop_info.get("allOf", [{}])[0].get("$ref")
                    if prop_info.get("allOf")
                    else None
                )
                if ref and isinstance(ref, str):
                    ref_name = ref.split("/")[-1]
                    ref_def = defs.get(ref_name, {})
                    enum_vals = ref_def.get("enum")
                # Check anyOf for enum
                if not enum_vals and "anyOf" in prop_info:
                    for option in prop_info["anyOf"]:
                        if "enum" in option:
                            enum_vals = option["enum"]
                            break
                        if "$ref" in option:
                            ref_name = option["$ref"].split("/")[-1]
                            ref_def = defs.get(ref_name, {})
                            if "enum" in ref_def:
                                enum_vals = ref_def["enum"]
                                break
            if enum_vals:
                data[prop_name] = enum_vals[0]
                continue

            prop_type = prop_info.get("type", "string")
            if prop_type == "string":
                data[prop_name] = f"mock_{prop_name}"
            elif prop_type == "integer":
                data[prop_name] = 0
            elif prop_type == "number":
                data[prop_name] = 0.0
            elif prop_type == "boolean":
                data[prop_name] = False
            elif prop_type == "array":
                data[prop_name] = []
            elif prop_type == "object":
                data[prop_name] = {}
            else:
                data[prop_name] = None

        return response_model.model_validate(data)

    async def health_check(self) -> bool:
        """Always returns True for mock client."""
        return True

    def reset(self):
        """Reset call count and history."""
        self._call_count = 0
        self.call_history = []


class PentestMockLLMClient(MockLLMClient):
    """Mock LLM that returns realistic pentest responses based on prompt keywords."""

    provider = "mock"

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> LLMResponse:
        """Return context-aware pentest mock responses."""
        self.call_history.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout": timeout,
            }
        )
        self._call_count += 1

        content = self._get_pentest_response(prompt, system_prompt or "")
        return LLMResponse(
            content=content,
            model="mock-pentest",
            provider=self.provider,
            usage={"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
            raw={},
        )

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> T:
        """Return realistic structured responses for pentest models."""
        self.call_history.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "response_model": response_model.__name__,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout": timeout,
            }
        )
        self._call_count += 1

        model_name = response_model.__name__

        # Check custom responses first
        if model_name in self.structured_responses:
            return response_model.model_validate(self.structured_responses[model_name])

        # Return pentest-aware defaults
        data = self._get_pentest_structured(model_name, prompt)
        if data:
            try:
                return response_model.model_validate(data)
            except Exception as e:
                logger.debug("Mock LLM validation failed: %s", e)

        return self._generate_default(response_model)

    def _get_pentest_response(self, prompt: str, system_prompt: str) -> str:
        """Generate context-aware text response."""
        prompt_lower = (prompt + " " + system_prompt).lower()

        if "scope" in prompt_lower or "target" in prompt_lower:
            return "Target is in scope. Proceeding with reconnaissance."
        elif "nmap" in prompt_lower or "scan" in prompt_lower:
            return (
                "Based on the scan results, the target has open ports 22 (SSH), 80 (HTTP), "
                "and 443 (HTTPS). The HTTP server appears to be Apache with PHP enabled. "
                "Recommend running nikto and dirb/dirsearch for web enumeration."
            )
        elif "vulnerability" in prompt_lower or "vuln" in prompt_lower:
            return (
                "Several vulnerabilities identified: 1) Apache server version disclosure (Info), "
                "2) phpinfo() page exposed at /info.php (Medium), 3) Directory listing enabled (Low), "
                "4) Backup configuration file at /backup/config.bak containing credentials (High), "
                "5) Default admin credentials on /admin/ (Critical)"
            )
        elif "exploit" in prompt_lower:
            return (
                "Recommend testing default credentials on admin panel (admin:admin123). "
                "Also check the backup config file for database credentials. "
                "For SSH, test weak credentials (root:toor)."
            )
        elif "report" in prompt_lower or "debrief" in prompt_lower:
            return (
                "Assessment complete. Found 5 findings: 1 Critical (default credentials), "
                "1 High (credential exposure), 1 Medium (information disclosure), "
                "2 Low (config issues). Recommend immediate password changes and removing exposed files."
            )
        elif "safety" in prompt_lower or "approve" in prompt_lower:
            return "Action is within scope and poses no risk to availability. Approved."
        elif "tool" in prompt_lower or "select" in prompt_lower or "recommend" in prompt_lower:
            return (
                "Recommend running: 1) nmap for port discovery, 2) whatweb for technology fingerprinting, "
                "3) nikto for web vulnerability scanning, 4) dirsearch for directory enumeration"
            )
        elif "analyze" in prompt_lower or "result" in prompt_lower or "output" in prompt_lower:
            return (
                "Analysis of tool output shows multiple interesting findings. Open ports detected. "
                "Web technologies identified. Several potential vulnerabilities found that warrant "
                "further investigation."
            )
        else:
            return (
                "Proceeding with the next phase of the assessment. Current findings suggest "
                "the target has several areas of concern that need further investigation."
            )

    def _get_pentest_structured(self, model_name: str, prompt: str) -> dict | None:
        """Return pentest-aware structured data for known models."""
        prompt_lower = prompt.lower()

        if "ScopeAction" in model_name or "scope" in model_name.lower():
            return {
                "action_type": "define_scope",
                "confidence": 0.95,
                "risk_level": "low",
                "reasoning": "Target parsed and validated",
                "targets": [],
                "exclusions": [],
                "total_hosts": 1,
                "warnings": [],
            }

        if "ToolSelection" in model_name or "tool" in model_name.lower():
            if "recon" in prompt_lower or "discover" in prompt_lower:
                return {
                    "tool_name": "nmap",
                    "arguments": "-sV -sC -T4",
                    "reasoning": "Port scan with service/version detection for initial recon",
                    "confidence": 0.9,
                }
            return {
                "tool_name": "nikto",
                "arguments": "",
                "reasoning": "Web vulnerability scanner for HTTP services",
                "confidence": 0.85,
            }

        if "Safety" in model_name or "safety" in model_name.lower():
            return {
                "approved": True,
                "reasoning": "Action is within defined scope",
                "risk_level": "low",
                "concerns": [],
            }

        # VoteResponse - consensus voting
        if "Vote" in model_name or "vote" in model_name.lower():
            return {
                "decision": "approve",
                "confidence": 0.85,
                "reasoning": "Action appears safe and within mission scope",
                "concerns": [],
            }

        if "Finding" in model_name or "finding" in model_name.lower():
            return {
                "title": "Service detected on target",
                "severity": "info",
                "description": "Mock finding from automated analysis",
                "confidence": 0.8,
            }

        if "Controller" in model_name or "Phase" in model_name or "Decision" in model_name:
            return {
                "next_phase": "reconnaissance",
                "reasoning": "Continue with reconnaissance to gather more information",
                "tasks": ["run_nmap", "run_whatweb"],
                "confidence": 0.85,
            }

        # MissionPlan - the controller's plan output
        if "MissionPlan" in model_name:
            return {
                "action_type": "mission_plan",
                "confidence": 0.85,
                "risk_level": "low",
                "reasoning": "Comprehensive assessment plan covering recon through reporting",
                "mission_type": "full_assessment",
                "current_phase": "discovery",
                "estimated_duration_minutes": 45,
                "requires_approval": False,
                "tasks": [
                    {
                        "task_id": "task_1",
                        "description": "Port scan and service discovery",
                        "agent_type": "tool_executor",
                        "phase": "discovery",
                        "priority": 1,
                        "dependencies": [],
                        "parameters": {"tool": "nmap", "args": "-sV -sC -T4"},
                    },
                    {
                        "task_id": "task_2",
                        "description": "Web technology fingerprinting",
                        "agent_type": "tool_executor",
                        "phase": "enumeration",
                        "priority": 2,
                        "dependencies": ["task_1"],
                        "parameters": {"tool": "whatweb"},
                    },
                    {
                        "task_id": "task_3",
                        "description": "Web vulnerability scanning",
                        "agent_type": "tool_executor",
                        "phase": "vulnerability",
                        "priority": 3,
                        "dependencies": ["task_2"],
                        "parameters": {"tool": "nikto"},
                    },
                    {
                        "task_id": "task_4",
                        "description": "Directory and file enumeration",
                        "agent_type": "tool_executor",
                        "phase": "enumeration",
                        "priority": 2,
                        "dependencies": ["task_1"],
                        "parameters": {"tool": "dirsearch"},
                    },
                    {
                        "task_id": "task_5",
                        "description": "Generate final report",
                        "agent_type": "reporter",
                        "phase": "reporting",
                        "priority": 5,
                        "dependencies": ["task_3", "task_4"],
                        "parameters": {},
                    },
                ],
            }

        # PhaseTransition
        if "PhaseTransition" in model_name:
            return {
                "action_type": "phase_transition",
                "confidence": 0.9,
                "risk_level": "low",
                "reasoning": "Phase objectives complete, transitioning to next phase",
                "from_phase": "discovery",
                "to_phase": "enumeration",
                "summary": "Discovery phase completed. Identified open services.",
                "findings_count": 0,
            }

        # SteeringAction
        if "Steering" in model_name:
            return {
                "action_type": "steering",
                "confidence": 0.8,
                "risk_level": "low",
                "reasoning": "Adjusting mission parameters per steering input",
            }

        # DebriefReport
        if "Debrief" in model_name or "Report" in model_name:
            return {
                "action_type": "debrief",
                "confidence": 0.9,
                "risk_level": "low",
                "reasoning": "Assessment complete",
                "summary": "Security assessment completed against target.",
                "key_findings": ["Services discovered", "Web application analyzed"],
                "risk_rating": "medium",
                "recommendations": ["Review service configurations", "Apply security patches"],
            }

        return None
