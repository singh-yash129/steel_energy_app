/* Predictor page: forms -> API -> animated result */
(function () {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const state = { tab: 'forecast', forecast: null, conditions: null, batch: null, example: null };
  let chart = null, bchart = null, batchCsv = '';

  /* ---------- defaults ---------- */
  function localInput(d) {
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  }
  const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1); tomorrow.setHours(14, 0, 0, 0);
  $('#f-target').value = localInput(tomorrow);
  $('#c-target').value = localInput(tomorrow);

  /* ---------- tabs ---------- */
  $$('.tab').forEach(t => t.addEventListener('click', () => switchTab(t.dataset.tab)));
  function switchTab(name) {
    state.tab = name;
    $$('.tab').forEach(t => { const on = t.dataset.tab === name; t.classList.toggle('active', on); t.setAttribute('aria-selected', on); });
    ['forecast', 'conditions', 'batch'].forEach(k => { $('#form-' + k).hidden = k !== name; });
    hideAlert(); showResult();
  }
  function showResult() {
    const has = state[state.tab];
    $('#empty').hidden = !!has;
    $('#result').hidden = !(has && state.tab !== 'batch');
    $('#batch-result').hidden = !(has && state.tab === 'batch');
    if (has && state.tab === 'forecast') renderForecast(has);
    if (has && state.tab === 'conditions') renderConditions(has);
    if (has && state.tab === 'batch') renderBatch(has);
  }

  /* ---------- helpers ---------- */
  function showAlert(msg) { const a = $('#alert'); a.textContent = msg; a.hidden = false; }
  function hideAlert() { $('#alert').hidden = true; }
  function setBusy(form, busy, label) {
    const b = $('button[type=submit]', form);
    if (!b.dataset.label) b.dataset.label = b.innerHTML;
    b.disabled = busy; b.innerHTML = busy ? (label || 'Working…') : b.dataset.label;
  }
  function formData(form) {
    const o = {}; new FormData(form).forEach((v, k) => { o[k] = v; }); return o;
  }
  function validate(form) {
    let ok = true;
    $$('input', form).forEach(i => i.classList.remove('invalid'));
    $$('input[required]', form).forEach(i => {
      if (i.closest('[hidden]')) return;
      if (i.value === '' || (i.type === 'number' && (isNaN(+i.value) || +i.value < +i.min || +i.value > +i.max))) { i.classList.add('invalid'); ok = false; }
    });
    if (!ok) showAlert('Please fix the highlighted fields (all numbers must be within the allowed range).');
    return ok;
  }
  async function post(url, body) {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({ error: 'Unexpected server response.' }));
    if (!r.ok) throw new Error(j.error || 'Something went wrong.');
    return j;
  }
  function countUp(el, to, ms = 700) {
    const t0 = performance.now();
    (function step(t) {
      const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3);
      el.textContent = fmt(to * e); if (k < 1) requestAnimationFrame(step);
    })(t0);
  }
  $$('input', document).forEach(i => i.addEventListener('input', () => { i.classList.remove('invalid'); if (!i.closest('#form-batch') && i.type !== 'radio' && i.name !== 'target' && i.name !== 'tariff') state.example = null; }));

  /* ---------- forecast form ---------- */
  const fForm = $('#form-forecast');
  function horizonChanged() {
    const q = fForm.horizon.value === 'Next 15 minutes';
    $('#lag15-wrap').hidden = !q; $('#f-lag15').required = q;
    state.forecast = null; showResult();
  }
  $$('input[name=horizon]', fForm).forEach(r => r.addEventListener('change', horizonChanged));

  $('#btn-typical').addEventListener('click', async () => {
    hideAlert();
    try {
      const r = await fetch('/api/typical?target=' + encodeURIComponent($('#f-target').value));
      const j = await r.json(); if (!r.ok) throw new Error(j.error);
      $('#f-lag24').value = j.lag_24h; $('#f-lag48').value = j.lag_48h; $('#f-lag7').value = j.lag_7d;
      $('#f-prev').value = j.prev_day_mean; if (!$('#lag15-wrap').hidden) $('#f-lag15').value = j.lag_15;
      $$('input', fForm).forEach(i => i.classList.remove('invalid'));
    } catch (e) { showAlert(e.message); }
  });

  async function loadExample() { const r = await fetch('/api/samples'); return r.json(); }

  $('#btn-example-f').addEventListener('click', async () => {
    hideAlert();
    try {
      const s = await loadExample();
      $('#f-target').value = s.timestamp; $('#f-lag24').value = s.lag_24h; $('#f-lag48').value = s.lag_48h;
      $('#f-lag7').value = s.lag_7d; $('#f-prev').value = s.prev_day_mean; $('#f-lag15').value = s.lag_15;
      state.example = s.actual_kwh;
      $$('input', fForm).forEach(i => i.classList.remove('invalid'));
      fForm.requestSubmit();
    } catch (e) { showAlert('Could not load an example.'); }
  });

  fForm.addEventListener('submit', async (ev) => {
    ev.preventDefault(); hideAlert();
    if (!validate(fForm)) return;
    setBusy(fForm, true, 'Predicting…');
    try {
      const j = await post('/api/predict/forecast', formData(fForm));
      j._actual = state.example; state.forecast = j; showResult();
      if (window.innerWidth < 960) $('.result-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) { showAlert(e.message); } finally { setBusy(fForm, false); }
  });

  /* ---------- conditions form ---------- */
  const cForm = $('#form-conditions');
  $('#btn-example-c').addEventListener('click', async () => {
    hideAlert();
    try {
      const s = await loadExample();
      $('#c-target').value = s.timestamp; $('#c-lagq').value = s.lag_react; $('#c-leadq').value = s.lead_react;
      $('#c-lagpf').value = s.lag_pf; $('#c-leadpf').value = s.lead_pf; state.example = s.actual_kwh;
      cForm._load = s.load_type;
      $$('input', cForm).forEach(i => i.classList.remove('invalid'));
      cForm.requestSubmit();
    } catch (e) { showAlert('Could not load an example.'); }
  });
  cForm.addEventListener('submit', async (ev) => {
    ev.preventDefault(); hideAlert();
    if (!validate(cForm)) return;
    setBusy(cForm, true, 'Estimating…');
    try {
      const j = await post('/api/predict/conditions', formData(cForm));
      j._actual = state.example; j._actualLoad = cForm._load || null; state.conditions = j; showResult();
      if (window.innerWidth < 960) $('.result-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) { showAlert(e.message); } finally { setBusy(cForm, false); cForm._load = null; }
  });

  /* ---------- shared result pieces ---------- */
  function paintCommon(j, kicker, unitNote) {
    $('#r-kicker').textContent = kicker;
    $('#r-when').textContent = j.reading_time + ' · ' + (j.day_type === 'weekday' ? 'Weekday' : 'Weekend');
    const pill = $('#r-status'); pill.textContent = j.status.label; pill.className = 'pill ' + j.status.key;
    countUp($('#r-kwh'), j.predicted_kwh);
    $('.big small i').textContent = unitNote;
  }
  function tile(label, value, unit) { return `<div class="tile"><small>${label}</small><b>${value}</b><span>${unit || ''}</span></div>`; }
  function paintMeter(j) {
    const t = j.typical, hi = j.high_kwh ?? j.predicted_kwh;
    const max = Math.max(t.p90 * 1.35, hi * 1.15, j.predicted_kwh * 1.2, 10);
    const pc = (v) => Math.min(100, Math.max(0, 100 * v / max));
    const set = (id, l, r) => { const e = $(id); e.style.left = pc(l) + '%'; e.style.width = Math.max(0.8, pc(r) - pc(l)) + '%'; };
    set('#m-wide', t.p10, t.p90); set('#m-core', t.p25, t.p75);
    const w = $('#m-whisk');
    if (j.low_kwh != null) { w.hidden = false; w.style.left = pc(j.low_kwh) + '%'; w.style.width = Math.max(0.8, pc(j.high_kwh) - pc(j.low_kwh)) + '%'; } else { w.hidden = true; }
    const m = $('#m-mark'); m.style.left = '0%'; requestAnimationFrame(() => requestAnimationFrame(() => { m.style.left = pc(j.predicted_kwh) + '%'; }));
  }
  function paintChart(c) {
    if (chart) chart.destroy();
    const pt = c.labels.map((_, i) => i === c.slot ? c.value : null);
    const accent = css('--accent'), cyan = css('--cyan'), good = css('--good');
    chart = new Chart($('#r-chart'), {
      type: 'line',
      data: { labels: c.labels, datasets: [
        { label: 'p10', order: 1, data: c.p10, borderWidth: 0, pointRadius: 0, fill: false },
        { label: 'Usual range (10–90%)', order: 1, data: c.p90, borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: alpha(cyan, .16) },
        { label: 'p25', order: 1, data: c.p25, borderWidth: 0, pointRadius: 0, fill: false },
        { label: 'Typical (middle 50%)', order: 1, data: c.p75, borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: alpha(good, .30) },
        { label: 'Average ' + c.kind, order: 1, data: c.mean, borderColor: css('--text'), borderWidth: 1.6, pointRadius: 0, tension: .25 },
        { label: 'Prediction', data: pt, order: 0, showLine: false, pointRadius: 8, pointHoverRadius: 10, pointBackgroundColor: accent, pointBorderColor: css('--card-solid'), pointBorderWidth: 3 },
      ] },
      options: {
        responsive: true, interaction: { mode: 'index', intersect: false },
        plugins: { legend: { labels: { filter: (i) => !['p10', 'p25'].includes(i.text) } },
                   tooltip: { filter: (i) => !['p10', 'p25'].includes(i.dataset.label) } },
        scales: { x: { ticks: { maxTicksLimit: 9 }, grid: { display: false } },
                  y: { title: { display: true, text: 'kWh per 15 min' }, beginAtZero: true } },
      },
    });
  }

  /* ---------- forecast result ---------- */
  function renderForecast(j) {
    $('#result').hidden = false;
    paintCommon(j, j.horizon === 'Next day' ? 'Predicted usage · same time tomorrow' : 'Predicted usage · next 15 minutes', 'in this 15-minute reading');
    $('#r-range').innerHTML = `Likely between <b>${fmt(j.low_kwh)}</b> and <b>${fmt(j.high_kwh)} kWh</b> <span class="muted">(80% of past errors fell in this band)</span>`;
    $('#meter').hidden = false; paintMeter(j);
    $('#tiles').innerHTML = tile('Average demand', fmt(j.avg_demand_kw, 1), 'kW') + tile('CO₂', fmt(j.co2.kg), 'kg') +
      tile('Typical now', fmt(j.typical.mean), 'kWh') + (j.cost != null ? tile('Est. cost', fmt(j.cost), '') : '');
    const d = (label, v) => v == null ? '' : `<span class="delta ${v > 0 ? 'up' : 'down'}">${v > 0 ? '▲' : '▼'} ${Math.abs(v).toFixed(0)}% ${label}</span>`;
    let cmp = d('vs typical for this time', j.vs_typical_pct) + d('vs yesterday', j.vs_yesterday_pct) + d('vs last week', j.vs_last_week_pct);
    if (j._actual != null) cmp += `<span class="delta">Real value in the data: <b>${fmt(j._actual)} kWh</b> (off by ${fmt(Math.abs(j._actual - j.predicted_kwh))})</span>`;
    $('#r-compare').innerHTML = cmp;
    $('#r-tips').innerHTML = j.tips.map(t => `<li>${t}</li>`).join('');
    $('#r-extra').hidden = true;
    paintChart(j.chart);
    $('#r-model').textContent = `${j.model.name} · average error ${j.model.test_mae} kWh on unseen Oct–Dec data (best simple guess "${j.model.baseline}": ${j.model.baseline_mae} kWh).`;
  }

  /* ---------- conditions result ---------- */
  function renderConditions(j) {
    $('#result').hidden = false;
    paintCommon(j, 'Estimated usage · from meter readings', 'in this 15-minute reading');
    $('#r-range').innerHTML = `Detected load type: <b>${j.load_type.replace('_', ' ')}</b> · average demand <b>${fmt(j.avg_demand_kw, 1)} kW</b>`;
    $('#meter').hidden = false; paintMeter({ ...j, low_kwh: null, high_kwh: null });
    $('#tiles').innerHTML = tile('CO₂', fmt(j.co2.kg), 'kg') + tile('Typical now', fmt(j.typical.mean), 'kWh') +
      tile('Lagging PF', fmt(j.power_factor.lagging_pf, 1), '%') + (j.cost != null ? tile('Est. cost', fmt(j.cost), '') : '');
    let cmp = '';
    if (j._actual != null) cmp += `<span class="delta">Real value in the data: <b>${fmt(j._actual)} kWh</b></span>`;
    if (j._actualLoad) cmp += `<span class="delta">Real load type: <b>${j._actualLoad.replace('_', ' ')}</b></span>`;
    if (j.physics_kwh != null) cmp += `<span class="delta">Physics cross-check: <b>${fmt(j.physics_kwh)} kWh</b></span>`;
    $('#r-compare').innerHTML = cmp;
    $('#r-tips').innerHTML = '';
    const names = { Light_Load: 'Light', Medium_Load: 'Medium', Maximum_Load: 'Maximum' };
    const top = Object.keys(j.load_probs).reduce((a, b) => j.load_probs[a] > j.load_probs[b] ? a : b);
    const probs = ['Light_Load', 'Medium_Load', 'Maximum_Load'].filter(k => k in j.load_probs).map(k => [k, j.load_probs[k]]).map(([k, v]) =>
      `<div class="prow ${k === top ? 'top' : ''}"><span>${names[k]}</span><div class="pbar"><i style="width:0" data-w="${(v * 100).toFixed(0)}"></i></div><span>${(v * 100).toFixed(0)}%</span></div>`).join('');
    const pf = j.power_factor;
    const comp = pf.compensation_kvar != null ? `<p>To reach ${pf.target}% you would need roughly <b>${fmt(pf.compensation_kvar, 0)} kVAr</b> of capacitor compensation at this load.</p>` : '';
    const ex = $('#r-extra'); ex.hidden = false;
    ex.innerHTML = `<div class="probs"><h4>Load-type confidence</h4>${probs}</div>
      <div class="pfbox ${pf.state}"><h4>Power-factor health</h4><p>${pf.text}</p>${comp}</div>`;
    requestAnimationFrame(() => requestAnimationFrame(() => $$('.pbar i', ex).forEach(e => { e.style.width = e.dataset.w + '%'; })));
    paintChart(j.chart);
    $('#r-model').textContent = `Random Forest · average error ${j.model.regressor_mae} kWh (R² ${j.model.regressor_r2}) · load-type accuracy ${(j.model.classifier_accuracy * 100).toFixed(0)}% on unseen Oct–Dec data.`;
  }

  /* ---------- batch ---------- */
  const bForm = $('#form-batch'), fileInput = $('#b-file'), drop = $('#drop');
  function showFile() { const f = fileInput.files[0]; $('#drop-title').textContent = f ? f.name : 'Drop a CSV here or click to browse'; $('#drop-sub').textContent = f ? (f.size / 1024).toFixed(1) + ' KB · ready' : 'Max 2 MB'; }
  fileInput.addEventListener('change', showFile);
  ['dragenter', 'dragover'].forEach(e => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(e => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', (ev) => { if (ev.dataTransfer.files.length) { fileInput.files = ev.dataTransfer.files; showFile(); } });
  bForm.addEventListener('submit', async (ev) => {
    ev.preventDefault(); hideAlert();
    if (!fileInput.files[0]) { showAlert('Please choose a CSV file first.'); return; }
    setBusy(bForm, true, 'Predicting…');
    try {
      const fd = new FormData(); fd.append('file', fileInput.files[0]);
      const r = await fetch('/api/batch', { method: 'POST', body: fd });
      const j = await r.json().catch(() => ({ error: 'Unexpected server response.' }));
      if (!r.ok) throw new Error(j.error);
      state.batch = j; batchCsv = j.csv; showResult();
    } catch (e) { showAlert(e.message); } finally { setBusy(bForm, false); }
  });
  $('#b-download').addEventListener('click', () => {
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([batchCsv], { type: 'text/csv' }));
    a.download = 'predictions.csv'; a.click(); URL.revokeObjectURL(a.href);
  });
  function renderBatch(j) {
    const s = j.summary;
    $('#b-when').textContent = `${fmt0(s.rows)} readings predicted`;
    const lc = Object.entries(s.load_counts).map(([k, v]) => `${k.replace('_Load', '')}: ${v}`).join(' · ');
    $('#b-tiles').innerHTML = tile('Total energy', fmt0(s.total_kwh), 'kWh') + tile('Peak reading', fmt(s.peak_kwh), 'kWh') + tile('CO₂', fmt0(s.total_co2_kg), 'kg') + `<div class="tile"><small>Load types</small><span style="margin:0">${lc}</span></div>`;
    if (bchart) bchart.destroy();
    const acc = css('--accent');
    bchart = new Chart($('#b-chart'), { type: 'line',
      data: { labels: j.series.labels, datasets: [{ label: 'Predicted kWh', data: j.series.kwh, borderColor: acc, backgroundColor: alpha(acc, .15), fill: true, pointRadius: 0, borderWidth: 2, tension: .25 }] },
      options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { ticks: { maxTicksLimit: 6 }, grid: { display: false } }, y: { beginAtZero: true, title: { display: true, text: 'kWh per 15 min' } } } } });
    const cols = ['timestamp', 'predicted_kwh', 'avg_demand_kw', 'co2_kg', 'predicted_load_type'];
    $('#b-table').innerHTML = '<thead><tr>' + cols.map(c => `<th>${c.replace(/_/g, ' ')}</th>`).join('') + '</tr></thead><tbody>' +
      j.preview.map(r => '<tr>' + cols.map(c => `<td>${r[c]}</td>`).join('') + '</tr>').join('') + '</tbody>';
  }

  window.addEventListener('themechange', () => { applyChartDefaults(); showResult(); });
})();
