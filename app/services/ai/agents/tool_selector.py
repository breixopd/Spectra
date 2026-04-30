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
    ParallelToolAction,
    ToolAction,
)
from app.services.ai.agents.registry import register_agent
from app.services.ai.errors import LLMParseError
from app.services.ai.prompts import TOOL_SELECTION_PROMPT
from app.services.ai.sanitizer import sanitize_for_prompt
from app.services.tools.registry import get_registry
from spectra_domain.enums import RiskLevel
from spectra_tools_core.models import RegisteredTool, ToolCapability, ToolCategory

logger = logging.getLogger(__name__)


# --- Input/Output Models ---


class ToolSelectorInput(BaseModel):
    """Input for the ToolSelector agent."""

    current_phase: str = Field("discovery", description="Current assessment phase")
    target: str = Field(..., description="Current target")
    target_type: str = Field("ip", description="Type of target: ip, domain, url")
    known_services: list[dict[str, Any]] = Field(default_factory=list, description="Services discovered so far")
    known_vulns: list[dict[str, Any]] = Field(default_factory=list, description="Vulnerabilities found so far")
    tools_already_run: list[str] = Field(default_factory=list, description="Tools that have already been run")
    user_preference: str | None = Field(None, description="User's tool preference if any")
    required_capability: str | None = Field(None, description="Specific capability needed")
    tags_filter: list[str] = Field(default_factory=list, description="Filter tools by tags")


class ToolSelectorOutput(ToolAction):
    """Output from the ToolSelector agent."""

    action_type: str = "run_tool"
    alternatives: list[str] = Field(default_factory=list, description="Alternative tools that could be used")
    skip_reason: str | None = Field(default=None, description="Reason if no tool selected")


# --- ToolSelector Implementation ---


@register_agent
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
    description: ClassVar[str] = "Analyzes context and selects the optimal security tool to run"
    enable_reflection: ClassVar[bool] = True
    reflection_threshold: ClassVar[float] = 0.7

    # Pre-defined groups of tools safe to run in parallel
    PARALLEL_TOOL_GROUPS: ClassVar[dict[str, list[str]]] = {
        # Recon phase: these tools gather complementary info
        "initial_recon": ["nmap", "naabu"],
        "web_fingerprint": ["whatweb", "nikto", "httpx"],
        "web_directory": ["gobuster", "dirsearch", "ffuf"],
        "subdomain_enum": ["subfinder", "amass"],
        # Vuln scanning phase
        "web_vuln_scan": ["nuclei", "nikto"],
        # SMB enumeration
        "smb_enum": ["enum4linux", "crackmapexec"],
    }

    # Deterministic quick-select for known service/phase combinations
    QUICK_SELECT: ClassVar[dict[tuple[str, str], list[str]]] = {
        ("http", "recon"): ["whatweb", "dirsearch", "nikto"],
        ("http", "vuln_scan"): ["nuclei", "sqlmap"],
        ("http", "vulnerability"): ["nuclei", "sqlmap"],
        ("https", "recon"): ["whatweb", "testssl", "dirsearch"],
        ("smb", "recon"): ["enum4linux", "crackmapexec"],
        ("ssh", "recon"): ["nmap"],
        ("ssh", "exploitation"): ["hydra"],
        ("ftp", "recon"): ["nmap"],
        ("ftp", "exploitation"): ["hydra", "metasploit"],
        ("dns", "recon"): ["subfinder", "amass"],
        ("mysql", "exploitation"): ["hydra", "sqlmap"],
        ("wordpress", "recon"): ["wpscan"],
        ("kerberos", "recon"): ["kerbrute"],
    }

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

    def _should_parallelize(self, context: AgentContext) -> bool:
        """Check whether parallel execution is appropriate for current context."""
        if context.stealth_mode:
            return False
        return not context.max_concurrency < 2

    def select_parallel_tools(
        self,
        context: AgentContext,
        input_data: ToolSelectorInput,
        available_tool_ids: set[str],
    ) -> ParallelToolAction | None:
        """Return a ParallelToolAction if a suitable parallel group applies.

        Returns None when parallelisation doesn't apply, letting the caller
        fall through to single-tool selection.
        """
        if not self._should_parallelize(context):
            return None

        for group_name, group_tools in self.PARALLEL_TOOL_GROUPS.items():
            # Filter to tools that are available and not yet run
            candidates = [t for t in group_tools if t in available_tool_ids and t not in input_data.tools_already_run]
            if len(candidates) < 2:
                continue

            # Build individual ToolActions
            tool_actions = [
                ToolAction(
                    tool_name=tool_id,
                    target=input_data.target,
                    tool_args={},
                    confidence=0.80,
                    risk_level=ActionRisk.LOW,
                    reasoning=f"Parallel group '{group_name}'",
                    estimated_duration=120,
                )
                for tool_id in candidates
            ]

            return ParallelToolAction(
                tools=tool_actions,
                max_concurrency=min(len(tool_actions), context.max_concurrency),
                confidence=0.80,
                risk_level=ActionRisk.LOW,
                reasoning=f"Parallel execution of group '{group_name}': {', '.join(candidates)}",
            )

        return None

    def _quick_select(self, service: str, phase: str, already_run: list[str]) -> list[str] | None:
        """Deterministic tool selection for known service/phase combos.

        Returns tool IDs not already run, or None to fall through to LLM.
        """
        for (svc, ph), tools in self.QUICK_SELECT.items():
            if svc in service.lower() and phase == ph:
                remaining = [t for t in tools if t not in already_run]
                return remaining if remaining else None
        return None

    async def execute(
        self,
        context: AgentContext,
        input_data: ToolSelectorInput,
    ) -> AgentResult:
        """Select the best tool for the current situation."""
        try:
            registry = get_registry()

            # Sync tool status from cache (set by tools container worker)
            try:
                await registry.sync_status_from_cache()
            except (OSError, RuntimeError, TypeError) as e:
                logger.debug("Tool status sync failed: %s", e)

            # Get all registered tools (not just available - they auto-install)
            all_tools = registry.list_tools()

            # Filter out already-run tools, but keep the preferred tool if specified
            candidates = [
                t
                for t in all_tools
                if t.config.id not in input_data.tools_already_run
                or (input_data.user_preference and t.config.id == input_data.user_preference)
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

            # Parallel selection: check if a parallel tool group applies
            if not input_data.user_preference:
                available_ids = {t.config.id for t in candidates}
                parallel = self.select_parallel_tools(context, input_data, available_ids)
                if parallel is not None:
                    logger.info(
                        "Parallel selection: %s",
                        [t.tool_name for t in parallel.tools],
                    )
                    return AgentResult(success=True, action=parallel)

            # Quick-select: deterministic tool selection if possible (skip LLM)
            if not input_data.user_preference and input_data.known_services:
                primary_svc = input_data.known_services[0].get("service", "")
                quick = self._quick_select(
                    primary_svc,
                    input_data.current_phase,
                    input_data.tools_already_run,
                )
                if quick:
                    # Find the first quick-select tool that exists in candidates
                    matched = None
                    for tool_id in quick:
                        matched = next((t for t in candidates if t.config.id == tool_id), None)
                        if matched:
                            break

                    if matched:
                        logger.info(
                            "Quick-select: %s for %s/%s", matched.config.id, primary_svc, input_data.current_phase
                        )
                        action = ToolSelectorOutput(
                            tool_name=matched.config.id,
                            target=input_data.target,
                            tool_args={},
                            confidence=0.85,
                            risk_level=self._map_risk_level(matched.config.metadata.risk_level),
                            reasoning=f"Deterministic selection for {primary_svc}/{input_data.current_phase}",
                            alternatives=quick[1:],
                            estimated_duration=matched.config.execution.timeout,
                        )
                        return AgentResult(success=True, action=action)

            # Use LLM to select the best tool with rich metadata
            # We no longer hardcode phase filters - we let the LLM decide based on tool descriptions
            action = await self._select_with_llm(context, input_data, candidates)

            # Validate and enrich the selection
            selected_tool = registry.get_tool(action.tool_name)
            if not selected_tool and action.tool_name:
                # LLM hallucinated a tool name - try fuzzy match
                available_ids = [t.config.id for t in all_tools]
                matches = [
                    t
                    for t in available_ids
                    if action.tool_name.lower() in t.lower() or t.lower() in action.tool_name.lower()
                ]
                if matches:
                    logger.warning(
                        "LLM suggested non-existent tool '%s', using closest match '%s'",
                        action.tool_name,
                        matches[0],
                    )
                    action.tool_name = matches[0]
                    selected_tool = registry.get_tool(action.tool_name)
                else:
                    raise LLMParseError(
                        agent=self.name,
                        raw_response=f"Unknown tool selected by LLM: {action.tool_name}",
                    )

            if selected_tool:
                # Apply stealth mode adjustments from tool config
                if context.stealth_mode:
                    action.tool_args = self._apply_stealth_settings(selected_tool, action.tool_args)

                # Set risk level from tool metadata
                action.risk_level = self._map_risk_level(selected_tool.config.metadata.risk_level)

                # Validate arguments against registry schema if possible, or basic types
                self._validate_tool_args(selected_tool, action.tool_args)

                # Set estimated duration from tool config if not provided or too low
                # Use min_timeout as a threshold to detect if LLM defaulted to 60s
                if action.estimated_duration <= selected_tool.config.execution.min_timeout:
                    action.estimated_duration = selected_tool.config.execution.timeout

            return AgentResult(
                success=bool(action.tool_name),
                action=action,
            )

        except (OSError, RuntimeError, ValueError) as e:
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
                (t for t in available_tools if t.config.id == input_data.user_preference),
                None,
            )
            if preferred_tool:
                logger.info("Using specified tool preference: %s", input_data.user_preference)
                return ToolSelectorOutput(
                    tool_name=preferred_tool.config.id,
                    target=input_data.target,
                    tool_args={},
                    confidence=0.95,
                    risk_level=self._map_risk_level(preferred_tool.config.metadata.risk_level),
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
            services_info = sanitize_for_prompt(services_info, field_name="services_info")

        vulns_info = ""
        if input_data.known_vulns:
            vulns_info = "\n**Known vulnerabilities:**\n" + "\n".join(
                f"- [{v.get('severity', 'unknown').upper()}] {v.get('name', 'Unknown')}"
                + (f" (CVE: {v.get('cve_id')})" if v.get("cve_id") else "")
                for v in input_data.known_vulns[:5]
            )
            vulns_info = sanitize_for_prompt(vulns_info, field_name="known_vulns")

        already_run_info = ""
        if input_data.tools_already_run:
            already_run_info = f"\n**Tools already executed:** {', '.join(input_data.tools_already_run)}"

        # Build preferred tool info with strong emphasis
        preferred_tool_info = ""
        if input_data.user_preference:
            preferred_tool_info = f"\n**[IMPORTANT] REQUIRED TOOL: {input_data.user_preference}** - You MUST select this tool if available.\n"

        # Get RAG context using centralized service
        rag_context = await get_tool_usage_context(input_data.current_phase, input_data.known_services)

        # Get methodology guidance using centralized service
        methodology_context = get_methodology_guidance(input_data.current_phase)

        # Get learned context from persistent memory
        memory_context = ""
        try:
            from app.services.ai.memory import detect_os_from_services, get_memory

            memory = get_memory(context.user_id)
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
        except (KeyError, ValueError, RuntimeError) as e:
            logger.debug("Memory context fetch failed: %s", e)

        # Get playbook recommendations
        playbook_context = ""
        try:
            from app.services.ai.playbook import get_playbook_engine

            engine = get_playbook_engine()
            playbook_context = engine.get_grounded_prompt_context(
                input_data.known_services,
                input_data.tools_already_run,
            )
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug("Playbook context fetch failed: %s", e)

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
                    cve_context = await get_cve_context_for_services_live(input_data.known_services)
                except (OSError, RuntimeError, ValueError, TimeoutError):
                    cve_context = get_cve_context_for_services(input_data.known_services)
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug("CVE context fetch failed: %s", e)

        # Generate smart wordlist context for brute-force and directory tools
        wordlist_context = ""
        try:
            from app.services.ai.wordlists import (
                generate_credential_list,
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
        except (KeyError, ValueError, RuntimeError) as e:
            logger.debug("Wordlist context fetch failed: %s", e)

        # Combine all learned context
        learned_context = "\n\n".join(filter(None, [memory_context, playbook_context, cve_context, wordlist_context]))

        from app.services.ai.context import ContextManager, ContextSection, Priority

        task_text = TOOL_SELECTION_PROMPT.format(
            target=sanitize_for_prompt(input_data.target, field_name="target"),
            target_type=input_data.target_type,
            phase=input_data.current_phase,
            stealth_mode="Yes - minimize detection, prefer passive/slow scans"
            if context.stealth_mode
            else "No - normal operation",
            preferred_tool_info=preferred_tool_info,
            services_info=services_info,
            vulns_info=vulns_info,
            already_run_info=already_run_info,
            methodology_context="",
            rag_context="",
            tools_text="",
        )

        ctx = ContextManager(max_context_tokens=6000)
        prompt = ctx.build(
            [
                ContextSection("task", task_text, Priority.CRITICAL),
                ContextSection("tools", tools_text, Priority.HIGH, max_tokens=800),
                ContextSection("methodology", methodology_context, Priority.LOW, max_tokens=400),
                ContextSection("learned", learned_context, Priority.MEDIUM, max_tokens=500),
                ContextSection("rag", rag_context, Priority.LOW, max_tokens=400),
            ]
        )

        system_prompt = self._build_system_prompt(context)

        try:
            return await self._llm_generate_structured(
                prompt=prompt,
                response_model=ToolSelectorOutput,
                system_prompt=system_prompt,
                temperature=0.3,
            )
        except (OSError, RuntimeError, ValueError, TimeoutError) as e:
            raise LLMParseError(agent=self.name, raw_response=str(e)) from e

    def _apply_stealth_settings(
        self,
        tool: RegisteredTool,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply strict stealth-mode overrides."""
        stealth_args = args.copy()

        stealth_args["-T"] = "1"
        stealth_args["--scan-delay"] = "1s"
        stealth_args.pop("--min-rate", None)
        stealth_args.pop("--rate", None)

        # Apply tool-specific stealth configuration if available
        if tool.config.stealth:
            if tool.config.stealth.rate_limit:
                stealth_args["rate"] = tool.config.stealth.rate_limit
            if tool.config.stealth.delay_ms:
                stealth_args["delay"] = tool.config.stealth.delay_ms
            if tool.config.stealth.extra_args:
                stealth_args.update(tool.config.stealth.extra_args)

        return stealth_args

    def _validate_tool_args(self, tool: RegisteredTool, args: dict[str, Any]) -> None:
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
                logger.warning("Removing malformed list syntax from arg %s: %s", key, val_str)
                import re

                items = re.findall(r"'([^']+)'", val_str)
                if items:
                    valid_items = [i for i in items if i and i not in ("", "*", "/") and not i.startswith("-")]
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
                            "Removing flag prefix from arg %s: %s -> %s",
                            key,
                            val_str,
                            clean_val,
                        )
                        args[key] = clean_val
                    else:
                        # Value was just "-t" with no actual value - remove it
                        logger.warning("Removing empty flag arg %s=%s", key, val_str)
                        keys_to_remove.append(key)
                else:
                    # Just a flag like "-v" - remove it
                    logger.warning("Removing arg that is just a flag: %s=%s", key, val_str)
                    keys_to_remove.append(key)

        for key in keys_to_remove:
            args.pop(key, None)

        # Check port arguments are integers or valid ranges
        for key in ["port", "ports", "p"]:
            if key in args:
                val = args[key]
                if isinstance(val, str) and not val.replace(",", "").replace("-", "").isdigit():
                    # Attempt to fix strict comma spacing e.g. "80, 443" -> "80,443"
                    args[key] = val.replace(" ", "")

        # Ensure rate limits are integers
        for key in ["rate", "threads", "concurrency"]:
            if key in args:
                try:
                    args[key] = int(args[key])
                except (ValueError, TypeError):
                    logger.warning("Invalid integer for %s: %s, using default", key, args[key])
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
