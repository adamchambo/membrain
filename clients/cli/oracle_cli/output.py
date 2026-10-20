"""User-facing result formatting; transport and model metadata stay out of normal flows."""
import json
from .types import Result


def show(result: Result, write=print) -> None:
    """Render result using write, an injectable line-output function."""
    write(result.message)
    for number, item in enumerate(result.items, 1):
        write(f'{number}. {item.title} [{item.kind}] {item.id}' + (f' — {item.detail}' if item.detail else ''))
    if result.payload is not None:
        describe(result.payload, write)
    if result.cursor:
        write('/more loads the next page.')


def feedback(value, write):
    if not value:
        write('Feedback is still processing.')
        return
    write(value.get('feedback', ''))
    if value.get('recall'):
        write('Recall against your saved explanation: ' + value['recall'])
    write('Factual correctness: not verified.')


def describe(value, write):
    """Present wire value as learning content; write receives each readable line."""
    if not isinstance(value, dict):
        write(json.dumps(value, default=str, ensure_ascii=False))
        return
    if 'output' in value and 'inputs' in value:
        output = value['output']
        if output is None:
            write('This learning result is still processing. Check its job status or return later.')
            return
        write(output['content'])
        write('Evidence: ' + ('supplied sources compared' if output.get('verification') == 'sources_compared' else 'not factually verified'))
        for uncertainty in output.get('uncertainty', []):
            write('Uncertain: ' + uncertainty)
        for citation in output.get('citations', []):
            write(f'Source excerpt ({citation["chunk_id"]}): {citation["quote"]}')
        for question in output.get('optional_questions', []):
            write('Optional question: ' + question)
        return
    if 'payload' in value and 'status' in value:
        suggestion = value['payload']
        write(f"{suggestion.get('kind', 'Suggestion')}: {suggestion.get('rationale', '')}")
        write(f"Evidence: {suggestion.get('evidence', 'uncertain')}; decision: {value['status']}")
        if suggestion.get('explanation_text'):
            write('Proposed explanation: ' + suggestion['explanation_text'])
        if suggestion.get('diagnostic_question'):
            write('Diagnostic question: ' + suggestion['diagnostic_question'])
        for citation in suggestion.get('citations', []):
            write(f'Source excerpt ({citation["chunk_id"]}): {citation["quote"]}')
        return
    if 'feedback' in value and 'response' in value:
        write('Your answer: ' + value['response'])
        feedback(value['feedback'], write)
        return
    if 'raw_text' in value:
        write(value['raw_text'])
        write('Capture status: ' + value.get('status', 'saved'))
        for identifier in value.get('concept_ids', []):
            write('Linked concept: ' + str(identifier))
        for proposal in value.get('proposals', []):
            payload = proposal.get('payload', {})
            if payload.get('question'):
                write(f"Optional clarification ({proposal['id']}): {payload['question']}")
        return
    if 'latest_revision' in value:
        write(value['title'])
        revision = value['latest_revision']
        write(revision['body'] if revision else 'No explanation recorded yet.')
        for resource in value.get('resources', []):
            write('Resource: ' + (resource.get('title') or resource['uri']) + ' — ' + resource['uri'])
        return
    if 'uri' in value:
        write(value.get('title') or value['uri'])
        write(value['uri'])
        if value.get('note'):
            write(value['note'])
        for chunk in value.get('stored_content', {}).get('items', []):
            write(chunk['text'])
        return
    if 'eligible_concept_ids' in value:
        write(f"Scope: {len(value['eligible_concept_ids'])} concepts; reviewed: {len(value['reviewed_concept_ids'])}; unreviewed: {len(value['unreviewed_concept_ids'])}.")
        write(f"Recorded changes: {len(value['revisions'])}; recorded answers: {len(value['attempts'])}.")
        write('Unreviewed means unassessed, not unknown. Mastery is not inferred.')
        if value.get('truncated'):
            write('Results are bounded; narrow the subject or period for more detail.')
        return
    if 'questions' in value and 'attempts' in value:
        write(f"Questions: {len(value['questions'])}; answers: {len(value['attempts'])}.")
        prompts = {str(question['id']): question['prompt'] for question in value['questions']}
        for attempt in value['attempts']:
            write('Question: ' + prompts.get(str(attempt.get('question_id')), 'Saved question'))
            write('Your answer: ' + attempt['response'])
            feedback(attempt.get('feedback'), write)
        return
    if 'captures' in value:
        write(value.get('title') or 'Conversation')
        for capture in value['captures']:
            write(f"{capture['created_at']} — {capture['raw_text']}")
        return
    if 'settings' in value and 'database' in value:
        write(f"Database ready: {value['database']['ready']}; worker running: {value['worker']['ready']}.")
        write('Work counts: ' + ', '.join(f'{status}: {count}' for status, count in value.get('pending_work', {}).items()))
        return
    if 'kind' in value and 'attempts' in value:
        write(f"{value['kind']}: {value['status']}; attempts: {value['attempts']}")
        if value.get('last_error'):
            write('Reason: ' + value['last_error'])
        if value.get('result'):
            write('Result: ' + json.dumps(value['result'], default=str))
        return
    if 'items' in value:
        for row in value['items']:
            if 'body' in row:
                write(f"Revision {row['revision_number']} — {row['created_at']}: {row['body']}")
            elif 'occurred_at' in row:
                write(f"{row['occurred_at']} — {row['type']}")
        return
    # Inspectable relationship, scope and decision records have no hidden credentials.
    write(json.dumps(value, indent=2, default=str, ensure_ascii=False))
