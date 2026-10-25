"""Rabik's RABIK_* environment variables: the ask this process serves, and the process's own settings (AskContext).

Rabik.app describes an ask in the environment of the helper it starts, and main() adds to it (the ask folder, the hands
map); the AI client and every helper it runs inherit that environment, so it stays the store. This module is the one place
that names each variable, says what it means and reads it the same way everywhere. Every accessor reads os.environ when
it is called: main() sets values mid-ask and tests patch them. A flag the code only ever compares to '1' comes back as a
bool; anything else comes back as the variable holds it, with the caller's default."""
import os
from contextlib import contextmanager

__all__ = ['ask_dir', 'set_ask_dir', 'agent', 'front_app', 'set_front_app', 'in_box', 'live', 'commit', 'request', 'requested',
           'hands_file', 'set_hands_file', 'screen', 'caret', 'selection', 'relay_active_here', 'set_relay_active',
           'relay_owner_here', 'set_relay_owner', 'agent_prep', 'focus_guard', 'in_menu_bar_click', 'clicking_menu_bar',
           'sandbox_dir', 'app', 'client_override', 'claude', 'codex', 'posthog_key', 'probe_key', 'probe_base']


def _read(name, default=None, required=False):
    return os.environ[name] if required else os.environ.get(name, default)


# --- the ask -------------------------------------------------------------------------------------------------------

def ask_dir(default=None, *, required=False):
    """This ask's folder (RABIK_ASK): its Allow cards and answers, hands events, the request. Unset outside an ask."""
    return _read('RABIK_ASK', default, required)


def set_ask_dir(path):
    os.environ['RABIK_ASK'] = path


def agent(default=None):
    """The background agent's id (RABIK_AGENT, 32 hex characters) when this process works for one, not the main ask."""
    return _read('RABIK_AGENT', default)


def front_app(default=None, *, required=False):
    """The app the user was in when the ask started (RABIK_FRONT): "this window" means it."""
    return _read('RABIK_FRONT', default, required)


def set_front_app(name):
    os.environ['RABIK_FRONT'] = name


def in_box():
    """The ask came from the box (RABIK_UI=1), so its output goes to the overlay, not a notification."""
    return os.environ.get('RABIK_UI') == '1'


def live():
    """The user is still talking (RABIK_LIVE=1): words can change, so nothing acts yet."""
    return os.environ.get('RABIK_LIVE') == '1'


def commit(default=None, *, required=False):
    """The file that appears once the transcript is confirmed (RABIK_COMMIT); tools and the answer wait for it."""
    return _read('RABIK_COMMIT', default, required)


def request(default=None):
    """The user's own words for this step (RABIK_REQUEST), which focus and typing trust."""
    return _read('RABIK_REQUEST', default)


@contextmanager
def requested(words):
    """RABIK_REQUEST is `words` inside the block (a replayed shortcut's steps), then what it was before."""
    before = os.environ.get('RABIK_REQUEST'); os.environ['RABIK_REQUEST'] = words
    try:
        yield
    finally:
        if before is None: os.environ.pop('RABIK_REQUEST', None)
        else: os.environ['RABIK_REQUEST'] = before


def hands_file(default=None):
    """This ask's hands map file (RABIK_HANDS_STATE): the window and controls the last --hands look found."""
    return _read('RABIK_HANDS_STATE', default)


def set_hands_file(path):
    os.environ['RABIK_HANDS_STATE'] = path


def screen(default=None, *, required=False):
    """The display the user asked from (RABIK_SCREEN): unnamed moves and drawings go there."""
    return _read('RABIK_SCREEN', default, required)


def caret(default=None):
    """'1' when the ask started with the text cursor in a text field (RABIK_CARET), else '' or unset."""
    return _read('RABIK_CARET', default)


def selection(default=None):
    """The text the user had selected when the ask started (RABIK_SELECTION)."""
    return _read('RABIK_SELECTION', default)


def relay_active_here():
    """This process already relays the ask's cards (RABIK_RELAY_ACTIVE is its pid)."""
    return os.environ.get('RABIK_RELAY_ACTIVE') == str(os.getpid())


def set_relay_active():
    os.environ['RABIK_RELAY_ACTIVE'] = str(os.getpid())


def relay_owner_here():
    """This process owns the ask's relay (RABIK_RELAY_OWNER is its pid): hands events print here, not through the folder."""
    return os.environ.get('RABIK_RELAY_OWNER') == str(os.getpid())


def set_relay_owner():
    os.environ['RABIK_RELAY_OWNER'] = str(os.getpid())


def agent_prep():
    """The agent is still preparing its task (RABIK_AGENT_PREP=1), not working on it yet."""
    return os.environ.get('RABIK_AGENT_PREP') == '1'


def focus_guard():
    """Rabik.app keeps focus with the user for this ask (RABIK_FOCUS_GUARD=1)."""
    return os.environ.get('RABIK_FOCUS_GUARD') == '1'


def in_menu_bar_click(default=None):
    """Set while a menu bar click runs (RABIK_BAR), so a click it makes never looks in the menu bar again."""
    return _read('RABIK_BAR', default)


@contextmanager
def clicking_menu_bar():
    """RABIK_BAR is set inside the block and gone after it."""
    os.environ['RABIK_BAR'] = '1'
    try:
        yield
    finally:
        os.environ.pop('RABIK_BAR', None)


# --- the process ---------------------------------------------------------------------------------------------------

def sandbox_dir(default=None):
    """Where Rabik keeps its files instead of ~/.config/rabik (RABIK_DIR): tests and evals, never a user's install."""
    return _read('RABIK_DIR', default)


def app(default=None):
    """Rabik.app's binary (RABIK_APP), set by the app for the helpers it starts."""
    return _read('RABIK_APP', default)


def client_override(default=None):
    """The AI client this process runs for (RABIK_CLIENT: claude, devin or pi), when it is not the user's setting."""
    return _read('RABIK_CLIENT', default)


def claude(default=None):
    """The Claude Code binary to run (RABIK_CLAUDE), instead of the one on PATH."""
    return _read('RABIK_CLAUDE', default)


def codex(default=None):
    """The Codex binary that adds MCP servers for the ChatGPT Mac app (RABIK_CODEX), instead of the one Rabik finds."""
    return _read('RABIK_CODEX', default)


def posthog_key(default=None):
    """The PostHog project key (RABIK_POSTHOG_KEY); empty turns telemetry off."""
    return _read('RABIK_POSTHOG_KEY', default)


def probe_key(default=None):
    return _read('RABIK_PROBE_KEY', default)


def probe_base(default=None):
    return _read('RABIK_PROBE_BASE', default)
