"""
POC Service.

Orchestrates the creation and verification of custom POCs.
"""

import logging

from app.core.config import settings
from app.services.ai.agents.base import AgentContext
from app.services.ai.agents.poc_developer import POCDeveloperAgent, POCDeveloperInput
from app.services.ai.consensus import QualityGate, VotingSystem
from app.services.ai.llm import LLMClient
from app.services.poc.models import POCMetadata, POCRequest, POCResult
from app.services.shell.session_manager import shell_manager
from app.services.tools.service import ToolExecutionService

logger = logging.getLogger("spectra.services.poc")


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
        try:
            # 1. Prepare Callback (if needed)
            callback_port = 4444  # Dynamic allocation in real impl
            callback_host = settings.CONNECT_BACK_HOST

            # Start listener if reverse shell
            # Allocate a free port
            shell_manager.start_listener(
                callback_port, context.session_id, request.target
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
            exec_result = await self.tool_service.execute_custom_script(
                mission=None,  # We might need to pass mission if available, adapted context
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

            return POCResult(
                success=True, content=poc_output.code_content, metadata=metadata
            )

        except Exception as e:
            logger.error("POC Service error: %s", e, exc_info=True)
            return POCResult(success=False, error=str(e))
