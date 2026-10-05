from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: StrictStr = Field(min_length=1)
    # Both optional: omitted -> the default provider's default model.
    provider: StrictStr | None = None
    model: StrictStr | None = None
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
    provider: str
    model: str
    tokens_used: int
    latency_ms: int
    cost_usd: float | None  # null when the model has no pricing configured


class ModelInfo(BaseModel):
    provider: str
    id: str
    label: str


class ModelsResponse(BaseModel):
    default_provider: str | None
    default_model: str | None
    models: list[ModelInfo]
