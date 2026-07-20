from pydantic import BaseModel
from typing import Any


class CommandRequest(BaseModel):
    command:   str
    confirmed: bool = False
    allowed_locations: list[str] | None = None


class SafetyResult(BaseModel):
    level:                 str
    allowed:               bool
    requires_confirmation: bool
    send_email:            bool
    reason:                str


class CommandResponse(BaseModel):
    user_input:            str
    interpreted_command:   str
    api_command:           str
    safety:                SafetyResult
    robot_response:        Any | None = None
    status_message:        str
    dry_run:               bool


class ModeRequest(BaseModel):
    dry_run:      bool
    confirmation: str = ""


class SequenceRequest(BaseModel):
    command: str
    allowed_locations: list[str] | None = None


class BatchMissionRequest(BaseModel):
    commands: list[str]


class PlanBTextRequest(BaseModel):
    command: str
    allowed_locations: list[str] | None = None