(function () {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();

  // --- Radar: six-dimension learner profile ---
  var radarEl = document.getElementById('chart-radar');
  if (radarEl) {
    var radar = echarts.init(radarEl, null, { renderer: 'svg' });
    radar.setOption({
      animation: false,
      tooltip: { trigger: 'item', appendToBody: true },
      radar: {
        indicator: [
          { name: '表现分', max: 1 },
          { name: '置信度', max: 1 },
          { name: '困惑风险', max: 1 },
          { name: '提问深度', max: 1 },
          { name: '提示依赖', max: 1 },
          { name: '解释需求', max: 1 }
        ],
        radius: '62%',
        splitArea: { show: true, areaStyle: { color: [bg2, 'rgba(37,99,235,0.03)'] } },
        axisLine: { lineStyle: { color: rule } },
        splitLine: { lineStyle: { color: rule } }
      },
      series: [{
        type: 'radar',
        data: [{
          name: '示例学习者',
          value: [0.35, 0.6, 0.8, 0.55, 0.7, 0.52],
          lineStyle: { color: accent, width: 2 },
          itemStyle: { color: accent },
          areaStyle: { color: accent, opacity: 0.12 },
          symbol: 'circle', symbolSize: 5
        }]
      }],
      legend: { bottom: 0, textStyle: { color: muted } }
    });
    window.addEventListener('resize', function () { radar.resize(); });
  }

  // --- Bars: cognitive test coverage by module ---
  var barEl = document.getElementById('chart-bars');
  if (barEl) {
    var bar = echarts.init(barEl, null, { renderer: 'svg' });
    bar.setOption({
      animation: false,
      tooltip: { trigger: 'axis', appendToBody: true },
      grid: { left: 60, right: 24, top: 30, bottom: 60 },
      xAxis: {
        type: 'category',
        data: ['衰减', '前置锚定', '投影', '冻结契约', '轨迹', '路径', '策略迟滞', '提示词契约', '认知端口'],
        axisLabel: { color: muted, rotate: 28, fontSize: 11 },
        axisLine: { lineStyle: { color: rule } }
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: muted },
        splitLine: { lineStyle: { color: rule } }
      },
      series: [{
        type: 'bar',
        data: [4, 5, 6, 2, 6, 7, 9, 8, 4],
        itemStyle: {
          color: accent,
          borderRadius: [4, 4, 0, 0]
        },
        barWidth: '52%',
        label: { show: true, position: 'top', color: ink, fontSize: 11 }
      }]
    });
    window.addEventListener('resize', function () { bar.resize(); });
  }
})();
