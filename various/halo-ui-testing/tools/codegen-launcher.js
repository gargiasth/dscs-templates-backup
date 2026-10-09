/*
 * codegen-launcher.js  —  dropdown that maps codegen recordings to test cases
 * ---------------------------------------------------------------------------
 * Now pulls test cases straight from the Excel backlog (the "Test backlog"
 * sheet of backlog/playwright-test-backlog.xlsx) via read-backlog.js. Pick a
 * case, click Record, and codegen's output is spliced into that case's skeleton
 * in ./tests between the <<<CODEGEN>>> markers.
 *
 * Daily work should use the Streamlit panel instead (npm start). This launcher
 * is an optional alternative if Streamlit is not available.
 *
 * Set the site in config.json (appUrl) or APP_URL, then:
 *   node tools/codegen-launcher.js
 * Open http://127.0.0.1:5599
 *
 * Needs SheetJS to read .xlsx:  npm install xlsx
 * Point BACKLOG at a different file if needed (a .csv export also works).
 *
 * SECURITY NOTE: starts a localhost-only web server that can launch codegen.
 * On a hardened VM a new listening service may need sign-off; if so, use the
 * VS Code "Record at cursor" workflow instead (no server).
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { load, PROJECT_ROOT, DEFAULT_BACKLOG } = require('./read-backlog');
const { requireAppUrl } = require('./app-config');

const PORT = 5599;
const BACKLOG = process.env.BACKLOG || DEFAULT_BACKLOG;
const TESTS_DIR = path.join(PROJECT_ROOT, 'tests');
let APP_URL;
try { APP_URL = requireAppUrl(); }
catch (e) { console.error(e.message); process.exit(1); }

function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

function extractBody(recorded) {
  const lines = recorded.replace(/\r\n/g,'\n').split('\n');
  const start = lines.findIndex(l => /async\s*\(\s*\{\s*page/.test(l) && /=>\s*\{/.test(l));
  if (start === -1) return null;
  let end = -1;
  for (let i = lines.length - 1; i > start; i--) { if (/^\s*\}\s*\)\s*;?\s*$/.test(lines[i])) { end = i; break; } }
  if (end === -1) return null;
  return lines.slice(start + 1, end)
    .filter(l => !/await\s+page\.goto\(/.test(l))
    .map(l => l.replace(/\s+$/,''))
    .filter(l => l.trim().length)
    .join('\n');
}

function spliceIntoSkeleton(file, body) {
  const p = path.join(TESTS_DIR, file);
  if (!fs.existsSync(p)) return { ok:false, msg:`Skeleton not found: tests/${file}. Run the generator first.` };
  const src = fs.readFileSync(p, 'utf8');
  const re = /(\/\/ <<<CODEGEN>>>\n)([\s\S]*?)(\n\s*\/\/ <<<END CODEGEN>>>)/;
  if (!re.test(src)) return { ok:false, msg:`Markers not found in tests/${file}. Regenerate skeletons with the updated generator.` };
  const indented = body.split('\n').map(l => l.length ? '  ' + l.replace(/^\s+/,'') : l).join('\n');
  fs.writeFileSync(p, src.replace(re, `$1${indented}$3`), 'utf8');
  return { ok:true, msg:`Recording mapped into tests/${file}. Now write the Expected-result assertion, then run it.` };
}

function runCodegen(caseObj) {
  return new Promise(resolve => {
    const tmp = path.join(TESTS_DIR, `.codegen-tmp-${caseObj.id}.js`);
    try { if (fs.existsSync(tmp)) fs.unlinkSync(tmp); } catch {}
    const child = spawn('npx', ['playwright','codegen','--output',tmp,APP_URL], { shell:true, stdio:'inherit', cwd: PROJECT_ROOT });
    child.on('error', err => resolve({ ok:false, msg:`Could not launch codegen: ${err.message}` }));
    child.on('close', () => {
      if (!fs.existsSync(tmp)) return resolve({ ok:false, msg:'Codegen closed with no recording saved.' });
      const body = extractBody(fs.readFileSync(tmp, 'utf8'));
      try { fs.unlinkSync(tmp); } catch {}
      if (!body) return resolve({ ok:false, msg:'Could not parse the recording (unexpected codegen format).' });
      resolve(spliceIntoSkeleton(caseObj.file, body));
    });
  });
}

function pageHtml() {
  const { error, cases } = load(BACKLOG);
  const ui = (cases || []).filter(c => c.uiCandidate);
  const opts = ui.map(c => `<option value="${esc(c.id)}">${esc(c.id)} (${esc(c.code)}) — ${esc(c.desc.split('.')[0].slice(0,80))}</option>`).join('');
  const data = JSON.stringify(ui.reduce((a,c)=>(a[c.id]=c,a),{}));
  return `<!doctype html><meta charset="utf-8"><title>Codegen launcher</title>
<style>
 body{font:14px/1.5 Arial,system-ui;margin:0;background:#f4f6fb;color:#1a2233}
 .wrap{max-width:760px;margin:32px auto;padding:0 20px}
 h1{color:#1f3864;font-size:20px;margin:0 0 4px} .sub{color:#7a869a;margin:0 0 20px}
 .card{background:#fff;border:1px solid #dfe4ee;border-radius:10px;padding:18px 20px;margin-bottom:16px}
 label{font-weight:bold;color:#1f3864;display:block;margin-bottom:6px}
 select,button{font:14px Arial;padding:9px 11px;border-radius:7px;border:1px solid #c3ccdb}
 select{width:100%;background:#fff}
 button{background:#1f3864;color:#fff;border:0;cursor:pointer;margin-top:14px;padding:11px 18px;font-weight:bold}
 button:disabled{background:#9aa7bd;cursor:default}
 .kv{margin:10px 0;padding:10px 12px;background:#f7f9fd;border-left:3px solid #1f3864;border-radius:4px}
 .kv b{color:#1f3864} .err{color:#b1361e;font-weight:bold}
 #status{white-space:pre-wrap;margin-top:12px} code{background:#eef1f7;padding:1px 5px;border-radius:4px}
</style>
<div class="wrap">
 <h1>Codegen launcher</h1>
 <p class="sub">Cases pulled from <code>${esc(BACKLOG)}</code> &middot; app <code>${esc(APP_URL)}</code></p>
 ${error ? `<div class="card err">${esc(error)}</div>` : `
 <div class="card">
  <label for="tc">Test case (${ui.length} UI candidates)</label>
  <select id="tc">${opts}</select>
  <div id="detail"></div>
  <button id="go">Record this case with codegen</button>
  <div id="status"></div>
 </div>`}
</div>
<script>
 const DATA = ${data};
 const sel=document.getElementById('tc'), det=document.getElementById('detail');
 const go=document.getElementById('go'), status=document.getElementById('status');
 function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
 function show(){ const c=DATA[sel.value]; if(!c) return;
   det.innerHTML='<div class="kv"><b>Precondition:</b> '+(c.pre?esc(c.pre):'<i>not filled in the backlog</i>')+
     '</div><div class="kv"><b>Steps:</b> '+(c.steps?esc(c.steps):'<i>not filled</i>')+
     '</div><div class="kv"><b>Expected:</b> '+(c.exp?esc(c.exp):'<i>not filled</i>')+
     '</div><div class="kv"><b>Writes to:</b> <code>tests/'+esc(c.file)+'</code></div>'; }
 sel.onchange=show; if(sel) show();
 if(go) go.onclick=async()=>{ go.disabled=true;
   status.textContent='Launching codegen\u2026 perform the Steps in the browser that opens, then close the codegen window to save.';
   try{ const r=await fetch('/launch?id='+encodeURIComponent(sel.value),{method:'POST'}); const j=await r.json();
     status.textContent=j.msg; status.className=j.ok?'':'err';
   }catch(e){ status.textContent='Error: '+e.message; status.className='err'; }
   go.disabled=false; };
</script>`;
}

http.createServer(async (req, res) => {
  const u = new URL(req.url, `http://127.0.0.1:${PORT}`);
  if (req.method === 'POST' && u.pathname === '/launch') {
    const { byId } = load(BACKLOG);
    const c = byId[u.searchParams.get('id')];
    if (!c) { res.writeHead(404,{'content-type':'application/json'}); return res.end(JSON.stringify({ok:false,msg:'Unknown test case.'})); }
    const result = await runCodegen(c);
    res.writeHead(200,{'content-type':'application/json'}); return res.end(JSON.stringify(result));
  }
  res.writeHead(200,{'content-type':'text/html; charset=utf-8'}); res.end(pageHtml());
}).listen(PORT, '127.0.0.1', () => {
  console.log(`Codegen launcher on http://127.0.0.1:${PORT}`);
  console.log(`Pulling cases from ${BACKLOG} \u00b7 app ${APP_URL} \u00b7 Ctrl+C to stop.`);
});
