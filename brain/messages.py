"""What the model is sent and streams back: the confirmed request kept apart from untrusted context, and the content
blocks of a stream event."""
import base64
import os
from pathlib import Path
from brain import prompts

__all__ = ['main_ask', 'user_content', 'message_blocks']


def main_ask(task, request=None):
    """Keep the confirmed transcript separate from untrusted context."""
    prompt = task.removesuffix(prompts.MODEL_OFFER)
    return (prompt if request is None else request), prompt


def user_content(task, shots=(), request=None):
    """The same final explicit request block for every supported client."""
    request, context = main_ask(task, request)
    content = [b for path, label in shots if os.path.exists(path) for b in ({'type': 'text', 'text': label}, {'type': 'image', 'source': {
        'type': 'base64', 'media_type': 'image/jpeg', 'data': base64.b64encode(Path(path).read_bytes()).decode()}})]
    if context.strip() and context != request:
        content.append({'type': 'text', 'text': context.rstrip()})
    content.append({'type': 'text', 'text': 'THE CURRENT USER REQUEST (do this now):\n' + request + (prompts.MODEL_OFFER if task.endswith(prompts.MODEL_OFFER) else '')})
    return content


def message_blocks(event):
    """Validated content blocks from an external model stream event."""
    message = event.get('message')
    content = message.get('content') if isinstance(message, dict) else None
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []
