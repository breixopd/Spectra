"""Structured error types for AI agent failures."""


class AgentError(Exception):
    """Base error for agent failures."""
    def __init__(self, message: str, agent: str, retryable: bool = False):
        self.agent = agent
        self.retryable = retryable
        super().__init__(message)


class LLMTimeoutError(AgentError):
    """LLM request timed out."""
    def __init__(self, agent: str, timeout_seconds: float):
        super().__init__(f"LLM timeout after {timeout_seconds}s", agent=agent, retryable=True)
        self.timeout_seconds = timeout_seconds


class LLMParseError(AgentError):
    """Failed to parse LLM response."""
    def __init__(self, agent: str, raw_response: str):
        super().__init__("Failed to parse LLM response", agent=agent, retryable=True)
        self.raw_response = raw_response[:500]  # Truncate for safety


class LLMRateLimitError(AgentError):
    """LLM rate limit exceeded."""
    def __init__(self, agent: str):
        super().__init__("LLM rate limit exceeded", agent=agent, retryable=True)


class AgentChainError(AgentError):
    """Failure in agent chain execution."""
    def __init__(self, agent: str, step: str, cause: Exception):
        self.step = step
        self.cause = cause
        super().__init__(f"Chain failed at {step}: {cause}", agent=agent, retryable=False)
