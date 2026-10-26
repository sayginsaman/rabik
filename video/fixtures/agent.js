// An errand an agent runs behind Mike's apps: the corner chip, open, with its live steps and the mini screen's slot.
const now = Date.now() / 1000;
agents.mode('shelf'); agents.visible(true);
agents.list([{id: 'a1', title: 'Desk lamp under $30', status: 'running', step: 'Comparing 3 lamps', created: now - 41, started: now - 41,
  steps: ['Searching for desk lamps under $30', 'Reading 3 product pages', 'Comparing prices and reviews'],
  target: {app: 'Google Chrome', window: 'Desk lamps'}, timeline: []}]);
agents.expand('a1');
// Room around the shelf so the chip's own shadow isn't cut off at the page edge (the shelf keeps its 300 pt width).
const room = document.createElement('style'); room.textContent = 'html, body { overflow: visible !important; } body { padding: 24px !important; box-sizing: border-box; }'; document.head.append(room);
