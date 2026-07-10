#!/usr/bin/env python3
"""Press Enter while the screen is dark to catch the fresh-boot CD prompt.
Connect with retry (VNC may not be ready immediately) and start pressing ASAP.
blue -> Windows Setup (exit 0). Persistent gray Front Page -> exit 1 so the
wrapper power-cycles for another fresh-boot attempt."""
import sys, os, time
from vncdotool import api

port = sys.argv[1]
duration = int(sys.argv[2]) if len(sys.argv) > 2 else 90

client = None
t0 = time.time()
while time.time() - t0 < 25:
    try:
        client = api.connect('127.0.0.1::%s' % port)
        client.timeout = 12
        client.refreshScreen()
        break
    except Exception as e:
        print('connect retry:', e); time.sleep(2); client = None
if client is None:
    print('NO_VNC'); sys.exit(2)

def analyze():
    client.refreshScreen()
    img = client.screen.convert('RGB').resize((40, 30))
    px = list(img.getdata()); n = len(px)
    r = sum(p[0] for p in px) / n
    g = sum(p[1] for p in px) / n
    b = sum(p[2] for p in px) / n
    mean = (r + g + b) / 3
    if mean < 45:
        return 'dark', mean
    if b - (r + g) / 2 > 16:
        return 'blue', mean
    if abs(r - g) < 22 and abs(g - b) < 22 and mean > 85:
        return 'gray', mean
    return 'other', mean

deadline = time.time() + duration
blue_streak = gray_streak = 0
while time.time() < deadline:
    try:
        s, m = analyze()
    except Exception as e:
        print('err', e); time.sleep(1); continue
    print('%-6s %5.1f' % (s, m))
    if s == 'dark':
        client.keyPress('enter'); gray_streak = 0; blue_streak = 0
    elif s == 'blue':
        blue_streak += 1; gray_streak = 0
        if blue_streak >= 3:
            print('SETUP'); sys.stdout.flush(); os._exit(0)
    else:  # gray / other
        gray_streak += 1
        if gray_streak >= 12:
            print('STUCK'); sys.stdout.flush(); os._exit(1)
    time.sleep(0.8)
print('TIMEOUT'); sys.stdout.flush(); os._exit(1)
