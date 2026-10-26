// The 21:00 evening recap, opened in full, with Mike's day around the Northstar project.
const open = document.createElement('style'); open.textContent = '.agent-card.recap-card .a,#thread{max-height:none!important;overflow:visible!important}'; document.head.append(open);
ui.recap({day: '2026-10-26', headline: 'Onboarding locked for Friday, lamp found, two follow-ups', source: 'ai',
  highlights: ['Northstar weekly agreed to ship onboarding Friday', 'An agent found 3 desk lamps under $30'],
  decisions: ['Pam owns the pricing copy'],
  actions: [{text: 'Send the draft to Pam', source: 'Northstar weekly', from: 'meeting:m1', due: '2026-10-27', key: 'a', added: ''},
            {text: 'Book the design review', source: 'Northstar weekly', from: 'meeting:m1', due: '', key: 'b', added: ''},
            {text: 'Pick one of the three lamps', source: 'Agent: Desk lamp under $30', from: 'agent:x', due: '', key: 'c', added: ''}],
  goals: [{goal: 'Ship Northstar onboarding by Friday', note: 'Decided in the weekly; only the pricing copy is left.'}],
  focus: ['Northstar onboarding · Figma · 1 h 25 min', 'Pricing draft · Pages · 40 min'], tomorrow: ['09:30 Northstar standup', '16:00 Dentist']});
document.getElementById('thread').scrollTop = 0;
