"""
POC Service.

Orchestrates the creation and verification of custom POCs.
"""

import logging

from spectra_ai_core.agents.base import AgentContext
from spectra_ai_core.agents.poc_developer import POCDeveloperAgent, POCDeveloperInput
from spectra_ai_core.capabilities import Capability, CapabilityRequest, require_capability
from spectra_ai_core.consensus import QualityGate, VotingSystem
from spectra_ai_core.llm import LLMClient
from spectra_common.config import settings
from spectra_contracts.poc import POCMetadata, POCRequest, POCResult
from spectra_infra.shell.relay_client import shell_relay_client
from spectra_mission.artifact_workspace import MissionArtifactWorkspace
from spectra_persistence.database import async_session_maker
from spectra_persistence.models.audit_log import AuditEventType
from spectra_system.audit import log_event as audit_log_event
from spectra_tools.service import StandaloneMissionAdapter, ToolExecutionService

logger = logging.getLogger(__name__)


class POCService:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self.developer_agent = POCDeveloperAgent(llm_client)
        self.consensus = VotingSystem(llm_client)
        self.tool_service = ToolExecutionService(llm_client)

    async def generate_and_execute_poc(
        self,
        context: AgentContext,
        request: POCRequest,
    ) -> POCResult:
        """
        Full lifecycle: Generate -> Validate -> Execute -> Store.
        """
        decision = require_capability(
            CapabilityRequest(
                capability=Capability.CUSTOM_POC_EXECUTION,
                context=context,
                target=request.target,
                requires_callback=True,
                ttl_seconds=900,
            )
        )
        if not decision.allowed:
            if context.user_id:
                try:
                    async with async_session_maker() as db_session:
                        await audit_log_event(
                            db_session,
                            AuditEventType.MISSION_CAPABILITY_DENIED,
                            user_id=context.user_id,
                            details={
                                "mission_id": context.mission_id,
                                "target": request.target,
                                "capability": decision.capability,
                                "reason": decision.reason,
                            },
                        )
                except Exception as exc:
                    logger.debug("Failed to write custom POC denial audit event: %s", exc)
            return POCResult(
                success=False,
                error=f"Custom POC execution denied by mission capability policy: {decision.reason}",
            )

        try:
            # 1. Prepare Callback (if needed)
            callback_host = settings.CONNECT_BACK_HOST

            callback_port = await shell_relay_client.start_listener(
                session_id=context.session_id,
                target=request.target,
                mission_id=context.mission_id,
                port=0,
                ttl_seconds=900,
            )

            # 2. Generate Code
            dev_input = POCDeveloperInput(
                request=request,
                callback_host=callback_host,
                callback_port=callback_port,
                shell_type="reverse_shell",  # simplified for now
            )

            result = await self.developer_agent.execute(context, dev_input)

            if not result.success or not result.action:
                return POCResult(success=False, error=result.error or "Agent failed")

            poc_output = result.action  # POCDeveloperOutput

            # 3. Consensus / Quality Gate
            vote_result = await self.consensus.validate_at_gate(
                QualityGate.PAYLOAD,
                result.action,
                {
                    "code_preview": poc_output.code_content[:500],
                    "target": request.target,
                    "risk": poc_output.risk_assessment,
                },
            )

            if vote_result.status != "approved":
                return POCResult(
                    success=False,
                    error=f"Consensus rejected: {vote_result.escalation_reason}",
                )

            # 4. Execute via Worker
            mission_adapter = StandaloneMissionAdapter(target=request.target)
            exec_result = await self.tool_service.execute_custom_script(
                mission=mission_adapter,
                script_content=poc_output.code_content,
                language=poc_output.language,
                target=request.target,
                timeout=300,
            )

            if not exec_result.success:
                # Optional: Feedback loop to fix code?
                return POCResult(
                    success=False,
                    error=exec_result.stderr,
                    content=poc_output.code_content,
                )

            # 5. Success - Return result with Metadata
            metadata = POCMetadata(
                name=f"Custom-{request.vulnerability.get('name', 'Exploit')}",
                target_service=request.target,
                language=poc_output.language,
                shell_type="reverse_shell",
            )
            artifact = await MissionArtifactWorkspace(context.mission_id).put_artifact(
                filename=f"{metadata.name}.{poc_output.language}",
                content=poc_output.code_content.encode(),
                kind="custom_poc",
                labels=["custom_poc", "generated_payload", request.target],
                ttl_seconds=30 * 86400,
            )
            evidence = {
                "artifact_id": artifact.id,
                "s3_key": artifact.key,
                "sha256": artifact.sha256,
                "kind": artifact.kind,
            }

            return POCResult(success=True, content=poc_output.code_content, metadata=metadata, evidence=evidence)

        except Exception as e:
            logger.error("POC Service error: %s", e, exc_info=True)
            return POCResult(success=False, error=str(e))
