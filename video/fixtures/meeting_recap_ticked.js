// The recap with both action items ticked: the frame each tick crossfades to.
meeting.width(340); meeting.listen(); meeting.capturing(); meeting.clock(151); meeting.saving(true);
const L = (id, t, s, extra = {}) => meeting.line({id, text: t, seconds: s, ...extra});
L(1, 'Morning, everyone. Quick Northstar check-in before lunch.', 64, {name: 'Pam'});
L(2, 'Onboarding is in good shape. I think we can ship it Friday.', 72, {mic: true});
L(3, 'QA signed off on the last two screens yesterday.', 81, {name: 'Jordan'});
L(4, 'Great. Then we ship onboarding Friday.', 89, {name: 'Pam'});
L(5, 'Who is taking the pricing copy?', 96, {mic: true});
L(6, 'I will own the pricing copy. Send me your draft.', 103, {name: 'Pam'});
L(7, 'I will send the draft to Pam today.', 112, {mic: true});
L(8, 'We still need a design review before launch.', 121, {name: 'Jordan'});
L(9, 'I will book the design review for Thursday.', 129, {mic: true});
L(10, 'Perfect. That is everything for this week.', 137, {name: 'Pam'});
L(11, 'Thanks, both. See you Thursday.', 144, {mic: true});
meeting.stopped();
meeting.recap({id: 'm1', summary: 'Northstar onboarding ships Friday; QA has signed off. Pam owns the pricing copy and is waiting on your draft. A design review is still needed before launch.',
  todos: [{text: 'Send the draft to Pam', key: 'a'}, {text: 'Book the design review', key: 'b'}], share: 'Northstar weekly'});
document.querySelectorAll('#todolist .todo').forEach(b => b.click());
