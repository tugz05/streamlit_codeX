# models.py
from pydantic import BaseModel, Field, validator
from typing import List

class RubricItem(BaseModel):
    criterion: str = Field(..., min_length=2, max_length=200)
    weight: float = Field(..., ge=0.0)

class ActivityCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    instruction: str = Field("", max_length=5000)
    max_score: float = Field(100.0, ge=1.0, le=1000.0)
    criteria: List[RubricItem]

    @validator("criteria")
    def non_empty(cls, v):
        if not v:
            raise ValueError("At least one criterion is required")
        return v

class ParticipantJoin(BaseModel):
    join_code: str
    name: str = Field(..., min_length=1, max_length=200)
    section: str = Field("", max_length=120)

class SubmissionCreate(BaseModel):
    join_code: str
    student_name: str
    section: str
    language: str
    code: str
    ai_model: str
    total_score: float
    feedback_json: dict
