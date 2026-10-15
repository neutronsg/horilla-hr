const {chromium}=require('playwright');const fs=require('fs');const assert=require('assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});const results=[];
 for(const phase of ['before','after']) for(const kind of ['approval','intervention','claim_submission']) for(let run=0;run<3;run++) {
  const context=await browser.newContext({viewport:{width:1440,height:1000}});const page=await context.newPage();const requests=[],errors=[];
  page.on('pageerror',e=>errors.push(e.message));const base=`http://127.0.0.1:${phase==='before'?8766:8765}`;
  await page.goto(base+(kind==='claim_submission'?'/payroll/view-reimbursement/':'/leave/request-view/'));await page.waitForTimeout(1000);await page.evaluate(()=>document.querySelectorAll('.driver-overlay,.driver-popover').forEach(e=>e.remove()));
  page.on('request',r=>requests.push(r.url()));let nativeMs=null;let readyMs=null;
  console.log('Measuring',phase,kind,run);
  const start=Date.now();page.on('dialog',async dialog=>{nativeMs=Date.now()-start;await dialog.dismiss()});
  if(kind==='approval') {
   await page.locator('[hx-confirm][title=Approve]').first().click();
   if(nativeMs===null){await page.locator('.swal2-popup').waitFor();readyMs=Date.now()-start;if(phase==='after'&&run===0)await page.screenshot({path:'docs/interface/screenshots/after-leave-approval.png'});await page.locator('.swal2-cancel').click();}
   assert.equal(requests.filter(u=>u.includes('/request-approve/')).length,0);
  } else {
   const selector=kind==='intervention'?'[hx-get*="admin-intervention"]':'#ohMainContent [hx-get="/payroll/reimbursement-create/"]';
   await page.locator(selector).first().click();await page.locator('.oh-modal--show form').waitFor();await page.locator('.oh-modal--show input, .oh-modal--show textarea, .oh-modal--show select').first().waitFor({state:'attached'});
   readyMs=Date.now()-start;
   if(kind==='intervention')assert.equal(await page.locator('.oh-modal--show textarea[name=reason]').count(),1);
  }
  results.push({phase,kind,run,readyMs:readyMs??nativeMs,requests,errors});await context.close();
 }
 fs.writeFileSync('docs/interface/modal-performance.json',JSON.stringify(results,null,2));console.log(results.map(r=>({phase:r.phase,kind:r.kind,readyMs:r.readyMs,errors:r.errors})));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
