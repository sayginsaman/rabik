// Safe mode: moving a calendar event asks first (brain/calendar.py builds this exact card).
ui.listen(); ui.words('Move my dentist appointment to 4.'); ui.think();
ui.line('▸ Checking your calendar');
ui.ask(['Move this event?', 'Dentist → Tue Oct 27, 4:00 PM – 5:00 PM · from Tue Oct 27, 2:00 PM – 3:00 PM · Home · this occurrence only']);
