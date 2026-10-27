'use strict';
// Dev tool:  CRYSTAL_SELFTEST=/tmp/shot npm start
// Draws a test pattern behind the ball, opens the dialogue box, saves <prefix>-ball.png and <prefix>-bg.png, quits.
const fs = require('fs');
const wait = ms => new Promise(r => setTimeout(r, ms));

module.exports = async function selftest({ BrowserWindow, ballWin, log, openWindow }) {
  const prefix = process.env.CRYSTAL_SELFTEST;
  const html = `<body style="margin:0;background:linear-gradient(90deg,#e63946,#f4a261,#e9c46a,#2a9d8f,#264653,#6a4c93);font:700 64px sans-serif;color:#fff">
    <div style="position:absolute;inset:0;background-image:linear-gradient(#0003 2px,transparent 2px),linear-gradient(90deg,#0003 2px,transparent 2px);background-size:40px 40px"></div>
    <div style="position:absolute;left:60px;top:120px">CRYSTAL BALL TEST</div><div style="position:absolute;left:60px;top:260px;font-size:28px">The quick brown fox jumps over the lazy dog</div></body>`;
  const bg = new BrowserWindow({ x: 0, y: 0, width: 1400, height: 900, frame: false, focusable: false, show: true });
  bg.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
  ballWin.setPosition(180, 60); ballWin.show();
  await wait(4000);
  // Xvfb cannot capture its own screen, so feed the shader the same pattern as a synthetic "desktop".
  await ballWin.webContents.executeJavaScript(`(async () => {
    stopCapture();
    const c = document.createElement('canvas'); c.width = 1400; c.height = 900; const g = c.getContext('2d');
    const gr = g.createLinearGradient(0, 0, 1400, 0); ['#e63946','#f4a261','#e9c46a','#2a9d8f','#264653','#6a4c93'].forEach((col, i) => gr.addColorStop(i / 5, col));
    g.fillStyle = ${JSON.stringify(process.env.CRYSTAL_SELFTEST_BG === 'white' ? '#ffffff' : null)} || gr; g.fillRect(0, 0, 1400, 900); g.strokeStyle = 'rgba(0,0,0,.25)'; g.lineWidth = 2;
    for (let x = 0; x < 1400; x += 40) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, 900); g.stroke(); }
    for (let y = 0; y < 900; y += 40) { g.beginPath(); g.moveTo(0, y); g.lineTo(1400, y); g.stroke(); }
    g.fillStyle = ${JSON.stringify(process.env.CRYSTAL_SELFTEST_BG === 'white' ? '#222' : '#fff')}; g.font = '700 64px sans-serif'; g.fillText('CRYSTAL BALL TEST', 60, 180);
    g.font = '700 28px sans-serif'; g.fillText('The quick brown fox jumps over the lazy dog', 60, 290);
    el.video.srcObject = c.captureStream(30); await el.video.play();
    capture.has = true; capture.disp = { x: 0, y: 0, width: 1400, height: 900 };
    setInterval(() => g.fillRect(0, 0, 1, 1), 100);
  })()`);
  await wait(1500);
  ballWin.webContents.send('ui:toggle-chat');
  await ballWin.webContents.executeJavaScript(`addMsg('user','what files are in my notes folder?'); addMsg('tool','Listing notes'); addMsg('assistant','You have three notes: todo, ideas and a shopping list. Want me to read one?','phi · 1.8s'); 0`);
  await wait(2500);
  const a = await ballWin.webContents.capturePage(); fs.writeFileSync(prefix + '-ball.png', a.toPNG());
  const b = await bg.webContents.capturePage(); fs.writeFileSync(prefix + '-bg.png', b.toPNG());
  if (process.env.CRYSTAL_SELFTEST_CHAT) {
    await ballWin.webContents.executeJavaScript(`sendChat('Hello crystal, can you hear me?'); 0`);
    await wait(1200);
    fs.writeFileSync(prefix + '-streaming.png', (await ballWin.webContents.capturePage()).toPNG());
    await wait(3500);
    fs.writeFileSync(prefix + '-chat.png', (await ballWin.webContents.capturePage()).toPNG());
  }
  for (const name of ['settings', 'console']) {
    const w = openWindow(name);
    await wait(1500);
    if (name === 'console') { log.error('selftest', 'deliberate test error so the console has something red'); log.warn('selftest', 'deliberate warning'); await wait(500); }
    fs.writeFileSync(`${prefix}-${name}.png`, (await w.webContents.capturePage()).toPNG());
  }
  log.info('selftest', `saved ${prefix}-ball.png and ${prefix}-bg.png`);
  process.exit(0);
};
