/* Shared feedback and keyboard behavior. One registration per full document. */
(function () {
    if (window.neutronInterface) return;
    window.neutronInterface = true;
    const outlineNames = new Set(['accessibility','business','checkmark-done-circle','filter-circle','information','move','add','add-circle','albums','alert','alert-circle','archive','arrow-back','arrow-down','arrow-down-circle','arrow-forward','arrow-forward-circle','arrow-redo','arrow-undo','arrow-up','at','attach','ban','bar-chart','briefcase','calendar','call','camera','caret-back','caret-down','caret-forward','caret-up','chatbox','checkmark','checkmark-circle','checkmark-done','chevron-back','chevron-down','chevron-forward','chevron-up','close','close-circle','cloud-download','cloud-upload','copy','create','document','document-attach','document-text','download','duplicate','ellipsis-horizontal','ellipsis-vertical','eye','eye-off','filter','folder','heart','help-circle','information-circle','link','list','location','lock-closed','log-in','log-out','mail','notifications','open','options','paper-plane','pencil','people','person','person-add','print','refresh','reload','save','search','send','settings','shield-checkmark','swap-horizontal','time','trash','warning']);
    function outlineIcons(root = document) {
        const icons = [...root.querySelectorAll('ion-icon[name]')];
        if (root.matches?.('ion-icon[name]')) icons.push(root);
        icons.forEach(icon => {
            const name = icon.getAttribute('name');
            // Filled stars/hearts are meaningful rating/selection data, rather than actions.
            if (outlineNames.has(name) && !icon.closest('.oh-rate,.oh-rating,[data-rating],.rating')) icon.setAttribute('name', name + '-outline');
        });
    }
    document.addEventListener('DOMContentLoaded', () => {
        outlineIcons();
        new MutationObserver(changes => changes.forEach(change => {
            if (change.type === 'attributes') outlineIcons(change.target);
            else change.addedNodes.forEach(node => { if (node.nodeType === 1) outlineIcons(node); });
        })).observe(document.body, {childList:true, subtree:true, attributes:true, attributeFilter:['name']});
    });
    let popoverId = 0;
    function popoverParts(wrapper) {
        return {panel: wrapper.querySelector(':scope > .dropdown-content'), trigger: wrapper.querySelector(':scope > button, :scope > [data-neutron-filter], :scope > [role="button"]')};
    }
    function setPopover(wrapper, open, restoreFocus = false) {
        const {trigger, panel} = popoverParts(wrapper);
        if (!trigger || !panel) return;
        if (!open) panel.querySelectorAll('select.select2-hidden-accessible').forEach(select => {
            const picker = window.jQuery?.(select).data('select2');
            if (picker?.isOpen()) picker.close();
        });
        wrapper.classList.toggle('neutron-popover-open', open);
        wrapper.classList.remove('force-open');
        trigger.setAttribute('aria-expanded', String(open));
        panel.inert = !open;
        if (restoreFocus) trigger.focus({preventScroll: true});
    }
    function popoverOwner(target) {
        const wrapper = target.closest('.neutron-popover');
        if (wrapper) return wrapper;
        // Select2 mounts its option/search panel under body, outside the filter.
        for (const select of document.querySelectorAll('.neutron-popover-open select.select2-hidden-accessible')) {
            const picker = window.jQuery?.(select).data('select2');
            if (picker?.dropdown?.$dropdown?.[0]?.contains(target)) return select.closest('.neutron-popover');
        }
        return null;
    }
    function closePopovers(except = null) {
        document.querySelectorAll('.neutron-popover-open').forEach(wrapper => { if (!except || !wrapper.contains(except)) setPopover(wrapper, false); });
    }
    function preparePopovers() {
        document.querySelectorAll('.dropdown-wrapper:not(.neutron-popover)').forEach(wrapper => {
            const {trigger, panel} = popoverParts(wrapper);
            if (!trigger || !panel) return;
            wrapper.classList.add('neutron-popover');
            panel.id ||= 'neutron-popover-' + ++popoverId;
            trigger.setAttribute('aria-controls', panel.id);
            trigger.setAttribute('aria-expanded', 'false');
            trigger.setAttribute('aria-haspopup', panel.getAttribute('role') === 'dialog' ? 'dialog' : 'true');
            if (!trigger.matches('button')) { trigger.setAttribute('role', 'button'); trigger.tabIndex = 0; }
            panel.inert = true;
        });
        document.querySelectorAll('.ngb-crumb-select-wrap').forEach(wrapper => {
            const trigger = wrapper.querySelector('.ngb-crumb-select-trigger');
            const panel = wrapper.querySelector('.ngb-crumb-dropdown');
            if (!trigger || !panel || trigger.hasAttribute('aria-controls')) return;
            panel.id ||= 'neutron-picker-' + ++popoverId;
            panel.setAttribute('role', 'menu');
            panel.querySelectorAll('button').forEach(item => item.setAttribute('role', 'menuitem'));
            trigger.setAttribute('aria-controls', panel.id);
            trigger.setAttribute('aria-haspopup', 'menu');
            trigger.setAttribute('aria-expanded', 'false');
            trigger.addEventListener('click', () => trigger.setAttribute('aria-expanded', String(wrapper.classList.contains('force-open'))));
        });
    }
    document.addEventListener('DOMContentLoaded', preparePopovers);
    document.addEventListener('htmx:afterSettle', preparePopovers);
    document.addEventListener('click', event => {
        preparePopovers();
        document.querySelectorAll('.ngb-crumb-select-wrap.force-open').forEach(picker => {
            if (!picker.contains(event.target) || event.target.closest('.ngb-crumb-option')) {
                picker.classList.remove('force-open');
                picker.querySelector('.ngb-crumb-select-trigger')?.setAttribute('aria-expanded', 'false');
                picker.closest('#ngbToolbarPanel')?.classList.remove('ngb-dropdown-open');
            }
        });
        const wrapper = popoverOwner(event.target);
        if (wrapper) {
            const {trigger} = popoverParts(wrapper);
            if (trigger?.contains(event.target)) {
                const open = !wrapper.classList.contains('neutron-popover-open');
                closePopovers(wrapper); setPopover(wrapper, open);
            } else if (event.target.closest('[data-neutron-popover-close]')) setPopover(wrapper, false, true);
            else if (event.target.closest('a[href], [data-toggle="oh-modal-toggle"]')) setPopover(wrapper, false);
        } else closePopovers();
    }, true);
    document.addEventListener('keydown', event => {
        // Pointer clicks on non-focusable panel content can focus the page's
        // tabindex=-1 container before click. Only keyboard traversal dismisses
        // on focus leaving a panel; pointer dismissal is handled by outside click.
        if (event.key === 'Tab') {
            setTimeout(() => closePopovers(popoverOwner(document.activeElement)), 0);
            return;
        }
        // Select2 owns Escape while its nested option panel is open.
        if (event.key === 'Escape' && event.target.closest('.select2-container--open')) return;
        const picker = event.target.closest('.ngb-crumb-select-wrap');
        if (picker) {
            const trigger = picker.querySelector('.ngb-crumb-select-trigger');
            if (event.key === 'Escape') {
                picker.classList.remove('force-open');
                picker.closest('#ngbToolbarPanel')?.classList.remove('ngb-dropdown-open');
                trigger.setAttribute('aria-expanded', 'false'); trigger.focus();
                event.preventDefault(); event.stopPropagation(); return;
            }
            if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
                if (!picker.classList.contains('force-open')) trigger.click();
                const controls = [...picker.querySelectorAll('.ngb-crumb-option:not(:disabled)')];
                const index = controls.indexOf(document.activeElement);
                const next = event.key === 'Home' ? 0 : event.key === 'End' ? controls.length - 1 : index < 0 ? (event.key === 'ArrowDown' ? 0 : controls.length - 1) : (index + (event.key === 'ArrowDown' ? 1 : -1) + controls.length) % controls.length;
                controls[next]?.focus(); event.preventDefault(); return;
            }
        }
        const wrapper = popoverOwner(event.target) || (event.key === 'Escape' ? [...document.querySelectorAll('.neutron-popover-open')].at(-1) : null);
        if (!wrapper) return;
        const {trigger, panel} = popoverParts(wrapper);
        const isTrigger = trigger.contains(event.target);
        if (event.key === 'Escape' && wrapper.classList.contains('neutron-popover-open')) {
            setPopover(wrapper, false, true); event.preventDefault(); event.stopPropagation();
        } else if (isTrigger && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
            closePopovers(wrapper); setPopover(wrapper, true);
            const controls = [...panel.querySelectorAll('button,a[href],input,select,textarea,[tabindex="0"]')].filter(e => !e.disabled && e.getClientRects().length);
            (event.key === 'ArrowDown' ? controls[0] : controls.at(-1))?.focus(); event.preventDefault();
        } else if (isTrigger && !trigger.matches('button') && (event.key === 'Enter' || event.key === ' ')) {
            trigger.click(); event.preventDefault();
        } else if (!isTrigger && panel.matches('[role="menu"]') && ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
            const controls = [...panel.querySelectorAll('[role="menuitem"],a[href],button')].filter(e => !e.disabled && e.getClientRects().length);
            const index = controls.indexOf(document.activeElement);
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? controls.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + controls.length) % controls.length;
            controls[next]?.focus(); event.preventDefault();
        }
    }, true);
    // Native details menus retain the server's exact permitted action markup.
    // Fixed positioning keeps them outside a scrollable table's clipping box.
    function positionMenu(menu) {
        const content = menu.querySelector('.neutron-action-menu-content');
        const rect = menu.querySelector('summary').getBoundingClientRect();
        const width = content.getBoundingClientRect().width;
        const left = menu.matches('.neutron-profile-overflow') ? rect.left : rect.right - width;
        content.style.left = Math.max(12, Math.min(innerWidth - width - 12, left)) + 'px';
        const topEdge = Math.max(12, (document.querySelector('#mainHeader')?.getBoundingClientRect().bottom || 0) + 6);
        const below = Math.max(0, innerHeight - rect.bottom - 18);
        const above = Math.max(0, rect.top - topEdge - 6);
        const openBelow = content.scrollHeight <= below || below >= above;
        content.style.maxHeight = Math.max(0, openBelow ? below : above) + 'px';
        const height = content.getBoundingClientRect().height;
        content.style.top = (openBelow ? rect.bottom + 6 : Math.max(topEdge, rect.top - height - 6)) + 'px';
    }
    document.addEventListener('toggle', event => {
        const menu = event.target;
        if (!menu.matches?.('.neutron-action-menu') || !menu.open) return;
        document.querySelectorAll('.neutron-action-menu[open]').forEach(other => { if (other !== menu) other.open = false; });
        positionMenu(menu);
    }, true);
    function closeMenus() { document.querySelectorAll('.neutron-action-menu[open]').forEach(menu => { menu.open = false; }); }
    function reflectProfileTab(tab) {
        const profile = tab?.closest('.emp-profile-page');
        const label = profile?.querySelector('.neutron-profile-overflow-label');
        if (!label) return;
        label.dataset.defaultLabel ||= label.textContent;
        const secondary = Boolean(tab.closest('.neutron-profile-overflow'));
        label.textContent = secondary ? tab.dataset.tab : label.dataset.defaultLabel;
        label.closest('summary').classList.toggle('neutron-selected-overflow', secondary);
    }
    document.addEventListener('click', event => {
        reflectProfileTab(event.target.closest('button[data-tab]'));
        if (event.target.closest('[data-neutron-clear-search]')) {
            const search = document.querySelector('.navFilterForm input[name=search]');
            if (search) { search.value = ''; search.dispatchEvent(new Event('input', {bubbles: true})); search.focus(); }
        }
        if (!event.target.closest('.neutron-action-menu')) closeMenus();
        else if (event.target.closest('.neutron-action-menu-content button,.neutron-action-menu-content a')) {
            const menu = event.target.closest('.neutron-action-menu');
            menu.querySelector('summary').focus({preventScroll: true});
            closeMenus();
        }
    }, true);
    document.addEventListener('keydown', event => {
        const menu = event.target.closest('.neutron-action-menu');
        if (!menu) return;
        if (event.key === 'Escape') { menu.open = false; menu.querySelector('summary').focus(); event.preventDefault(); }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            menu.open = true; positionMenu(menu);
            const controls = [...menu.querySelectorAll('.neutron-action-menu-content button,.neutron-action-menu-content a')].filter(el => el.getClientRects().length && !el.disabled);
            if (controls.length) {
                const index = controls.indexOf(document.activeElement);
                controls[index < 0 ? (event.key === 'ArrowDown' ? 0 : controls.length - 1) : (index + (event.key === 'ArrowDown' ? 1 : -1) + controls.length) % controls.length].focus();
            }
            event.preventDefault();
        }
    });
    window.addEventListener('resize', closeMenus);
    document.addEventListener('scroll', event => { if (!event.target.closest?.('.neutron-action-menu-content')) closeMenus(); }, true);
    function updateSelection(root = document) {
        const lists = [...root.querySelectorAll('.hlv-container')];
        if (root.matches?.('.hlv-container')) lists.push(root);
        lists.forEach(list => {
            let selected = list.querySelector('.list-table-row:checked');
            const key = list.dataset.selectedInstancesKey;
            if (key) {
                try { selected ||= JSON.parse(document.getElementById(key)?.dataset.ids || '[]').length > 0; } catch (_) {}
            }
            list.classList.toggle('has-selection', Boolean(selected));
        });
    }
    document.addEventListener('change', event => {
        if (event.target.matches('.list-table-row,.bulk-list-table-row')) updateSelection();
    });
    document.addEventListener('click', event => { if (event.target.closest('.quick-bulk-action')) setTimeout(updateSelection, 0); });
    document.addEventListener('htmx:afterSettle', () => updateSelection());
    document.addEventListener('DOMContentLoaded', () => updateSelection());
    // Charts: module dashboards hard-code Tailwind colours. Remap series colours to the
    // Neutron palette as each chart is created, render bars solid, and use the UI font.
    const CHART_COLOURS = {
        '#22c55e': '#2aa9ac', '#16a34a': '#2aa9ac', '#4ade80': '#2aa9ac', '#10b981': '#2aa9ac',
        '#ef4444': '#c4322a', '#dc2626': '#c4322a', '#f87171': '#c4322a',
        '#f59e0b': '#d98e04', '#d97706': '#d98e04', '#fbbf24': '#d98e04', '#f97316': '#d98e04',
        '#3b82f6': '#617be3', '#2563eb': '#617be3', '#4f46e5': '#617be3', '#6366f1': '#617be3',
        '#a855f7': '#9cacfa', '#8b5cf6': '#9cacfa', '#ec4899': '#9cacfa',
        '#06b6d4': '#60cfd2', '#14b8a6': '#60cfd2', '#0ea5e9': '#60cfd2',
    };
    const remapColour = c => typeof c === 'string' ? (CHART_COLOURS[c.trim().toLowerCase()] || c) : c;
    function themeChartOptions(options) {
        if (!options || typeof options !== 'object') return options;
        if (Array.isArray(options.colors)) options.colors = options.colors.map(remapColour);
        if (options.markers && Array.isArray(options.markers.colors)) options.markers.colors = options.markers.colors.map(remapColour);
        if (options.fill && Array.isArray(options.fill.colors)) options.fill.colors = options.fill.colors.map(remapColour);
        const type = options.chart && options.chart.type;
        if (type === 'bar' && options.fill && options.fill.type === 'gradient') options.fill = Object.assign({}, options.fill, {type: 'solid'});
        // No entrance animation: after the loading skeleton, growing bars read as a second load.
        options.chart = Object.assign({fontFamily: 'Geist, Inter, -apple-system, sans-serif'}, options.chart || {}, {animations: {enabled: false}});
        return options;
    }
    function wrapApexCharts(Base) {
        if (!Base || Base.__neutron) return Base;
        class NeutronApexCharts extends Base {
            constructor(el, options) { super(el, themeChartOptions(options)); }
        }
        NeutronApexCharts.__neutron = true;
        return NeutronApexCharts;
    }
    (function () {
        let current = wrapApexCharts(window.ApexCharts);
        try {
            Object.defineProperty(window, 'ApexCharts', {
                configurable: true,
                get: () => current,
                set: value => { current = wrapApexCharts(value); },
            });
        } catch (_) { if (current) window.ApexCharts = current; }
    })();
    const status = document.querySelector('.neutron-status');
    const message = text => typeof gettext === 'function' ? gettext(text) : text;
    const assets = new Map();
    const loaded = new Set();
    const resolve = url => new URL(url, location.href).href;
    const present = url => Array.from(document.querySelectorAll('script[src], link[rel="stylesheet"]')).some(el => (el.src || el.href) === resolve(url));
    function loadAsset(url) {
        if (assets.has(url)) return assets.get(url);
        if (present(url)) return Promise.resolve();
        const promise = new Promise((done, fail) => {
            const element = document.createElement(url.endsWith('.css') ? 'link' : 'script');
            if (element.tagName === 'LINK') { element.rel = 'stylesheet'; element.href = url; }
            else { element.src = url; element.async = false; }
            element.onload = () => { loaded.add(url); done(); };
            element.onerror = () => { assets.delete(url); element.remove(); fail(new Error('Asset unavailable')); };
            document.head.appendChild(element);
        });
        assets.set(url, promise);
        return promise;
    }
    // Incremented by every main-region navigation; a deferred navigation only runs if it is still the latest.
    let navigationGeneration = 0;
    function assetGroup(url) {
        const path = new URL(url, location.href).pathname;
        return path.includes('/report/') ? 'reports' : path.includes('organisation-chart') ? 'organization' : (path.includes('dashboard') || path === '/my/' || path === '/ess/') ? 'dashboard' : null;
    }
    function assetsReady(group) {
        // A tag we inserted is ready only once it has loaded; tags from the page HTML already ran.
        return (window.NEUTRON_ASSETS[group] || []).every(url => loaded.has(url) || (!assets.has(url) && present(url)));
    }
    async function loadGroup(group) {
        if (group) for (const asset of window.NEUTRON_ASSETS[group]) await loadAsset(asset);
    }
    window.neutronEnsurePageAssets = async function (url) {
        const generation = ++navigationGeneration;
        await loadGroup(assetGroup(url));
        return generation === navigationGeneration;
    };
    // Any HTMX navigation into the main region (not only the sidebar) waits for the page's
    // feature assets, e.g. module dashboards that need the local ApexCharts build.
    document.addEventListener('htmx:confirm', event => {
        const {question, issueRequest, path, target} = event.detail;
        if (question || !path || !target || !(target.id === 'ohMainContent' || target.closest?.('#ohMainContent'))) return;
        // Swapping the whole region is a navigation and supersedes any deferred one;
        // smaller in-page requests (lazy widgets, filters) leave a pending navigation alone.
        const generation = target.id === 'ohMainContent' ? ++navigationGeneration : navigationGeneration;
        const group = assetGroup(path);
        if (!group || assetsReady(group)) return;
        event.preventDefault();
        loadGroup(group).then(() => {
            if (generation === navigationGeneration) issueRequest(true);
        }, () => {
            // Nothing was requested yet; the failed asset is uncached, so trying again reloads it.
            if (generation !== navigationGeneration) return;
            if (status) status.textContent = message('This page could not load. Check your connection and try again.');
            window.Swal?.fire?.({toast: true, position: 'top-end', icon: 'error', timer: 4000, showConfirmButton: false,
                title: message('This page could not load. Check your connection and try again.')});
        });
    });
    const active = new Map();
    const bar = document.querySelector('.neutron-loading');
    function finish(event) {
        const xhr = event.detail.xhr;
        const target = active.get(xhr);
        active.delete(xhr);
        if (target && !Array.from(active.values()).includes(target)) target.removeAttribute('aria-busy');
        bar?.classList.toggle('active', active.size > 0);
    }
    document.addEventListener('htmx:beforeRequest', event => {
        reflectProfileTab(event.detail.elt.closest('button[data-tab]'));
        const target = event.detail.target;
        active.set(event.detail.xhr, target);
        target?.setAttribute('aria-busy', 'true');
        const modal = target?.closest('.oh-modal');
        const swap = event.detail.elt.closest('[hx-swap]')?.getAttribute('hx-swap') || '';
        if (modal && !/^none(?:\s|$)/.test(swap) && event.detail.elt.closest('[data-toggle="oh-modal-toggle"]')) {
            modal.classList.add('oh-modal--show');
        }
        bar?.classList.add('active');
        if (status) status.textContent = '';
    });
    document.addEventListener('htmx:afterRequest', finish);
    const confirming = new WeakSet();
    document.addEventListener('htmx:confirm', event => {
        const {question, elt, issueRequest} = event.detail;
        if (!question || typeof Swal === 'undefined') return;
        event.preventDefault();
        if (confirming.has(elt)) return;
        confirming.add(elt);
        Swal.fire({
            title: message('Confirm'), text: question, icon: 'question',
            showCancelButton: true,
            confirmButtonText: message('Confirm'), cancelButtonText: message('Cancel'),
            confirmButtonColor: '#051c97', cancelButtonColor: '#494b51',
        }).then(result => {
            if (result.isConfirmed) issueRequest(true);
        }).finally(() => confirming.delete(elt));
    });
    // Plain POST forms that change what other people see confirm first. The submitter is
    // passed back so its name/value (e.g. action=archive) still reaches the server.
    const confirmedForms = new WeakSet();
    document.addEventListener('submit', event => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.dataset.neutronConfirm || typeof Swal === 'undefined') return;
        if (confirmedForms.has(form)) { confirmedForms.delete(form); return; }
        event.preventDefault();
        const submitter = event.submitter;
        Swal.fire({
            title: message('Confirm'), text: form.dataset.neutronConfirm, icon: 'question',
            showCancelButton: true,
            confirmButtonText: submitter?.textContent.trim() || message('Confirm'), cancelButtonText: message('Cancel'),
            confirmButtonColor: 'neutronDanger' in form.dataset ? '#d33' : '#051c97', cancelButtonColor: '#494b51',
        }).then(result => {
            if (!result.isConfirmed) return;
            confirmedForms.add(form);
            form.requestSubmit(submitter || undefined);
        });
    });
    for (const name of ['htmx:timeout', 'htmx:sendError', 'htmx:responseError']) {
        document.addEventListener(name, event => {
            finish(event);
            if (status) status.textContent = message('Unable to load this content. Please try again.');
        });
    }
    document.addEventListener('htmx:sendAbort', finish);

    // Observe only dialog class changes, not every table/chart DOM mutation.
    const observed = new WeakSet();
    const returnFocus = new WeakMap();
    function focusDialog(modal) {
        const focus = modal.querySelector('[autofocus], input:not([type=hidden]):not([disabled]):not(.select2-hidden-accessible), textarea, select:not(.select2-hidden-accessible), button, [href]');
        if (focus && focus.getClientRects().length) focus.focus({preventScroll: true});
        else { modal.tabIndex = -1; modal.focus({preventScroll: true}); }
    }
    const observer = new MutationObserver(records => {
        for (const {target: modal} of records) {
            const open = modal.classList.contains('oh-modal--show');
            modal.setAttribute('aria-hidden', String(!open));
            if (open) {
                if (!returnFocus.has(modal)) returnFocus.set(modal, document.activeElement);
                modal.setAttribute('aria-modal', 'true');
                focusDialog(modal);
            } else {
                modal.removeAttribute('aria-modal');
                const trigger = returnFocus.get(modal);
                if (trigger?.isConnected) trigger.focus({preventScroll: true});
                returnFocus.delete(modal);
            }
        }
    });
    function observe(root) {
        root.querySelectorAll('a[hx-get]:not([href]), li[hx-get]').forEach(control => {
            control.setAttribute('role', 'button');
            control.tabIndex = 0;
        });
        const dialogs = [...root.querySelectorAll('.oh-modal')];
        if (root.matches?.('.oh-modal')) dialogs.push(root);
        dialogs.forEach(modal => {
            if (observed.has(modal)) return;
            observed.add(modal);
            observer.observe(modal, {attributes: true, attributeFilter: ['class']});
            modal.setAttribute('aria-hidden', String(!modal.classList.contains('oh-modal--show')));
        });
    }
    document.addEventListener('click', event => {
        const control = event.target.closest('[data-toggle="oh-modal-toggle"]');
        const action = event.target.closest('a,button,input,select,textarea,summary,details,[role="button"],[hx-get],[hx-post],[hx-delete],[hx-put]');
        if (action && action !== control) return;
        const target = control?.getAttribute('data-target');
        const modal = target ? document.querySelector(target) : null;
        if (modal) {
            if (!modal.classList.contains('oh-modal--show')) returnFocus.set(modal, control);
            // Row actions stop bubbling; capture must open their dialogs too.
            if (!event.target.closest('[hx-confirm]')) modal.classList.add('oh-modal--show');
        }
    }, true);
    observe(document);
    document.addEventListener('htmx:afterSwap', event => {
        observe(event.detail.target);
        const modal = event.detail.target.closest('.oh-modal--show');
        if (modal) focusDialog(modal);
    });
    document.addEventListener('keydown', event => {
        const control = event.target.closest('a[role="button"]:not([href]), li[role="button"]');
        if (control && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault();
            control.click();
            return;
        }
        if (typeof Swal !== 'undefined' && Swal.isVisible()) return;
        const modals = Array.from(document.querySelectorAll('.oh-modal--show')).filter(el => el.getClientRects().length);
        const modal = modals.at(-1);
        if (!modal) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            modal.classList.remove('oh-modal--show');
        } else if (event.key === 'Tab') {
            const items = Array.from(modal.querySelectorAll('a[href],button,input,select,textarea,[tabindex]')).filter(el => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length);
            const first = items[0], last = items.at(-1);
            if (!first) { event.preventDefault(); return; }
            if (event.shiftKey && (document.activeElement === first || !modal.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && (document.activeElement === last || !modal.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
        }
    });
})();
