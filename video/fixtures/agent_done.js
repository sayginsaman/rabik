// The same errand, done: the chip's summary of the three options.
const now = Date.now() / 1000;
agents.mode('shelf'); agents.visible(true);
agents.list([{id: 'a1', title: 'Desk lamp under $30', status: 'done', created: now - 96, started: now - 96, ended: now - 2,
  summary: 'Found 3 desk lamps under $30:\n\n- Slim LED lamp · $22.99\n- Clamp arm lamp · $27.50\n- Dimmable task lamp · $29.00',
  target: {app: 'Google Chrome', window: 'Desk lamps'}, timeline: []}]);
agents.expand('a1');
// Room around the shelf so the chip's own shadow isn't cut off at the page edge (the shelf keeps its 300 pt width).
const room = document.createElement('style'); room.textContent = 'html, body { overflow: visible !important; } body { padding: 24px !important; box-sizing: border-box; }'; document.head.append(room);
