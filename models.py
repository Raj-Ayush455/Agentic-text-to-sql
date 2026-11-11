"""
Pydantic models for structured LLM output.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class QueryStatus(str, Enum):
    """Whether the LLM can generate SQL or needs more information."""

    READY = "READY"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class LLMResponse(BaseModel):
    """Structured response returned by the Clarification Engine.

    Invariants enforced by the validator:
      • READY              →  sql_query must be set, clarification_question must be null
      • NEEDS_CLARIFICATION →  clarification_question must be set, sql_query must be null
    """

    status: QueryStatus = Field(
        ...,
        description="READY if the question is unambiguous; NEEDS_CLARIFICATION otherwise.",
    )
    sql_query: Optional[str] = Field(
        None,
        description="The generated SQL query.  Present only when status is READY.",
    )
    clarification_question: Optional[str] = Field(
        None,
        description="A follow-up question to resolve ambiguity.  Present only when status is NEEDS_CLARIFICATION.",
    )

    @model_validator(mode="after")
    def _check_consistency(self) -> "LLMResponse":
        if self.status == QueryStatus.READY:
            if not self.sql_query:
                raise ValueError("sql_query is required when status is READY")
            if self.clarification_question is not None:
                # Tolerate but clear it — some models still fill it in.
                self.clarification_question = None
        else:
            if not self.clarification_question:
                raise ValueError(
                    "clarification_question is required when status is NEEDS_CLARIFICATION"
                )
            if self.sql_query is not None:
                self.sql_query = None
        return self

