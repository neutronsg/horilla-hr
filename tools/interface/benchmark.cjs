// Run with the bundled Node runtime and NODE_PATH set to its node_modules.
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
 const phase=process.argv[2]||'before';
 const base=process.env.HR_UI_URL||'http://127.0.0.1:8765';
 const state=JSON.parse(fs.readFileSync('/private/tmp/hr-interface/state.json'));
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 const pages={dashboard:'/dashboard/',employees:'/employee/employee-view/',employee_detail:`/employee/employee-view/${state.employee}/`,employee_edit:`/employee/employee-view-update/${state.employee}/`,leave:'/leave/request-view/',reimbursements:'/payroll/view-reimbursement/',payslips:'/payroll/view-payslip/',payslip_detail:`/payroll/view-payslip/${state.payslip}/`};
 const results=[];
 for(const [name,path] of Object.entries(pages)) {
  if(process.env.HR_UI_PAGES&&!process.env.HR_UI_PAGES.split(',').includes(name))continue;
  for(let run=0;run<3;run++) {
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   const page=await context.newPage(); const errors=[];const requests=[];
   page.on('pageerror',e=>errors.push(e.message));
   page.on('response',r=>{if(r.status()>=400)errors.push(`${r.status()} ${r.url()}`)});
   page.on('request',r=>requests.push(r.url()));
   await page.addInitScript(()=>{window.__longTasks=[];new PerformanceObserver(l=>window.__longTasks.push(...l.getEntries().map(e=>e.duration))).observe({type:'longtask',buffered:true});window.__swaps=[];document.addEventListener('htmx:afterSettle',()=>window.__swaps.push(performance.now()));});
   const t=Date.now();
   const response=await page.goto(base+path,{waitUntil:'load',timeout:60000});
   if(response.status()!==200)throw new Error(`${name}: HTTP ${response.status()}`);
   await page.waitForTimeout(2200);
   const metrics=await page.evaluate(()=>{const nav=performance.getEntriesByType('navigation')[0];const res=performance.getEntriesByType('resource');return {ttfb:nav.responseStart-nav.requestStart,html:nav.decodedBodySize,dcl:nav.domContentLoadedEventEnd,load:nav.loadEventEnd,resources:res.length,decodedBytes:res.reduce((s,r)=>s+r.decodedBodySize,nav.decodedBodySize),transferBytes:res.reduce((s,r)=>s+r.transferSize,nav.transferSize),server:nav.serverTiming,backend:res.filter(r=>r.serverTiming.length&&!new URL(r.name).pathname.startsWith('/static/')).map(r=>({url:r.name,timings:r.serverTiming,wait:r.responseStart-r.requestStart,duration:r.duration})),fcp:performance.getEntriesByName('first-contentful-paint')[0]?.startTime,resourceWait:Math.max(...res.map(r=>r.responseEnd),0)-nav.responseEnd,longTasks:window.__longTasks.reduce((a,b)=>a+b,0),lastSwap:window.__swaps.at(-1),duplicates:res.filter(r=>r.name.endsWith('/actions.js')).map(r=>r.name)};});
   if(run===0)await page.evaluate(()=>document.querySelectorAll('.driver-overlay,.driver-popover').forEach(e=>e.remove()));
   if(run===0)await page.screenshot({path:`docs/interface/screenshots/${phase}-${name}.png`,fullPage:true});
   results.push({name,run,path,status:await page.title(),...metrics,errors,requestCount:requests.length});
   console.log(name,run,Math.round(metrics.dcl),metrics.resources,metrics.decodedBytes,errors.slice(0,2));
   await context.close();
  }
 }
 const output=`docs/interface/${phase}.json`;
 const previous=process.env.HR_UI_PAGES&&fs.existsSync(output)?JSON.parse(fs.readFileSync(output)).filter(r=>!process.env.HR_UI_PAGES.split(',').includes(r.name)):[];
 fs.writeFileSync(output,JSON.stringify([...previous,...results],null,2));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
