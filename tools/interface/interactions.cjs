const { chromium }=require('playwright');const fs=require('fs');
(async()=>{
const phase=process.argv[2]||'before'; const browser=await chromium.launch({headless:true,channel:'chrome'});const page=await browser.newPage({viewport:{width:1440,height:1000}});const results=[];const state=JSON.parse(fs.readFileSync('/private/tmp/hr-interface/state.json'));
for(const [name,path] of Object.entries({employees:'/employee/employee-view/',leave:'/leave/request-view/',reimbursements:'/payroll/view-reimbursement/',payslips:'/payroll/view-payslip/'})) {
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:8765'+path);await page.waitForTimeout(1800);await page.evaluate(()=>{document.querySelectorAll('.driver-overlay,.driver-popover').forEach(e=>e.remove());document.body.classList.remove('driver-active');});
 await page.screenshot({path:`docs/interface/screenshots/${phase}-${name}.png`,fullPage:true});
 const search=page.locator('input[name=search]').first(); const swaps=[]; const requests=[];
 await page.exposeFunction('reportSwap'+name,v=>swaps.push(v));
 await page.evaluate(n=>{document.addEventListener('htmx:afterSettle',e=>window['reportSwap'+n]({id:e.detail.target.id,time:performance.now()}));},name);
 page.on('request',r=>requests.push(r.url()));
 if(await search.count()) {
  for(let i=0;i<3;i++) {const t=await page.evaluate(()=>performance.now()); const prev=swaps.length; await search.fill(i%2?'':'QA 03');await search.dispatchEvent('keyup');await page.waitForTimeout(1000);results.push({name,action:'search',iteration:i,settleMs:swaps.slice(prev).map(s=>s.time-t),requests:requests.splice(0)});}
 }
 const pagination=await page.locator('[hx-get]').evaluateAll(es=>es.filter(e=>e.getAttribute('hx-get').includes('page=2')).map(e=>({tag:e.tagName,id:e.id,url:e.getAttribute('hx-get')})));
 if(pagination[0]) {const prev=swaps.length,t=await page.evaluate(()=>performance.now());await page.locator('[hx-get]').filter({hasText:'___'}).count();await page.evaluate(u=>document.querySelectorAll('[hx-get]').forEach(e=>{if(e.getAttribute('hx-get')===u)e.click()}),pagination[0].url);await page.waitForTimeout(1200);results.push({name,action:'pagination',settleMs:swaps.slice(prev).map(s=>s.time-t),requests:requests.splice(0)});}
 results.push({name,errors,handlers:await page.evaluate(()=>({document:Object.fromEntries(Object.entries(jQuery._data(document,'events')||{}).map(([k,v])=>[k,v.length])),select2:document.querySelectorAll('.select2-container').length}))});
}
await page.goto('http://127.0.0.1:8765/dashboard/');await page.waitForTimeout(1800);await page.evaluate(()=>document.querySelectorAll('.driver-overlay,.driver-popover').forEach(e=>e.remove()));await page.screenshot({path:`docs/interface/screenshots/${phase}-dashboard.png`,fullPage:true});
fs.writeFileSync(`docs/interface/${phase}-interactions.json`,JSON.stringify(results,null,2));console.log(results);await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
