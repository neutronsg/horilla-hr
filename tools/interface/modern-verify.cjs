const {chromium}=require('playwright');const fs=require('fs');const assert=require('assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[],checks=[];page.on('pageerror',e=>errors.push(e.message));
 const base=process.env.HR_UI_URL||'http://127.0.0.1:8767';const state=JSON.parse(fs.readFileSync('/private/tmp/hr-interface/state.json'));
 async function go(path){const r=await page.goto(base+path);assert.equal(r.status(),200);await page.waitForTimeout(1200);await page.evaluate(()=>{document.querySelectorAll('.driver-overlay,.driver-popover').forEach(e=>e.remove());document.body.classList.remove('driver-active')});}
 async function check(name,fn){await fn();checks.push({name,pass:true});console.log('PASS',name);}
 await go('/employee/employee-view/');
 await check('Neutron palette and expanded sidebar',async()=>{assert.ok(await page.locator('.sideboxmain').first().evaluate(e=>e.getBoundingClientRect().width>150));assert.equal(await page.locator('body').evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--primary-600').trim()),'#051c97');});
 await check('row selection does not open a detail modal',async()=>{const checkbox=page.locator('.list-table-row').first();await checkbox.check();assert.equal(await page.locator('.oh-modal--show').count(),0);await checkbox.uncheck();});
 await check('burst search emits one list request and displays matching employee',async()=>{
  let count=0;const listener=r=>{if(r.url().includes('/employees-list/'))count++};page.on('request',listener);
  for(const term of ['Q','QA','QA 03']) {await page.locator('input[name=search]').first().fill(term);await page.waitForTimeout(70);}
  await page.waitForTimeout(750);page.off('request',listener);assert.equal(count,1);assert.equal(await page.locator('.fixed-table tbody tr').count(),1);assert.match(await page.locator('.fixed-table tbody').innerText(),/Casey QA 03/);
 });
 await check('20 HTMX swaps retain one Select2 instance and stable document handlers',async()=>{
  await page.evaluate(()=>window.__select2Before=jQuery('.oh-select').first().data('select2'));
  const before=await page.evaluate(()=>({events:Object.fromEntries(Object.entries(jQuery._data(document,'events')).map(([k,v])=>[k,v.length])),select:jQuery('.oh-select').first().data('select2')?.id,createClick:(jQuery._data(document.querySelector('[data-toggle="oh-modal-toggle"]'),'events')?.click||[]).length}));
  for(let i=0;i<20;i++)await page.evaluate(async()=>{await htmx.ajax('GET','/employee/employees-list/?search=QA%2003',{target:'#listContainer'})});
  const after=await page.evaluate(()=>({events:Object.fromEntries(Object.entries(jQuery._data(document,'events')).map(([k,v])=>[k,v.length])),select:jQuery('.oh-select').first().data('select2')?.id,createClick:(jQuery._data(document.querySelector('[data-toggle="oh-modal-toggle"]'),'events')?.click||[]).length}));assert.deepEqual(after,before);assert.equal(await page.evaluate(()=>jQuery('.oh-select').first().data('select2')===window.__select2Before),true);
  assert.equal(await page.locator('script[src*="/employee/actions.js"]').count(),1);
 });
 await check('pagination replaces list without document navigation',async()=>{
  const requests=[];const listener=r=>requests.push({url:r.url(),type:r.resourceType()});page.on('request',listener);
  await page.locator('input[name=search]').first().fill('');await page.waitForTimeout(650);
  const pagination=await page.locator('[hx-get]').evaluateAll(es=>es.filter(e=>/page=2(?:&|$)/.test(e.getAttribute('hx-get'))).map(e=>e.getAttribute('hx-get')));

  if(pagination.length){await page.evaluate(u=>document.querySelector(`[hx-get="${CSS.escape(u)}"]`).click(),pagination[0]);}
  else {const pageInput=page.locator('input[name=page]').first();assert.ok(await pageInput.count());await pageInput.fill('2');await pageInput.press('Enter');}
  await page.waitForTimeout(650);page.off('request',listener);assert.equal(requests.filter(r=>r.type==='document').length,0);assert.ok(requests.some(r=>r.url.includes('page=2')));assert.equal(await page.locator('.fixed-table tbody tr').count(),20);
 });
 await check('filter and empty state preserve permissions and recover',async()=>{
  const select=page.locator('select[name=is_active]').first();await select.selectOption('False',{force:true});await page.locator('#applyFilter').evaluate(e=>e.click());await page.waitForTimeout(550);assert.equal(await page.locator('.fixed-table tbody tr').count(),0);assert.match(await page.locator('#listContainer').innerText(),/No|no|empty|Empty/);
  await select.selectOption('True',{force:true});await page.locator('#applyFilter').evaluate(e=>e.click());await page.waitForTimeout(550);assert.ok(await page.locator('.fixed-table tbody tr').count()>0);
 });
 await check('network failure clears busy feedback and retry succeeds',async()=>{
  await page.route('**/employee/employees-list/**',route=>route.abort());await page.locator('input[name=search]').first().fill('offline');await page.waitForTimeout(550);assert.match(await page.locator('.neutron-status').innerText(),/Unable/);assert.equal(await page.locator('.neutron-loading.active').count(),0);
  await page.unroute('**/employee/employees-list/**');await page.locator('input[name=search]').first().fill('QA 03');await page.waitForTimeout(550);assert.equal(await page.locator('.fixed-table tbody tr').count(),1);
 });
 await check('employee details and editable fields render',async()=>{await go(`/employee/employee-view/${state.employee}/`);assert.match(await page.locator('#ohMainContent').innerText(),/QA 03|QA 00|QA/);await page.screenshot({path:'docs/interface/modern/screenshots/current-employee_detail.png',fullPage:true});await go(`/employee/employee-view-update/${state.employee}/`);assert.ok(await page.locator('input[name=employee_first_name]').count());await page.screenshot({path:'docs/interface/modern/screenshots/current-employee_edit.png',fullPage:true});});
 for(const [name,path,url] of [['leave','/leave/request-view/','/leave/leave-request-creation'],['reimbursement','/payroll/view-reimbursement/','/payroll/reimbursement-create/']]) {
  await go(path);
  await check(name+' modal loads, traps keyboard focus, and returns focus on Escape',async()=>{
   const create=page.locator('[hx-get][data-toggle="oh-modal-toggle"]').filter({hasText:'Create'}).first();assert.ok(await create.count());await create.click();await page.waitForTimeout(700);const modal=page.locator('.oh-modal--show').last();assert.ok(await modal.count());assert.ok(await modal.locator('input,select,textarea').count());assert.equal(await modal.getAttribute('aria-modal'),'true');
   await page.screenshot({path:`docs/interface/modern/screenshots/current-${name}-form.png`,fullPage:true});
   await page.keyboard.press('Shift+Tab');assert.ok(await modal.evaluate(e=>e.contains(document.activeElement)));await page.keyboard.press('Escape');await page.waitForTimeout(50);assert.equal(await page.locator('.oh-modal--show').count(),0);assert.ok(await create.evaluate(e=>e===document.activeElement));
  });
 }
 await check('repeated modal closure releases Select2 widget cache',async()=>{
  const cache=()=>page.evaluate(()=>Object.keys(jQuery.fn.select2.amd.require('select2/utils').__cache).length);
  await page.waitForTimeout(250);const before=await cache();
  for(let i=0;i<3;i++){await page.locator('#ohMainContent [hx-get="/payroll/reimbursement-create/"]').first().click();await page.locator('.oh-modal--show form').waitFor();await page.waitForTimeout(70);await page.keyboard.press('Escape');await page.waitForTimeout(300);}
  assert.equal(await cache(),before);assert.equal(await page.locator('#genericModalBody select').count(),0);
 });
 await go('/leave/request-view/');
 await check('approval confirmation cancels without a decision request',async()=>{
  const requests=[];const listener=r=>{if(r.url().includes('/request-approve/'))requests.push(r.url())};page.on('request',listener);
  await page.locator('[hx-confirm][title=Approve]').first().click();await page.locator('.swal2-popup').waitFor();await page.screenshot({path:'docs/interface/modern/screenshots/current-leave-approval.png',fullPage:true});await page.locator('.swal2-cancel').click();await page.locator('.swal2-container').waitFor({state:'hidden'});page.off('request',listener);assert.deepEqual(requests,[]);assert.equal(await page.locator('.oh-modal--show').count(),0);
 });
 await check('confirmed approval forwards exactly one request',async()=>{
  let decisions=0;await page.route('**/leave/request-approve/**',async route=>{decisions++;await route.fulfill({status:200,body:''});});
  await page.locator('[hx-confirm][title=Approve]').first().click();await page.locator('.swal2-confirm').click();await page.locator('.swal2-container').waitFor({state:'hidden'});assert.equal(decisions,1);assert.equal(await page.locator('.oh-modal--show').count(),0);await page.unroute('**/leave/request-approve/**');
 });
 await check('administrator exception dialog still requires a reason',async()=>{
  await page.locator('.neutron-action-menu summary').first().click();await page.locator('[hx-get*="admin-intervention"]').first().click();await page.locator('.oh-modal--show textarea[name=reason]').waitFor();assert.equal(await page.locator('textarea[name=reason]').getAttribute('required'),'');await page.screenshot({path:'docs/interface/modern/screenshots/current-leave-intervention.png',fullPage:true});await page.keyboard.press('Escape');
 });
 await check('payslip detail renders financial fields',async()=>{await go(`/payroll/view-payslip/${state.payslip}/`);assert.match(await page.locator('#ohMainContent').innerText(),/4,?000|4000/);await page.screenshot({path:'docs/interface/modern/screenshots/current-payslip_detail.png',fullPage:true});});
 await check('HTMX navigation loads report dependencies once',async()=>{
  await go('/employee/employee-view/');
  const link=page.locator('#sidebar a[href*="/report/"]').first();assert.ok(await link.count());await link.evaluate(e=>e.click());await page.waitForTimeout(1500);
  assert.ok(await page.evaluate(()=>typeof jQuery.fn.pivotUI==='function'));assert.ok(await page.locator('#ohMainContent').innerText());
  const n=await page.locator('script[src$="pivottable.min.js"]').count();await page.evaluate(()=>window.neutronEnsurePageAssets('/report/employee/'));assert.equal(await page.locator('script[src$="pivottable.min.js"]').count(),n);
 });
 await check('slow report assets cannot overwrite newer employee navigation',async()=>{
  await go('/employee/employee-view/');await page.route('**/pivottable_plot.min.js',async route=>{await new Promise(r=>setTimeout(r,500));await route.continue();});
  const report=page.locator('#sidebar a[href*="/report/"]').first();await report.evaluate(e=>e.click());await page.waitForTimeout(40);await page.locator('#sidebar a[href="/employee/employee-view/"]').first().evaluate(e=>e.click());await page.waitForTimeout(1300);assert.match(page.url(),/employee-view/);assert.match(await page.locator('#ohMainContent').innerText(),/Employees/);await page.unroute('**/pivottable_plot.min.js');
 });
 await check('dashboard charts render with local ApexCharts',async()=>{await go('/dashboard/');await page.waitForTimeout(1200);assert.ok(await page.locator('.apexcharts-canvas').count());assert.equal(await page.locator('script[src*="cdn.jsdelivr"]').count(),0);await page.screenshot({path:'docs/interface/modern/screenshots/current-dashboard.png',fullPage:true});});
 await check('employee self service dashboard has local chart dependency',async()=>{await go('/ess/');assert.equal(await page.evaluate(()=>typeof ApexCharts),'function');assert.equal(await page.locator('script[src*="cdn.jsdelivr"]').count(),0);});
 await check('mobile and dark layout',async()=>{await page.setViewportSize({width:390,height:844});await go('/employee/employee-view/');assert.equal(await page.locator('#sidebar').evaluate(e=>Math.round(e.getBoundingClientRect().width)),64);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);assert.equal(await page.locator('.action-col-cell').first().evaluate(e=>getComputedStyle(e).position),'static');await page.screenshot({path:'docs/interface/modern/screenshots/current-mobile.png',fullPage:true});await page.evaluate(()=>{document.documentElement.classList.add('dark');document.body.classList.add('dark')});await page.screenshot({path:'docs/interface/modern/screenshots/current-mobile-dark.png',fullPage:true});});
 assert.deepEqual(errors,[]);
 fs.writeFileSync('docs/interface/modern/verification.json',JSON.stringify({checks,errors},null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
