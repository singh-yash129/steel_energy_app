/* Insights dashboard */
(function () {
  let D = null, charts = [];
  const $ = (s) => document.querySelector(s);
  const mk = (id, cfg) => { const c = new Chart($(id), cfg); charts.push(c); return c; };

  fetch('/api/insights').then(r => r.json()).then(d => { D = d; draw(); });
  window.addEventListener('themechange', () => { applyChartDefaults(); if (D) draw(); });

  function draw() {
    charts.forEach(c => c.destroy()); charts = [];
    const accent = css('--accent'), cyan = css('--cyan'), good = css('--good'), warn = css('--warn'), violet = '#8b5cf6';
    const K = D.kpis;

    $('#kpis').innerHTML = [
      ['Total energy', fmt0(K.total_kwh / 1000) + ' MWh', `${fmt(K.avg_kwh, 1)} kWh average per reading`, accent],
      ['CO₂ emitted', fmt0(K.co2_tonnes) + ' t', 'dataset CO₂ column, 2018', cyan],
      ['Peak demand', fmt(K.peak_kwh, 1) + ' kWh', K.peak_when, '#fb7185'],
      ['Load factor', fmt(K.load_factor, 1) + '%', 'average ÷ peak demand', good],
      ['Weekday vs weekend', fmt(K.weekday_vs_weekend, 1) + '×', 'more energy per day on weekdays', warn],
      ['Poor power factor', fmt(K.pf_below_90_pct, 0) + '%', 'of readings below 90% lagging', violet],
    ].map(([a, b, c, col]) => `<div class="kpi" style="--k:${col}"><small>${a}</small><b>${b}</b><span>${c}</span></div>`).join('');

    // hourly
    mk('#c-hourly', { type: 'line', data: { labels: D.hourly.labels.map(h => String(h).padStart(2, '0') + ':00'), datasets: [
      { label: 'Weekdays', data: D.hourly.weekday, borderColor: accent, backgroundColor: alpha(accent, .15), fill: true, tension: .35, borderWidth: 2.5, pointRadius: 0 },
      { label: 'Weekends', data: D.hourly.weekend, borderColor: cyan, backgroundColor: alpha(cyan, .12), fill: true, tension: .35, borderWidth: 2.5, pointRadius: 0 } ] },
      options: { interaction: { mode: 'index', intersect: false }, scales: { x: { ticks: { maxTicksLimit: 12 }, grid: { display: false } }, y: { beginAtZero: true, title: { display: true, text: 'kWh / 15 min' } } } } });

    // load types
    mk('#c-load', { type: 'bar', data: { labels: D.load.labels, datasets: [
      { label: 'Share of time (%)', data: D.load.time_pct, backgroundColor: alpha(cyan, .85), borderRadius: 8 },
      { label: 'Share of energy (%)', data: D.load.energy_pct, backgroundColor: alpha(accent, .9), borderRadius: 8 } ] },
      options: { scales: { x: { grid: { display: false } }, y: { beginAtZero: true, max: 100 } } } });

    // heatmap
    const vals = D.heatmap.values.flat(), lo = Math.min(...vals), hi = Math.max(...vals);
    const col = (v) => { const t = (v - lo) / (hi - lo); return `color-mix(in srgb, ${accent} ${Math.round(t * 100)}%, ${alpha(cyan, 0.10)})`; };
    let h = '<span></span>' + D.heatmap.cols.map(c => `<span class="hl">${c % 3 === 0 ? c : ''}</span>`).join('');
    D.heatmap.rows.forEach((r, i) => {
      h += `<span class="lab">${r}</span>` + D.heatmap.values[i].map((v, j) => `<span class="cell" style="background:${col(v)}" title="${r} ${String(j).padStart(2, '0')}:00 — ${v} kWh"></span>`).join('');
    });
    $('#heat').innerHTML = h;

    // day of week
    mk('#c-dow', { type: 'bar', data: { labels: D.dow.labels, datasets: [{ data: D.dow.values,
      backgroundColor: D.dow.labels.map((_, i) => i < 5 ? alpha(accent, .9) : alpha(cyan, .9)), borderRadius: 8 }] },
      options: { plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { beginAtZero: true, title: { display: true, text: 'kWh / day' } } } } });

    // monthly
    mk('#c-month', { data: { labels: D.month.labels, datasets: [
      { type: 'bar', label: 'Avg daily kWh', data: D.month.kwh_per_day, backgroundColor: alpha(accent, .85), borderRadius: 8, yAxisID: 'y' },
      { type: 'line', label: 'CO₂ (tonnes / month)', data: D.month.co2_tonnes, borderColor: cyan, backgroundColor: cyan, borderWidth: 2.5, tension: .3, pointRadius: 4, yAxisID: 'y2' } ] },
      options: { scales: { x: { grid: { display: false } }, y: { beginAtZero: true, title: { display: true, text: 'kWh / day' } },
                           y2: { position: 'right', beginAtZero: true, grid: { display: false }, title: { display: true, text: 'tonnes CO₂' } } } } });

    // load duration
    mk('#c-ldc', { type: 'line', data: { datasets: [{ label: 'kWh', data: D.load_duration.pct.map((p, i) => ({ x: p, y: D.load_duration.kwh[i] })), borderColor: violet, backgroundColor: alpha(violet, .18), fill: true, pointRadius: 0, borderWidth: 2.5, tension: .2 }] },
      options: { plugins: { legend: { display: false } }, scales: { x: { type: 'linear', min: 0, max: 100, title: { display: true, text: '% of the year demand is at least this high' }, ticks: { stepSize: 25 }, grid: { display: false } }, y: { beginAtZero: true, title: { display: true, text: 'kWh / 15 min' } } } } });

    // power factor
    mk('#c-pf', { type: 'line', data: { labels: D.hourly.labels.map(h => String(h).padStart(2, '0') + ':00'), datasets: [
      { label: 'Lagging PF (%)', data: D.pf_hour.lagging, borderColor: accent, borderWidth: 2.5, tension: .3, pointRadius: 0 },
      { label: 'Leading PF (%)', data: D.pf_hour.leading, borderColor: cyan, borderWidth: 2.5, tension: .3, pointRadius: 0 },
      { label: '90% target', data: D.hourly.labels.map(() => 90), borderColor: good, borderDash: [6, 6], borderWidth: 1.5, pointRadius: 0 } ] },
      options: { interaction: { mode: 'index', intersect: false }, scales: { x: { ticks: { maxTicksLimit: 12 }, grid: { display: false } }, y: { suggestedMin: Math.floor(Math.min(...D.pf_hour.leading, ...D.pf_hour.lagging) / 10) * 10, max: 105, title: { display: true, text: 'Power factor (%)' } } } } });

    // models
    const nd = D.models['Next day'], q = D.models['Next 15 minutes'];
    const best = (m) => m.final_scores[m.chosen_model].MAE, base = (m) => m.final_scores[m.best_baseline].MAE;
    mk('#c-models', { type: 'bar', data: { labels: ['Next day', 'Next 15 min'], datasets: [
      { label: 'Best simple guess', data: [base(nd), base(q)], backgroundColor: alpha(css('--faint'), .8), borderRadius: 8 },
      { label: 'Chosen model', data: [best(nd), best(q)], backgroundColor: alpha(accent, .9), borderRadius: 8 } ] },
      options: { scales: { x: { grid: { display: false } }, y: { beginAtZero: true, title: { display: true, text: 'MAE (kWh)' } } } } });

    // takeaways
    const wk = D.hourly.weekday, peakH = wk.indexOf(Math.max(...wk)), lowH = wk.indexOf(Math.min(...wk));
    const light = D.load;
    $('#takeaways').innerHTML = [
      `<b>Weekday rhythm:</b> usage is lowest around ${String(lowH).padStart(2, '0')}:00, ramps up through the morning and peaks around ${String(peakH).padStart(2, '0')}:00 at roughly ${fmt(Math.max(...wk), 0)} kWh per reading.`,
      `<b>Weekends run lighter:</b> the plant uses about ${fmt(K.weekday_vs_weekend, 1)}× more energy on a weekday than on a weekend day.`,
      `<b>Light load</b> takes ${light.time_pct[0]}% of the time but only ${light.energy_pct[0]}% of the energy, so most savings from idling come from long, low-level periods.`,
      `<b>Power factor</b> is the weak spot: ${fmt(K.pf_below_90_pct, 0)}% of readings fall below the 90% mark, mostly overnight and at light load.`,
      `<b>Forecasts help:</b> the next-day model cuts average error by ${fmt(nd.improvement_vs_baseline_pct, 0)}% and the next-15-minute model by ${fmt(q.improvement_vs_baseline_pct, 0)}% versus the best simple guess.`,
    ].map(t => `<li>${t}</li>`).join('');
  }
})();
