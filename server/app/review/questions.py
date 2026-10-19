"""Review task orchestration using feature-owned prompts and schemas."""

import json

from pydantic import ValidationError

from app.ai.client import get_chat_client
from app.errors import NotConfigured, Unavailable
from app.review.ai_schemas import QuestionOutput, FeedbackOutput
from app.review.prompts.questions import QUESTION_PROMPT, QUESTION_VERSION
from app.review.prompts.feedback import FEEDBACK_PROMPT, FEEDBACK_VERSION


def generate_question(snapshot: dict) -> tuple[str, str, str]:
    try:
        client = get_chat_client()
    except NotConfigured:
        return f"Explain {snapshot['title']} in your own words. What are you unsure about?", "template", QUESTION_VERSION
    payload = json.dumps({"understanding": snapshot, "output_schema": QuestionOutput.model_json_schema()})
    try:
        result = QuestionOutput.model_validate_json(client.generate(QUESTION_PROMPT, payload))
    except ValidationError as exc:
        raise Unavailable("The model returned an invalid review question") from exc
    return result.prompt, client.model_key, QUESTION_VERSION


def assess_answer(snapshot: dict, prompt: str, response: str) -> dict:
    client = get_chat_client()
    payload = json.dumps({"saved_user_understanding": snapshot, "question": prompt,
                          "user_response": response, "output_schema": FeedbackOutput.model_json_schema()})
    try:
        result = FeedbackOutput.model_validate_json(client.generate(FEEDBACK_PROMPT, payload))
    except ValidationError as exc:
        raise Unavailable("The model returned invalid review feedback") from exc
    return {**result.model_dump(), "model_key": client.model_key, "prompt_version": FEEDBACK_VERSION}
