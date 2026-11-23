/* Shared helpers: theme toggle + chart defaults */
(function () {
  const root = document.documentElement;
  const btn = document.getElementById('themeBtn');
  if (btn) btn.addEventListener('click', () => {
    const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('theme', next); } catch (e) {}
    window.dispatchEvent(new Event('themechange'));
  });

  window.css = (name) => getComputedStyle(root).getPropertyValue(name).trim();
  window.fmt = (n, d = 2) => Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  window.fmt0 = (n) => Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
  window.alpha = (hex, a) => {
    const h = hex.replace('#', ''); const v = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h, 16);
    return `rgba(${(v >> 16) & 255}, ${(v >> 8) & 255}, ${v & 255}, ${a})`;
  };

  window.applyChartDefaults = function () {
    if (!window.Chart) return;
    Chart.defaults.font.family = css('--font');
    Chart.defaults.font.size = 12;
    Chart.defaults.color = css('--muted');
    Chart.defaults.borderColor = css('--line');
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.boxWidth = 8;
    Chart.defaults.plugins.tooltip.backgroundColor = css('--card-solid');
    Chart.defaults.plugins.tooltip.titleColor = css('--text');
    Chart.defaults.plugins.tooltip.bodyColor = css('--muted');
    Chart.defaults.plugins.tooltip.borderColor = css('--line-strong');
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 10;
  };
  applyChartDefaults();
})();
