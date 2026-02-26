"""
ToolSelector Agent - Decides which security tool to run.

Responsible for:
- Analyzing current findings and context
- Selecting the most appropriate tool based on capabilities and metadata
- Configuring tool parameters based on stealth/speed requirements
"""

import logging
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.services.ai.agents.base import (
    ActionRisk,
    Agent,
    AgentContext,
    AgentResult,
    AgentRole,
    ToolAction,
)
from app.services.tools.models import RiskLevel, ToolCapability, ToolCategory
from app.services.tools.registry import get_registry
from app.services.ai.prompts import TOOL_SELECTION_PROMPT

logger = logging.getLogger("spectra.ai.agents.tool_selector")


# --- Input/Output Models ---


class ToolSelectorInput(BaseModel):
    """Input for the ToolSelector agent."""

    current_phase: str = Field("discovery", description="Current assessment phase")
    target: str = Field(..., description="Current target")
    target_type: str = Field("ip", description="Type of target: ip, domain, url")
    known_services: list[dict[str, Any]] = Field(
        default_factory=list, description="Services discovered so far"
    )
    known_vulns: list[dict[str, Any]] = Field(
        default_factory=list, description="Vulnerabilities found so far"
    )
    tools_already_run: list[str] = Field(
        default_factory=list, description="Tools that have already been run"
    )
    user_preference: str | None = Field(
        None, description="User's tool preference if any"
    )
    required_capability: str | None = Field(
        None, description="Specific capability needed"
    )
    tags_filter: list[str] = Field(
        default_factory=list, description="Filter tools by tags"
    )


class ToolSelectorOutput(ToolAction):
    """Output from the ToolSelector agent."""

    action_type: str = "run_tool"
    alternatives: list[str] = Field(
        default_factory=list, description="Alternative tools that could be used"
    )
    skip_reason: str | None = Field(
        default=None, description="Reason if no tool selected"
    )


# --- ToolSelector Implementation ---


class ToolSelectorAgent(Agent[ToolSelectorInput, ToolSelectorOutput]):
    """
    Agent that selects the most appropriate security tool based on context.

    Uses tool metadata, capabilities, and LLM reasoning to:
    1. Filter applicable tools based on phase, capabilities, and target type
    2. Rank tools based on findings, tags, and stealth requirements
    3. Configure tool parameters appropriately
    """

    role: ClassVar[AgentRole] = AgentRole.TOOL_SELECTOR
    name: ClassVar[str] = "ToolSelector"
    description: ClassVar[str] = (
        "Analyzes context and selects the optimal security tool to run"
    )

    # Phase to tool category mapping (primary)
    PHASE_CATEGORIES = {
        "scope": [],  # Scope phase doesn't use scanning tools
        "discovery": [ToolCategory.DISCOVERY, ToolCategory.NETWORK],
        "enumeration": [ToolCategory.ENUMERATION, ToolCategory.WEB],
        "vulnerability": [ToolCategory.VULNERABILITY, ToolCategory.WEB],
        "exploitation": [ToolCategory.EXPLOITATION],
        "post_exploitation": [ToolCategory.POST_EXPLOITATION, ToolCategory.SECRETS],
        "reporting": [],  # Reporting phase doesn't use scanning tools
    }

    # Phase to recommended capabilities mapping
    PHASE_CAPABILITIES = {
        "scope": [],  # No tool capabilities for scope definition
        "discovery": [
            ToolCapability.PORT_SCAN,
            ToolCapability.SERVICE_DETECTION,
            ToolCapability.HOST_DISCOVERY,
            ToolCapability.OS_DETECTION,
        ],
        "enumeration": [
            ToolCapability.SUBDOMAIN_ENUM,
            ToolCapability.DIRECTORY_BRUTE,
            ToolCapability.DNS_ENUM,
            ToolCapability.WEB_FINGERPRINT,
            ToolCapability.CMS_DETECTION,
            ToolCapability.VHOST_DISCOVERY,
        ],
        "vulnerability": [
            ToolCapability.VULN_SCAN,
            ToolCapability.CVE_DETECTION,
            ToolCapability.MISCONFIG_DETECTION,
            ToolCapability.WAF_DETECTION,
        ],
        "exploitation": [
            ToolCapability.SQL_INJECTION,
            ToolCapability.COMMAND_INJECTION,
            ToolCapability.BRUTE_FORCE,
            ToolCapability.EXPLOIT_FRAMEWORK,
            ToolCapability.AUTH_BYPASS,
        ],
        "post_exploitation": [
            ToolCapability.PRIVILEGE_ESCALATION,
            ToolCapability.LATERAL_MOVEMENT,
            ToolCapability.SECRET_SCAN,
            ToolCapability.CREDENTIAL_HARVEST,
        ],
        "reporting": [],  # No tool capabilities for reporting
    }

    async def execute(
        self,
        context: AgentContext,
        input_data: ToolSelectorInput,
    ) -> AgentResult:
        """Select the best tool for the current situation."""
        try:
            registry = get_registry()

            # Sync tool status from Redis (set by tools container worker)
            try:
                await registry.sync_status_from_redis()
            except Exception:
                pass  # Non-critical, tools will auto-install anyway

            # Get all registered tools (not just available - they auto-install)
            all_tools = registry.list_tools()

            # Filter out already-run tools, but keep the preferred tool if specified
            candidates = [
                t
                for t in all_tools
                if t.config.id not in input_data.tools_already_run
                or (
                    input_data.user_preference
                    and t.config.id == input_data.user_preference
                )
            ]

            if not candidates:
                # All tools for this phase have been run
                return AgentResult(
                    success=True,
                    action=ToolSelectorOutput(
                        tool_name="",
                        target=input_data.target,
                        confidence=1.0,
                        risk_level=ActionRisk.LOW,
                        reasoning="All applicable tools for this phase have been executed",
                        skip_reason="phase_complete",
                        estimated_duration=0,
                    ),
                )

            # Use LLM to select the best tool with rich metadata
            # We no longer hardcode phase filters - we let the LLM decide based on tool descriptions
            action = await self._select_with_llm(context, input_data, candidates)

            # Validate and enrich the selection
            selected_tool = registry.get_tool(action.tool_name)
            if selected_tool:
                # Apply stealth mode adjustments from tool config
                if context.stealth_mode:
                    action.tool_args = self._apply_stealth_settings(
                        selected_tool, action.tool_args
                    )

                # Set risk level from tool metadata
                action.risk_level = self._map_risk_level(
                    selected_tool.config.metadata.risk_level
                )

                # Validate arguments against registry schema if possible, or basic types
                self._validate_tool_args(selected_tool, action.tool_args)

                # Set estimated duration from tool config if not provided or too low
                # Use min_timeout as a threshold to detect if LLM defaulted to 60s
                if (
                    action.estimated_duration
                    <= selected_tool.config.execution.min_timeout
                ):
                    action.estimated_duration = selected_tool.config.execution.timeout

            return AgentResult(
                success=bool(action.tool_name),
                action=action,
            )

        except Exception as e:
            logger.error("ToolSelector failed: %s", e)
            return AgentResult(
                success=False,
                error=str(e),
            )

    def _map_risk_level(self, tool_risk: RiskLevel) -> ActionRisk:
        """Map tool risk level to action risk level."""
        mapping = {
            RiskLevel.PASSIVE: ActionRisk.LOW,
            RiskLevel.LOW: ActionRisk.LOW,
            RiskLevel.MEDIUM: ActionRisk.MEDIUM,
            RiskLevel.HIGH: ActionRisk.HIGH,
            RiskLevel.CRITICAL: ActionRisk.CRITICAL,
        }
        return mapping.get(tool_risk, ActionRisk.LOW)

    async def _select_with_llm(
        self,
        context: AgentContext,
        input_data: ToolSelectorInput,
        available_tools: list[Any],  # List[RegisteredTool]
    ) -> ToolSelectorOutput:
        """Use LLM to select and configure the best tool with rich metadata and RAG context."""
        from app.services.ai.knowledge import (
            get_methodology_guidance,
            get_tool_usage_context,
        )

        # If user specified a tool preference, check if it's available and use it directly
        if input_data.user_preference:
            preferred_tool = next(
                (
                    t
                    for t in available_tools
                    if t.config.id == input_data.user_preference
                ),
                None,
            )
            if preferred_tool:
                logger.info(
                    "Using specified tool preference: %s", input_data.user_preference
                )
                return ToolSelectorOutput(
                    tool_name=preferred_tool.config.id,
                    target=input_data.target,
                    tool_args={},
                    confidence=0.95,
                    risk_level=self._map_risk_level(
                        preferred_tool.config.metadata.risk_level
                    ),
                    reasoning=f"Using specified tool: {preferred_tool.config.name}",
                    alternatives=[],
                    estimated_duration=preferred_tool.config.execution.timeout,
                )
            else:
                logger.warning(
                    "Preferred tool %s not available, selecting alternative",
                    input_data.user_preference,
                )

        # Build comprehensive tool descriptions for the prompt
        tool_descriptions = []
        for t in available_tools:
            tool_descriptions.append(t.config.get_ai_summary())

        tools_text = "\n\n".join(tool_descriptions)

        # Build context about what we know
        services_info = ""
        if input_data.known_services:
            services_info = "\n**Discovered services:**\n" + "\n".join(
                f"- Port {s.get('port', '?')}/{s.get('protocol', 'tcp')}: {s.get('service', 'unknown')} {s.get('product', '')} {s.get('version', '')}"
                for s in input_data.known_services[:10]
            )

        vulns_info = ""
        if input_data.known_vulns:
            vulns_info = "\n**Known vulnerabilities:**\n" + "\n".join(
                f"- [{v.get('severity', 'unknown').upper()}] {v.get('name', 'Unknown')}"
                + (f" (CVE: {v.get('cve_id')})" if v.get("cve_id") else "")
                for v in input_data.known_vulns[:5]
            )

        already_run_info = ""
        if input_data.tools_already_run:
            already_run_info = f"\n**Tools already executed:** {', '.join(input_data.tools_already_run)}"

        # Build preferred tool info with strong emphasis
        preferred_tool_info = ""
        if input_data.user_preference:
            preferred_tool_info = f"\n**[IMPORTANT] REQUIRED TOOL: {input_data.user_preference}** - You MUST select this tool if available.\n"

        # Get RAG context using centralized service
        rag_context = await get_tool_usage_context(
            input_data.current_phase, input_data.known_services
        )

        # Get methodology guidance using centralized service
        methodology_context = get_methodology_guidance(input_data.current_phase)

        # Get learned context from persistent memory
        memory_context = ""
        try:
            from app.services.ai.memory import get_memory, detect_os_from_services

            memory = get_memory()
            # Detect OS from known services
            os_family = None
            if input_data.known_services:
                os_family = detect_os_from_services(input_data.known_services)
                if os_family == "unknown":
                    os_family = None
            # Get service-specific recommendations from past missions
            primary_service = None
            if input_data.known_services:
                primary_service = input_data.known_services[0].get("service")
            memory_context = memory.get_context_for_prompt(
                service=primary_service,
                os_family=os_family,
            )
        except Exception:
            pass

        # Get playbook recommendations
        playbook_context = ""
        try:
            from app.services.ai.playbook import get_playbook_engine

            engine = get_playbook_engine()
            playbook_context = engine.get_grounded_prompt_context(
                input_data.known_services,
                input_data.tools_already_run,
            )
        except Exception:
            pass

        # Get CVE intelligence for discovered services (live + builtin)
        cve_context = ""
        try:
            from app.services.ai.cve_intel import (
                get_cve_context_for_services,
                get_cve_context_for_services_live,
            )

            if input_data.known_services:
                # Try live NVD lookup first, fall back to builtin
                try:
                    cve_context = await get_cve_context_for_services_live(
                        input_data.known_services
                    )
                except Exception:
                    cve_context = get_cve_context_for_services(
                        input_data.known_services
                    )
        except Exception:
            pass

        # Generate smart wordlist context for brute-force and directory tools
        wordlist_context = ""
        try:
            from app.services.ai.wordlists import (
                generate_credential_list,
                generate_tech_wordlist,
            )

            if input_data.known_services:
                for svc in input_data.known_services[:3]:
                    service = svc.get("service", "")
                    product = svc.get("product")
                    if service:
                        creds = generate_credential_list(service, product)
                        wordlist_context += (
                            f"\n**Default credentials for {service}**: "
                            f"users=[{','.join(creds['users'][:5])}] "
                            f"passwords=[{','.join(creds['passwords'][:5])}]"
                        )
        except Exception:
            pass

        # Combine all learned context
        learned_context = "\n\n".join(
            filter(None, [memory_context, playbook_context, cve_context, wordlist_context])
        )
        if learned_context:
            learned_context = (
                f"\n--- Learned from Past Missions ---\n{learned_context}\n"
            )

        prompt = TOOL_SELECTION_PROMPT.format(
            target=input_data.target,
            target_type=input_data.target_type,
            phase=input_data.current_phase,
            stealth_mode="Yes - minimize detection, prefer passive/slow scans"
            if context.stealth_mode
            else "No - normal operation",
            preferred_tool_info=preferred_tool_info,
            services_info=services_info,
            vulns_info=vulns_info,
            already_run_info=already_run_info,
            methodology_context=methodology_context,
            rag_context=rag_context + learned_context,
            tools_text=tools_text,
        )

        system_prompt = self._build_system_prompt(context)

        try:
            return await self.llm.generate_structured(
                prompt=prompt,
                response_model=ToolSelectorOutput,
                system_prompt=system_prompt,
                temperature=0.3,
            )
        except Exception as e:
            logger.warning("LLM selection failed, using smart fallback: %s", e)
            return self._smart_fallback_selection(input_data, available_tools)

    def _smart_fallback_selection(
        self,
        input_data: ToolSelectorInput,
        available_tools: list[Any],
    ) -> ToolSelectorOutput:
        """Smart fallback when LLM fails - uses tool metadata for ranking."""
        # Score tools based on relevance
        scored_tools = []
        phase_caps = self.PHASE_CAPABILITIES.get(input_data.current_phase, [])

        for tool in available_tools:
            score = 0
            config = tool.config

            # Score by capability match
            matching_caps = sum(
                1 for cap in phase_caps if cap in config.metadata.capabilities
            )
            score += matching_caps * 10

            # Score by prerequisites (prefer tools with no unmet prereqs)
            prereqs_met = all(
                p in input_data.tools_already_run for p in config.metadata.prerequisites
            )
            if prereqs_met:
                score += 20

            # Prefer lower risk tools in general (safety)
            risk_scores = {
                RiskLevel.PASSIVE: 5,
                RiskLevel.LOW: 4,
                RiskLevel.MEDIUM: 3,
                RiskLevel.HIGH: 2,
                RiskLevel.CRITICAL: 1,
            }
            score += risk_scores.get(config.metadata.risk_level, 0)

            scored_tools.append((score, tool))

        # Sort by score descending
        scored_tools.sort(key=lambda x: x[0], reverse=True)

        selected_tool = scored_tools[0][1] if scored_tools else available_tools[0]

        return ToolSelectorOutput(
            tool_name=selected_tool.config.id,
            target=input_data.target,
            tool_args={},
            confidence=0.6,
            risk_level=self._map_risk_level(selected_tool.config.metadata.risk_level),
            reasoning=f"Fallback selection based on capability matching: {selected_tool.config.name}",
            alternatives=[
                t.config.id
                for t in available_tools[1:4]
                if t.config.id != selected_tool.config.id
            ],
            estimated_duration=selected_tool.config.execution.timeout,
        )

    def _apply_stealth_settings(
        self,
        tool: Any,  # RegisteredTool
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply stealth settings from tool config or fallback defaults."""
        # Strict overrides for stealth mode
        stealth_args = args.copy()

        # Apply tool-specific stealth configuration if available
        if tool.config.stealth:
            if tool.config.stealth.rate_limit:
                stealth_args["rate"] = tool.config.stealth.rate_limit
            if tool.config.stealth.delay_ms:
                stealth_args["delay"] = tool.config.stealth.delay_ms
            if tool.config.stealth.extra_args:
                stealth_args.update(tool.config.stealth.extra_args)

        # Hardcoded fallbacks for common tools to ENSURE safety
        # Using a mapping for cleaner extensibility (KISS)
        tool_name = tool.config.id

        stealth_overrides = {
            "nmap": {
                "-T": "1",  # Paranoid
                "--scan-delay": "1s",
                "-T4": None,  # Remove aggressive
                "-T5": None,  # Remove aggressive
            },
            "naabu": {"rate": 50},
            "ffuf": {"rate": 5, "delay": 1000},
            "nuclei": {"rate-limit": 5},
        }

        if tool_name in stealth_overrides:
            for key, val in stealth_overrides[tool_name].items():
                if val is None:
                    stealth_args.pop(key, None)
                else:
                    stealth_args[key] = val

        return stealth_args

    def _validate_tool_args(self, tool: Any, args: dict[str, Any]) -> None:
        """Sanity check generated arguments."""
        # First pass: sanitize malformed values
        keys_to_remove = []
        for key, val in list(args.items()):
            if val is None:
                keys_to_remove.append(key)
                continue

            val_str = str(val)

            # Remove Python list syntax that LLM might generate
            # e.g., "-t ['cves/']" -> "" (invalid), "['*']" -> "" (invalid)
            if "[" in val_str or "]" in val_str:
                logger.warning(
                    f"Removing malformed list syntax from arg {key}: {val_str}"
                )
                import re

                items = re.findall(r"'([^']+)'", val_str)
                if items:
                    valid_items = [
                        i
                        for i in items
                        if i and i not in ("", "*", "/") and not i.startswith("-")
                    ]
                    if valid_items:
                        args[key] = ",".join(valid_items)
                    else:
                        keys_to_remove.append(key)
                else:
                    keys_to_remove.append(key)

            # Remove flag prefix that LLM might incorrectly include
            # e.g., "-t cves/" -> "cves/", "-w /path" -> "/path", "-tcves/" -> "cves/"
            elif val_str.startswith("-"):
                import re

                # Try to extract the actual value after the flag
                # Pattern: -<letter(s)> optionally followed by space, then the value
                match = re.match(r"^-\w+\s*(.*)$", val_str)
                if match:
                    clean_val = match.group(1).strip()
                    if clean_val:
                        logger.warning(
                            f"Removing flag prefix from arg {key}: {val_str} -> {clean_val}"
                        )
                        args[key] = clean_val
                    else:
                        # Value was just "-t" with no actual value - remove it
                        logger.warning(f"Removing empty flag arg {key}={val_str}")
                        keys_to_remove.append(key)
                else:
                    # Just a flag like "-v" - remove it
                    logger.warning(f"Removing arg that is just a flag: {key}={val_str}")
                    keys_to_remove.append(key)

        for key in keys_to_remove:
            args.pop(key, None)

        # Check port arguments are integers or valid ranges
        for key in ["port", "ports", "p"]:
            if key in args:
                val = args[key]
                if (
                    isinstance(val, str)
                    and not val.replace(",", "").replace("-", "").isdigit()
                ):
                    # Attempt to fix strict comma spacing e.g. "80, 443" -> "80,443"
                    args[key] = val.replace(" ", "")

        # Ensure rate limits are integers
        for key in ["rate", "threads", "concurrency"]:
            if key in args:
                try:
                    args[key] = int(args[key])
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid integer for {key}: {args[key]}, using default"
                    )
                    args.pop(key)

        # Apply argument modifiers from tool configuration
        if tool.config.execution.arg_modifiers:
            for arg_name, modifier in tool.config.execution.arg_modifiers.items():
                # Check for aliases (e.g., "port", "ports", "p")
                target_key = None
                if arg_name in args:
                    target_key = arg_name

                # If explicitly checking for aliases in the modifier config could be added here,
                # but for now we assume the config key matches the argument name or we check common variants if needed.
                # Let's check common variants if not found directly
                if not target_key:
                    for variant in [arg_name, f"{arg_name}s", arg_name[:-1]]:
                        if variant in args:
                            target_key = variant
                            break

                if target_key:
                    val = str(args[target_key]).strip()
                    param_config = modifier

                    # Apply separator if list-like string
                    separator = param_config.get("separator")
                    if separator and " " in val and separator != " ":
                        # "80 443" -> "80,443"
                        val = val.replace(" ", separator)
                        args[target_key] = val

                    # Apply prefix (with space after flag-style prefixes)
                    prefix = param_config.get("prefix")
                    if prefix and not val.startswith(prefix):
                        # Add space after prefix if it looks like a flag (starts with -)
                        if prefix.startswith("-") and not prefix.endswith(" "):
                            args[target_key] = f"{prefix} {val}"
                        else:
                            args[target_key] = f"{prefix}{val}"
