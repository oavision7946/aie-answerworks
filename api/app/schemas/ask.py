from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator

from app.core.config import get_llm_settings, load_model_costs


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: StrictStr = Field(min_length=1)
    model: StrictStr = get_llm_settings().default_model
    stream: StrictBool = False
    force_bad_first_response: StrictBool = False
    force_bad: StrictBool = False

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, question: str) -> str:
        question = question.strip()
        if not question:
            raise ValueError("question must not be blank")
        return question

    @field_validator("model")
    @classmethod
    def model_must_be_configured(cls, model: str) -> str:
        if model not in load_model_costs():
            raise ValueError(f"model must be one of: {', '.join(load_model_costs())}")
        return model


class ModelOutput(BaseModel):
    answer: StrictStr = Field(min_length=1)

    @field_validator("answer")
    @classmethod
    def answer_must_not_be_blank(cls, answer: str) -> str:
        answer = answer.strip()
        if not answer:
            raise ValueError("answer must not be blank")
        return answer


class AskResponse(BaseModel):
    answer: str
    model: str
    tokens_used: int
    latency_ms: int
    cost_usd: float


class ModelsResponse(BaseModel):
    models: list[str]
