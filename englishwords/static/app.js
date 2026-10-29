document.documentElement.classList.add('js');
document.querySelectorAll('[data-print-management]').forEach(form => {
  const update = () => {
    const items = [...form.querySelectorAll('input[name="job_id"]')];
    const count = items.filter(input => input.checked).length;
    form.querySelector('[data-print-count]').textContent = count ? `已选 ${count} 份` : '请选择资料';
    form.querySelector('[data-print-action]').disabled = count === 0;
    const all = form.querySelector('[data-select-all]');
    all.checked = count > 0 && count === items.length;
    all.indeterminate = count > 0 && count < items.length;
  };
  form.addEventListener('change', update);
  window.addEventListener('pageshow', update);
  update();
});
document.querySelectorAll('[data-select-all]').forEach(toggle => {
  toggle.addEventListener('change', () => {
    const form = toggle.closest('form');
    form.querySelectorAll(`input[type="checkbox"][name="${toggle.dataset.selectAll}"]`).forEach(input => { input.checked = toggle.checked; });
    form.dispatchEvent(new Event('change', { bubbles: true }));
  });
});
document.querySelectorAll('[data-book-fill]').forEach(select => {
  select.addEventListener('change', () => {
    const raw = select.selectedOptions[0]?.dataset.fields;
    if (!raw) return;
    Object.entries(JSON.parse(raw)).forEach(([key,value]) => {
      const input = document.querySelector(`[name="${key}_${select.dataset.bookFill}"]`);
      if (input) input.value = value;
    });
  });
});

document.querySelectorAll('[data-print-picker]').forEach(form => {
  const update = () => {
    let total = 0, sections = 0;
    form.querySelectorAll('[data-book-picker]').forEach(book => {
      const inputs = [...book.querySelectorAll('input[name="section_id"]')];
      const selected = inputs.filter(input => input.checked);
      const toggle = book.querySelector('[data-book-toggle]');
      toggle.checked = inputs.length > 0 && selected.length === inputs.length;
      toggle.indeterminate = selected.length > 0 && selected.length < inputs.length;
      book.querySelector('[data-book-count]').textContent = selected.length ? `已选 ${selected.length} / ${inputs.length} 个单元` : '未选择';
      total += selected.reduce((sum, input) => sum + Number(input.dataset.count), 0);
      sections += selected.length;
    });
    const limited = form.querySelector('[name="initial"]').value;
    form.querySelector('[data-picker-summary]').textContent = sections ? `已选 ${sections} 个单元 · ${total} 条${limited ? '（首字母筛选前）' : ''}` : '请选择单元';
    form.querySelector('[data-picker-submit]').disabled = sections === 0;
  };
  form.querySelectorAll('[data-book-toggle]').forEach(toggle => {
    toggle.addEventListener('change', () => {
      toggle.closest('[data-book-picker]').querySelectorAll('input[name="section_id"]').forEach(input => { input.checked = toggle.checked; });
    });
  });
  form.querySelector('[data-picker-clear]').addEventListener('click', () => {
    form.querySelectorAll('input[name="section_id"]').forEach(input => { input.checked = false; });
    update();
  });
  form.addEventListener('change', update);
  window.addEventListener('pageshow', update);
  update();
});

document.querySelectorAll('[data-print-options]').forEach(form => {
  const update = () => {
    form.querySelector('[data-shuffle-seed]').hidden = form.querySelector('[data-print-order]').value !== 'shuffle';
    const pageBreak = form.querySelector('[data-break-sections]');
    pageBreak.disabled = form.querySelector('[name="grouping"]').value === 'none';
    if (pageBreak.disabled) pageBreak.checked = false;
  };
  form.addEventListener('change', update);
  form.addEventListener('submit', () => {
    const button = form.querySelector('button[type="submit"], .print-submit button');
    button.disabled = true;
    button.textContent = '正在生成…';
  });
  window.addEventListener('pageshow', () => {
    const button = form.querySelector('.print-submit button');
    if (button.textContent === '正在生成…') { button.disabled = false; button.textContent = '生成三张表 →'; }
  });
  update();
});

document.querySelectorAll('[data-item-selection]').forEach(form => {
  const update = () => {
    const selected = form.querySelectorAll('input[name="item_id"]:checked').length;
    form.querySelector('[data-print-selected]').disabled = selected === 0;
    form.querySelector('[data-selected-count]').textContent = selected ? `已选 ${selected} 条` : '勾选词条后可打印或批量整理';
    const toggle = form.querySelector('[data-select-all]');
    const count = form.querySelectorAll('input[name="item_id"]').length;
    toggle.checked = count > 0 && selected === count;
    toggle.indeterminate = selected > 0 && selected < count;
  };
  form.addEventListener('change', update);
  window.addEventListener('pageshow', update);
  update();
});
