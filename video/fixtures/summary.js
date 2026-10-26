// A finished answer from Rabik's own records: what the Northstar weekly decided, with the meeting as a source chip.
ui.listen(); ui.words('What did we decide in the Northstar weekly?'); ui.think();
ui.line('▸ Reading your meetings');
await new Promise(r => setTimeout(r, 1800));
ui.line('✓ In the **Northstar weekly** at 11:00 the team settled two things:\n\n- **Ship onboarding Friday**\n- **Pam owns the pricing copy**\n\nYour action items:\n\n- Send the draft to Pam\n- Book the design review');
ui.line('⌖ ' + JSON.stringify([{kind: 'meeting', id: 'm1', label: 'Northstar weekly · Today 11:00'}, {kind: 'person', id: 'pam', label: 'Pam'}]));
