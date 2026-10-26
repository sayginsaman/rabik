// The box while Mike asks out loud; the words (and the live caret) stay laid out but invisible, so the video can type them in
// over the real box.
ui.listen(); ui.words('Code on my Studio Display, Chrome and Terminal on the vertical screen.');
document.querySelector('#thread .turn:last-child .q').style.color = 'transparent';
const hide = document.createElement('style'); hide.textContent = '.q.live::after { visibility: hidden !important; }'; document.head.append(hide);
