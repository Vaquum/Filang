// Both the visual builder and the formal editor use the same keyboard interaction.
import { h, mount, nextId } from './ui/dom.js';
import { applyCompletion, queryCompletions } from './query-completions.js';

export function optionList(input, { label, onPick, dismiss, highlightFirst = true }) {
  const id = nextId('choices');
  const list = h('div', { class: 'option-list', id, role: 'listbox', 'aria-label': label });
  let options = [],
    active = -1;
  const abort = new AbortController();
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', id);
  function highlight(i, scroll) {
    active = i;
    Array.from(list.children).forEach((e, index) => e.setAttribute('aria-selected', String(index === i)));
    const selected = list.children[i];
    if (selected && options.length) {
      input.setAttribute('aria-activedescendant', selected.id);
      if (scroll) selected.scrollIntoView({ block: 'nearest' });
    } else input.removeAttribute('aria-activedescendant');
  }
  function show(items, message = 'No matching choices. Try another name.') {
    options = items;
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    mount(
      list,
      items.map((item, i) =>
        h(
          'div',
          {
            class: 'choice',
            id: id + '-' + i,
            role: 'option',
            onmousedown: (e) => e.preventDefault(),
            onclick: () => onPick(item),
          },
          h(
            'div',
            { class: 'choice-top' },
            item.sample,
            h('span', { class: 'choice-title' }, item.label),
            item.count !== undefined &&
              h(
                'span',
                { class: 'choice-count' },
                item.count.toLocaleString('en-US') + (item.count === 1 ? ' match' : ' matches'),
              ),
          ),
          item.detail && h('small', null, item.detail),
        ),
      ),
    );
    if (!items.length) mount(list, h('p', { class: 'no-choice' }, message));
    highlight(items.length && highlightFirst ? 0 : -1, false);
    list.scrollTop = 0;
  }
  function hide() {
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    active = -1;
  }
  input.addEventListener(
    'keydown',
    (e) => {
      if (list.hidden || e.isComposing || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 'Escape') {
        hide();
        if (dismiss) dismiss();
      } else if (options.length && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
        highlight(
          active < 0
            ? e.key === 'ArrowDown'
              ? 0
              : options.length - 1
            : (active + (e.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length,
          true,
        );
      } else if (
        options.length &&
        active >= 0 &&
        (e.key === 'Enter' || (e.key === 'Tab' && !e.shiftKey && !highlightFirst))
      ) {
        onPick(options[active]);
      } else return;
      e.preventDefault();
      e.stopPropagation();
    },
    { signal: abort.signal },
  );
  hide();
  return { list, show, hide, destroy: () => abort.abort() };
}

export function setupFormalMenu(input, host, env) {
  const menu = optionList(input, {
    label: 'Query completions',
    highlightFirst: false,
    onPick: (item) => {
      const next = applyCompletion(input.value, item);
      input.value = next.text;
      input.focus();
      input.setSelectionRange(next.caret, next.caret);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      refresh();
    },
  });
  const helper = h(
    'button',
    {
      type: 'button',
      class: 'text-btn',
      onclick: () => {
        input.focus();
        refresh(true);
      },
    },
    'Show completions',
  );
  const context = h('small', { class: 'menu-context' });
  mount(host, h('div', { class: 'completion-tools' }, helper, context), menu.list);
  function refresh(force) {
    const result = queryCompletions(input.value, input.selectionStart, env, input.selectionEnd);
    if (!force && !result.items.length) {
      menu.hide();
      context.textContent = '';
      return;
    }
    context.textContent = result.context;
    menu.show(result.items, 'No completion at this position.');
  }
  input.addEventListener('input', () => refresh());
  input.addEventListener('click', () => refresh());
  input.addEventListener('keydown', (e) => {
    if (((e.ctrlKey || e.metaKey) && e.code === 'Space') || (menu.list.hidden && e.key === 'ArrowDown')) {
      e.preventDefault();
      refresh(true);
    }
  });
  input.addEventListener('keyup', (e) => {
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) refresh();
  });
  host.parentElement.addEventListener('focusout', (e) => {
    if (!host.contains(e.relatedTarget) && e.relatedTarget !== input) {
      menu.hide();
      context.textContent = '';
    }
  });
  return () => {
    menu.hide();
    context.textContent = '';
  };
}
