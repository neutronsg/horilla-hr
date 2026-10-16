// Synthetic-only regression checks for shared navigation and select controls.
const {chromium} = require('playwright');
const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');
const base = process.env.HR_UI_URL || 'http://127.0.0.1:8791';
const output = process.env.HR_UI_OUTPUT || '/private/tmp/hr-interface/document-refinement';
fs.mkdirSync(output, {recursive: true});

(async () => {
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  const results = [], errors = [];
  try {
    const page = await browser.newPage({viewport: {width: 768, height: 950}, extraHTTPHeaders: {'X-HR-UI-Actor': 'zeyu+ui-admin@neutron.sg'}});
    page.on('pageerror', error => errors.push(error.message));
    const sidebarCases = [768, 991, 1440].flatMap(width =>
      ['Employee', 'Recruitment', 'Reports'].map(menu => ({width, menu})));
    for (const {width, menu} of sidebarCases) {
      await page.setViewportSize({width, height: 950});
      await page.goto(base + '/employee/company-documents/');
      await page.mouse.move(width - 10, 900);
      await page.waitForTimeout(250);
      const owner = page.locator(`.sideboxmain[data-menu="${menu}"]`);
      await owner.hover();
      await page.waitForTimeout(250);
      const rail = await page.locator('#sidebar').boundingBox();
      const panel = await page.locator('#sidebarFlyout').boundingBox();
      assert.equal(rail.width, 232);
      assert.equal(panel.x, rail.x + rail.width + 6);
      await page.evaluate(() => {
        window.railFrames = []; window.recordRail = true;
        const frame = () => {
          const rail = document.querySelector('#sidebar');
          window.railFrames.push({width: rail.getBoundingClientRect().width,
            labelsVisible: getComputedStyle(rail.querySelector('.oh-sidebar-label')).display !== 'none'});
          if (window.recordRail) requestAnimationFrame(frame);
        };
        requestAnimationFrame(frame);
      });
      // Stay in the gap beyond the close timer, then move into the submenu.
      await page.mouse.move(rail.x + rail.width + 3, panel.y + 18, {steps: 8});
      await page.waitForTimeout(250);
      await page.mouse.move(panel.x + 18, panel.y + 18, {steps: 8});
      await page.waitForTimeout(180);
      const frames = await page.evaluate(() => {window.recordRail = false; return window.railFrames;});
      assert.ok(frames.length > 5);
      assert.ok(frames.every(frame => frame.width === 232 && frame.labelsVisible), 'rail blink while entering flyout');
      assert.ok(await page.locator('#sidebarFlyout').isVisible());
      results.push({name: 'gap crossing holds rail and labels', menu, width, samples: frames.length, minimumWidth: Math.min(...frames.map(frame => frame.width))});

      // Leaving keyboard focus must not close a menu still under the pointer.
      // Focusout can schedule a fresh close after mouseenter has cancelled one.
      const submenuLinks = page.locator('#sidebarFlyout a');
      for (const index of [0, await submenuLinks.count() - 1]) {
        await submenuLinks.nth(index).hover();
        await submenuLinks.last().focus();
        await page.keyboard.press('Tab');
        await page.waitForTimeout(250);
        assert.ok(await page.locator('#sidebarFlyout').isVisible(), 'focusout closed a hovered submenu');
        assert.equal((await page.locator('#sidebar').boundingBox()).width, 232);
      }
      results.push({name: 'hovered submenu survives focus leaving its last link', menu, width});
      await page.mouse.move(width - 10, 900);
      await page.waitForTimeout(350);
      assert.equal(await page.locator('#sidebarFlyout').isVisible(), false);
      if (width < 992) assert.equal((await page.locator('#sidebar').boundingBox()).width, 64);
      await owner.focus();
      await page.keyboard.press('ArrowRight');
      assert.ok(await page.locator('#sidebarFlyout a').first().evaluate(element => element === document.activeElement));
      await page.keyboard.press('ArrowDown');
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('#sidebarFlyout').isVisible(), false);
      assert.ok(await owner.evaluate(element => element === document.activeElement));
    }

    for (const width of [390, 1440]) {
      await page.setViewportSize({width, height: 950});
      await page.goto(base + '/employee/company-documents/');
      for (const dark of [false, true]) {
        await page.evaluate(value => {document.body.classList.toggle('dark', value); document.documentElement.classList.toggle('dark', value);}, dark);
        const category = page.getByRole('combobox', {name: /Category/});
        await category.click();
        const popup = page.locator('.select2-dropdown:visible');
        await popup.waitFor();
        const rect = await popup.boundingBox();
        assert.ok(rect.x >= 0 && rect.x + rect.width <= width + 1);
        assert.equal(await popup.evaluate(element => getComputedStyle(element).borderRadius), '10px');
        await page.screenshot({path: path.join(output, `category-${width}-${dark ? 'dark' : 'light'}.png`), fullPage: true});
        await page.getByRole('option', {name: 'Insurance and benefits', exact: true}).click();
        assert.equal(await page.locator('#cd-category').inputValue(), 'insurance');
        await page.getByRole('combobox', {name: /Status/}).click();
        await page.getByRole('option', {name: 'Drafts', exact: true}).click();
        assert.equal(await page.locator('#cd-state').inputValue(), 'draft');
        results.push({name: 'category and status options work', width, dark});
      }
    }

    await page.setViewportSize({width: 1440, height: 950});
    // Open the app's real filter panels and choose an option without applying.
    for (const route of ['/employee/employee-view/', '/leave/request-view/', '/payroll/view-reimbursement/']) {
      await page.goto(base + route);
      await page.locator('[data-neutron-filter]').first().waitFor();
      const trigger = page.locator('[data-neutron-filter]').first();
      await trigger.click();
      const wrapper = trigger.locator('xpath=..');
      if (!await wrapper.locator('.select2-selection:visible,select:visible').count()) {
        await wrapper.locator('.oh-accordion-header').first().click();
      }
      const selection = wrapper.locator('.select2-selection:visible').first();
      if (await selection.count()) {
        await selection.click();
        const options = page.locator('.select2-results__option[aria-selected]:not([aria-disabled=true]):visible');
        await options.first().waitFor();
        await options.first().click();
      } else {
        const native = wrapper.locator('select:visible').first();
        await native.selectOption({index: 1});
      }
      assert.equal(await trigger.getAttribute('aria-expanded'), 'true');
      await page.keyboard.press('Escape');
      assert.equal(await trigger.getAttribute('aria-expanded'), 'false');
      results.push({name: 'filter stays open while selecting options', route});
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'navigation-selects.json'), JSON.stringify({results, errors}, null, 2));
    console.log(JSON.stringify({checks: results.length, errors}));
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
