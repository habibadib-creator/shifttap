/* Browserless DOM + actual HTTP integration. This is not visual browser QA.
   Requires development-only jsdom@26.1.0, provided through NODE_PATH. */
const {JSDOM,CookieJar}=require('jsdom');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const base='http://localhost:8901';
const fixture=spawn('python',['tests/serve_fixture.py'],{cwd:path.resolve(__dirname,'..'),stdio:['ignore','pipe','pipe']});
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(check,label){for(let i=0;i<100;i++){if(await check())return;await delay(50)}throw Error('Timed out: '+label)}
async function makeDom(route='/'){
 const jar=new CookieJar();const dom=new JSDOM(fs.readFileSync(path.resolve(__dirname,'../public/index.html'),'utf8'),{url:base+route,runScripts:'outside-only',cookieJar:jar,pretendToBeVisual:true});
 const w=dom.window;w.AbortSignal=global.AbortSignal;w.confirm=()=>true;w.print=()=>{};Object.defineProperty(w.crypto,'randomUUID',{value:require('node:crypto').randomUUID});
 Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async()=>{}}});
 w.fetch=async (url,opts={})=>{
  const cookie=jar.getCookieStringSync(base);const r=await fetch(new URL(url,base),{...opts,headers:{...opts.headers,...(cookie?{Cookie:cookie}:{}),...(opts.method?{Origin:base}:{})}});
  for(const c of r.headers.getSetCookie())jar.setCookieSync(c,base);
  return r;
 };
 const errors=[];w.addEventListener('error',e=>errors.push(e.message));w.eval(fs.readFileSync(path.resolve(__dirname,'../public/app.js'),'utf8'));
 await wait(()=>w.document.querySelector('[data-form="login"]'),'login screen');return {dom,w,errors};
}
function click(w,selector){const e=w.document.querySelector(selector);assert(e,'Missing '+selector);e.click()}
function set(w,name,value){const e=w.document.querySelector(`[name="${name}"]`);assert(e,'Missing input '+name);e.value=value}
function submit(w,selector){const form=w.document.querySelector(selector);assert(form,'Missing form '+selector);form.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}))}
async function login(w,email){set(w,'email',email);set(w,'password','FixturePassword123!');submit(w,'[data-form="login"]');await wait(()=>w.document.querySelector('.shell'),'signed-in shell')}
(async()=>{
 await new Promise((resolve,reject)=>{fixture.stdout.on('data',d=>{if(String(d).includes('FIXTURE_READY'))resolve()});fixture.once('exit',c=>reject(Error('Fixture exited '+c)));setTimeout(()=>reject(Error('Fixture start timeout')),10000).unref()});
 let {dom,w,errors}=await makeDom();await login(w,'owner@test.com');
 for(const name of ['Overview','Locations','Team','Timesheets','Requests','Clock station','Settings']){click(w,`[data-action="view"][data-view="${name}"]`);assert.equal(w.document.querySelector('h1').textContent,name==='Overview'?'Your stores, in sync.':name)}
 click(w,'[data-action="view"][data-view="Locations"]');click(w,'[data-action="store-new"]');set(w,'name','Second Store <img src=x onerror=alert(1)>');set(w,'address','Bankstown');submit(w,'[data-form="store"]');await wait(()=>!w.document.querySelector('.modal'),'store saved');assert(w.document.querySelector('.location-grid').textContent.includes('Second Store'));assert.equal(w.document.querySelectorAll('.location-grid img').length,0,'XSS-safe store name');
 click(w,'[data-action="view"][data-view="Team"]');click(w,'[data-action="staff-new"]');set(w,'name','Invited Staff');set(w,'email','invited@test.com');w.document.querySelector('[name="stores"]').checked=true;submit(w,'[data-form="staff"]');await wait(()=>!w.document.querySelector('.modal'),'staff invited');assert(w.document.querySelector('table').textContent.includes('Invited Staff'));
 click(w,'[data-action="view"][data-view="Timesheets"]');click(w,'[data-action="manual"]');set(w,'user_id','staff');set(w,'store_id','store');const start=Math.floor(Date.now()/1000)-7200,end=start+3600;set(w,'started',new Date(start*1000).toISOString());set(w,'ended',new Date(end*1000).toISOString());set(w,'reason','Verified missed shift');click(w,'[data-action="add-break"]');set(w,'break_started',new Date((start+600)*1000).toISOString());set(w,'break_ended',new Date((start+900)*1000).toISOString());submit(w,'[data-form="manual"]');await wait(()=>!w.document.querySelector('.modal'),'manual shift saved');assert(w.document.querySelector('table').textContent.includes('55m'));
 click(w,'[data-action="correct"]');set(w,'reason','Verified correction reason');submit(w,'[data-form="correct"]');await wait(()=>!w.document.querySelector('.modal'),'correction saved');click(w,'[data-action="audit"]');await wait(()=>w.document.querySelector('.audit-record'),'audit records');click(w,'[data-action="close-modal"]');click(w,'[data-action="approve"]');await wait(()=>w.document.querySelector('table').textContent.includes('approved'),'shift approved');
 assert.deepEqual(errors,[],'owner runtime errors');dom.window.close();
 ({dom,w,errors}=await makeDom('/tap/fixture-tag'));await login(w,'staff@test.com');await wait(()=>w.document.querySelector('[data-clock="in"]'),'staff clock screen');click(w,'[data-clock="in"]');await wait(()=>w.document.querySelector('[data-clock="out"]'),'clock in saved');click(w,'[data-clock="break"]');assert(w.document.querySelector('[name="paid"]'),'break type field');submit(w,'[data-form="break"]');await wait(()=>w.document.querySelector('[data-clock="resume"]'),'break saved');click(w,'[data-clock="resume"]');await wait(()=>w.document.querySelector('[data-clock="break"]'),'resume saved');click(w,'[data-clock="out"]');await wait(()=>w.document.querySelector('[data-clock="in"]'),'clock out saved');
 assert.equal(w.document.querySelector('[data-view="Team"]'),null,'staff has no Team navigation');assert.deepEqual(errors,[],'staff runtime errors');dom.window.close();console.log('Frontend integration passed: owner views/store/staff/manual-break/correction/audit/approval; staff login and full clock/break cycle; escaped store text. Visual browser QA still required.');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(()=>{fixture.kill();process.exit(process.exitCode||0)});
