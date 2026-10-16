// Existing synthetic profiles only. Verify coordinates and painting as well as clicks.
const {chromium} = require('playwright');
const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');
const base = process.env.HR_UI_URL || 'http://127.0.0.1:8768';
const output = process.env.HR_UI_OUTPUT || '/private/tmp/hr-interface/profile-more';
const profileId = process.env.HR_UI_PROFILE_ID || '1';
const credentials = process.env.HR_UI_CREDENTIALS
    ? [...fs.readFileSync(process.env.HR_UI_CREDENTIALS, 'utf8').matchAll(/username: (\S+)\n  password: (\S+)/g)].map(m => [m[1], m[2]]) : null;
const roles = credentials ? [['admin', 0], ['hr-manager', 2], ['employee', 1]] : [['preview', null]];
const checks = [], errors = [];
fs.mkdirSync(output, {recursive: true});

async function geometry(summary, panel) {
    const anchor = await summary.boundingBox(), box = await panel.boundingBox();
    const viewport = summary.page().viewportSize();
    assert.ok(box.x >= 11 && box.x + box.width <= viewport.width - 11, JSON.stringify(box));
    assert.ok(box.y >= 11 && box.y + box.height <= viewport.height - 11, JSON.stringify(box));
    const expectedLeft = Math.max(12, Math.min(viewport.width - box.width - 12, anchor.x));
    assert.ok(Math.abs(box.x - expectedLeft) < 1, 'Menu aligns with More');
    assert.ok(Math.abs(box.y - anchor.y - anchor.height - 6) < 1 || Math.abs(box.y + box.height - anchor.y + 6) < 1, 'Menu stays next to its trigger');
    assert.ok(await panel.evaluate(e => e.contains(document.elementFromPoint(e.getBoundingClientRect().left + 20, e.getBoundingClientRect().top + 20))), 'Menu paints above page content');
}

(async () => {
    const browser = await chromium.launch({channel: 'chrome', headless: true});
    try {
        for (const [role, index] of roles) {
            const context = await browser.newContext({viewport: {width: 1440, height: 1000},
                extraHTTPHeaders: credentials ? {} : {'X-HR-UI-Actor': process.env.HR_UI_ACTOR || 'zeyu+ui-admin@neutron.sg'}});
            const page = await context.newPage();
            page.on('pageerror', e => errors.push({role, message: e.message}));
            if (credentials) {
                await page.goto(base + '/login/');
                await page.locator('#username').fill(credentials[index][0]);
                await page.locator('#password').fill(credentials[index][1]);
                await Promise.all([page.waitForNavigation(), page.locator('button[type=submit]').click()]);
            }
            const profilePath = index === 1
                ? await page.locator('.neutron-profile-menu a').filter({hasText: 'My profile'}).getAttribute('href')
                : '/employee/employee-view/' + profileId + '/';
            assert.equal((await page.goto(base + profilePath)).status(), 200);
            await page.waitForTimeout(700);
            const summary = page.locator('.neutron-profile-overflow>summary');
            const panel = page.locator('.neutron-profile-overflow>.neutron-action-menu-content');
            for (const [width, height] of [[1440, 1000], [1024, 768], [390, 600]]) {
                await page.setViewportSize({width, height});
                for (const dark of [false, true]) {
                    await page.evaluate(d => { document.body.classList.toggle('dark', d); document.documentElement.classList.toggle('dark', d); }, dark);
                    await summary.scrollIntoViewIfNeeded();
                    const before = await page.locator('.neutron-profile-content').boundingBox();
                    await summary.click();
                    await page.waitForTimeout(80);
                    await geometry(summary, panel);
                    assert.deepEqual(await page.locator('.neutron-profile-content').boundingBox(), before, 'Opening More does not move page content');
                    const option = panel.locator('button[data-tab]').first();
                    await option.hover();
                    assert.equal(await option.evaluate(e => getComputedStyle(e).borderBottomWidth), '0px', 'Menu options do not inherit tab underlines');
                    assert.equal(await option.evaluate(e => getComputedStyle(e).color), await page.locator('body').evaluate(e => getComputedStyle(e).color), 'Menu options use the shared readable text colour');
                    assert.ok((await option.boundingBox()).height <= 36, 'Menu option height stays compact');
                    await panel.evaluate(e => { e.scrollTop = e.scrollHeight; });
                    assert.equal(await panel.isVisible(), true, 'Internal scrolling keeps the menu open');
                    await page.screenshot({path: path.join(output, role + '-' + width + '-' + (dark ? 'dark' : 'light') + '.png')});
                    await summary.focus();
                    await page.keyboard.press('Escape');
                    assert.equal(await panel.isVisible(), false);
                    assert.equal(await summary.evaluate(e => e === document.activeElement), true);
                    checks.push({role, width, height, dark, name: 'anchored menu, stable content, compact options, keyboard closure'});
                    console.log('PASS', role, width, dark ? 'dark' : 'light');
                }
            }
            await page.setViewportSize({width: 1440, height: 1000});
            await page.locator('.usertablist>li>button[data-tab="About"]').click();
            await page.waitForTimeout(500);
            await page.locator('.oh-main-content').evaluate(e => { e.scrollTop = 180; });
            await summary.focus();
            await page.keyboard.press('ArrowDown');
            await geometry(summary, panel);
            assert.equal(await panel.evaluate(e => e.contains(document.activeElement)), true);
            await page.screenshot({path: path.join(output, role + '-sticky-dark.png')});
            await page.locator('.oh-main-content').evaluate(e => { e.scrollTop = 0; });
            await page.waitForTimeout(50);
            assert.equal(await panel.isVisible(), false, 'Page scrolling dismisses the anchored menu');
            await summary.click();
            const selected = await panel.locator('button[data-tab]').first().getAttribute('data-tab');
            await panel.locator('button[data-tab]').first().click();
            await page.waitForTimeout(450);
            assert.equal(await panel.isVisible(), false);
            assert.equal(await summary.locator('.neutron-profile-overflow-label').innerText(), selected);
            await summary.click();
            await page.locator('.neutron-profile-header h2').click();
            assert.equal(await panel.isVisible(), false, 'Outside click closes the menu');
            checks.push({role, name: 'sticky bar, keyboard entry, permitted tab selection, scroll and outside closure'});
            await context.close();
        }
        assert.deepEqual(errors, []);
    } catch (error) {
        const page = browser.contexts().at(-1)?.pages().at(-1);
        if (page) await page.screenshot({path: path.join(output, 'failure.png')});
        throw error;
    } finally {
        fs.writeFileSync(path.join(output, 'checks.json'), JSON.stringify({checks, errors}, null, 2));
        await browser.close();
    }
})().catch(e => { console.error(e); process.exitCode = 1; });
