<template>
  <div class="chart-wrap">
    <div ref="containerRef" class="chart-container"></div>
    <div class="chart-legend">
      <template v-if="items.length === 1">
        <span class="leg-item"><span class="leg-line" style="background:#34d399"></span>Respiratory Rate</span>
        <span class="leg-item"><span class="leg-dash" style="border-color:#8b8fa3"></span>Average</span>
        <span class="leg-item"><span class="leg-dot" style="background:#ef4444"></span>Anomaly</span>
      </template>
      <template v-else>
        <span v-for="(item, i) in items" :key="i" class="leg-item">
          <span class="leg-line" :style="{ background: palette[i % palette.length] }"></span>
          {{ periodLabel(item.period) }}
        </span>
      </template>
    </div>
    <div class="d3-tooltip" ref="tooltipEl"></div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import * as d3 from 'd3'

const props = defineProps({ items: { type: Array, default: () => [] } })

const containerRef = ref(null)
const tooltipEl = ref(null)
const palette = ['#f87171','#60a5fa','#34d399','#a78bfa','#fbbf24','#f472b6','#38bdf8','#fb923c']

const M = { top: 16, right: 16, bottom: 28, left: 44 }
let svg, g, rootG, xScale, yScale, gX, gY, resizeObs, w = 600, h = 260

function periodLabel(p) {
  const d = new Date(p.started_at)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + p.sleep_type
}

function detectAnomalies(series, sigma = 2.0) {
  const vals = series.map(d => d.v)
  const mean = d3.mean(vals), std = d3.deviation(vals) || 1
  return series.filter(d => Math.abs((d.v - mean) / std) > sigma)
}

function downsample(data, maxPts) {
  if (data.length <= maxPts) return data
  const out = [data[0]]
  const bucketSize = (data.length - 2) / (maxPts - 2)
  let a = 0
  for (let i = 1; i < maxPts - 1; i++) {
    const rangeStart = Math.floor((i - 1) * bucketSize) + 1
    const rangeEnd = Math.min(Math.floor(i * bucketSize) + 1, data.length)
    const nextStart = Math.floor(i * bucketSize) + 1
    const nextEnd = Math.min(Math.floor((i + 1) * bucketSize) + 1, data.length)
    let avgT = 0, avgV = 0, count = 0
    for (let j = nextStart; j < nextEnd; j++) { avgT += data[j].t; avgV += data[j].v; count++ }
    avgT /= count; avgV /= count
    let maxArea = -1, maxIdx = rangeStart
    for (let j = rangeStart; j < rangeEnd; j++) {
      const area = Math.abs((data[a].t - avgT) * (data[j].v - data[a].v) - (data[a].t - data[j].t) * (avgV - data[a].v))
      if (area > maxArea) { maxArea = area; maxIdx = j }
    }
    out.push(data[maxIdx])
    a = maxIdx
  }
  out.push(data[data.length - 1])
  return out
}

function styleAxis(sel) {
  sel.selectAll('text').attr('fill', '#8b8fa3').attr('font-size', '11px')
  sel.selectAll('line,path').attr('stroke', '#2a2e3d')
}

function init() {
  if (!containerRef.value) return
  d3.select(containerRef.value).selectAll('svg').remove()
  const rect = containerRef.value.getBoundingClientRect()
  w = Math.max(rect.width || 600, 300); h = 260
  const iw = w - M.left - M.right, ih = h - M.top - M.bottom

  svg = d3.select(containerRef.value).append('svg').attr('width', w).attr('height', h)

  const defs = svg.append('defs')
  const grad = defs.append('linearGradient').attr('id', 'resp-grad').attr('x1','0%').attr('y1','0%').attr('x2','0%').attr('y2','100%')
  grad.append('stop').attr('offset','0%').attr('stop-color','#34d399').attr('stop-opacity', 0.4)
  grad.append('stop').attr('offset','100%').attr('stop-color','#34d399').attr('stop-opacity', 0.02)

  // Clip path to prevent overflow when zoomed
  const clipId = 'rr-clip-' + Math.random().toString(36).slice(2, 8)
  defs.append('clipPath').attr('id', clipId)
    .append('rect').attr('width', iw).attr('height', ih)

  rootG = svg.append('g').attr('transform', `translate(${M.left},${M.top})`)
  g = rootG.append('g').attr('clip-path', `url(#${clipId})`)

  xScale = d3.scaleTime().range([0, iw])
  yScale = d3.scaleLinear().range([ih, 0])

  g.append('g').attr('class', 'grid')
  g.append('g').attr('class', 'area-layer')
  g.append('g').attr('class', 'data-layer')
  g.append('g').attr('class', 'avg-layer')
  g.append('g').attr('class', 'anomaly-layer')

  const ch = rootG.append('g').attr('class', 'crosshair').style('display', 'none')
  ch.append('line').attr('y1', 0).attr('y2', ih).attr('stroke', '#7c6ef0').attr('stroke-dasharray', '3,3').attr('stroke-width', 1)

  gX = rootG.append('g').attr('transform', `translate(0,${ih})`)
  gY = rootG.append('g')

  const zoom = d3.zoom().scaleExtent([1, 20])
    .extent([[M.left, M.top], [M.left + iw, M.top + ih]])
    .translateExtent([[M.left, M.top], [M.left + iw, M.top + ih]])
    .on('zoom', ev => {
      const nx = ev.transform.rescaleX(xScale)
      gX.call(d3.axisBottom(nx).ticks(6).tickFormat(d3.timeFormat('%H:%M'))).call(styleAxis)
      render(nx)
    })
  svg.call(zoom)
  svg.on('dblclick.zoom', () => svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity))

  svg.on('mousemove', function(ev) {
    const [mx] = d3.pointer(ev, rootG.node())
    if (mx >= 0 && mx <= iw) {
      ch.style('display', null).attr('transform', `translate(${mx},0)`)
      const tip = tooltipEl.value
      if (tip) {
        tip.style.display = 'block'
        tip.style.left = (ev.offsetX + 12) + 'px'
        tip.style.top = (ev.offsetY - 10) + 'px'
        const t = xScale.invert(mx)
        tip.textContent = d3.timeFormat('%H:%M')(t)
      }
    }
  })
  svg.on('mouseleave', () => {
    ch.style('display', 'none')
    if (tooltipEl.value) tooltipEl.value.style.display = 'none'
  })
}

function render(xS) {
  if (!g) return
  xS = xS || xScale
  const iw = w - M.left - M.right, ih = h - M.top - M.bottom
  const single = props.items.length === 1
  const allData = props.items.flatMap(it => it.analysis.respiratory_series || [])
  if (!allData.length) return

  const tExtent = d3.extent(allData, d => d.t)
  const vExtent = d3.extent(allData, d => d.v)
  xScale.domain([new Date(tExtent[0]), new Date(tExtent[1])])
  yScale.domain([Math.max(0, (vExtent[0] || 0) - 2), (vExtent[1] || 20) + 2]).nice()

  gX.call(d3.axisBottom(xS).ticks(6).tickFormat(d3.timeFormat('%H:%M'))).call(styleAxis)
  gY.call(d3.axisLeft(yScale).ticks(5)).call(styleAxis)

  g.select('.grid').selectAll('line').remove()
  g.select('.grid').selectAll('line').data(yScale.ticks(5)).enter().append('line')
    .attr('x1', 0).attr('x2', iw).attr('y1', d => yScale(d)).attr('y2', d => yScale(d))
    .attr('stroke', 'rgba(255,255,255,0.05)')

  const maxPts = Math.max(300, iw)
  const areaLayer = g.select('.area-layer')
  areaLayer.selectAll('*').remove()
  const dataLayer = g.select('.data-layer')
  dataLayer.selectAll('*').remove()

  const line = d3.line().x(d => xS(new Date(d.t))).y(d => yScale(d.v)).curve(d3.curveMonotoneX)
  const area = d3.area().x(d => xS(new Date(d.t))).y0(ih).y1(d => yScale(d.v)).curve(d3.curveMonotoneX)

  if (single) {
    const raw = props.items[0].analysis.respiratory_series || []
    const data = downsample(raw, maxPts)
    areaLayer.append('path').datum(data).attr('d', area).attr('fill', 'url(#resp-grad)')
    dataLayer.append('path').datum(data).attr('d', line)
      .attr('fill', 'none').attr('stroke', '#34d399').attr('stroke-width', 1.5).attr('opacity', 0.9)
  } else {
    props.items.forEach((item, i) => {
      const raw = item.analysis.respiratory_series || []
      const data = downsample(raw, maxPts)
      dataLayer.append('path').datum(data).attr('d', line)
        .attr('fill', 'none').attr('stroke', palette[i % palette.length]).attr('stroke-width', 1.5).attr('opacity', 0.8)
    })
  }

  // Avg line
  const avgLayer = g.select('.avg-layer')
  avgLayer.selectAll('*').remove()
  const avgVal = d3.mean(allData, d => d.v)
  if (avgVal != null) {
    avgLayer.append('line').attr('x1', 0).attr('x2', iw)
      .attr('y1', yScale(avgVal)).attr('y2', yScale(avgVal))
      .attr('stroke', 'rgba(255,255,255,0.4)').attr('stroke-dasharray', '6,4').attr('stroke-width', 1)
    avgLayer.append('text').attr('x', iw - 4).attr('y', yScale(avgVal) - 5)
      .attr('fill', 'rgba(255,255,255,0.5)').attr('font-size', '10px').attr('text-anchor', 'end')
      .text(`avg ${avgVal.toFixed(1)} br/min`)
  }

  // Anomalies — red dots
  const anomLayer = g.select('.anomaly-layer')
  anomLayer.selectAll('*').remove()
  if (single) {
    const raw = props.items[0].analysis.respiratory_series || []
    const anoms = detectAnomalies(raw)
    anoms.forEach(a => {
      const cx = xS(new Date(a.t)), cy = yScale(a.v)
      if (cx >= 0 && cx <= iw) {
        anomLayer.append('circle').attr('cx', cx).attr('cy', cy).attr('r', 4)
          .attr('fill', '#ef4444').attr('opacity', 0.85).attr('stroke', '#fff').attr('stroke-width', 0.5)
      }
    })
  }
}

function update() { if (g) render() }

onMounted(() => { init(); update(); resizeObs = new ResizeObserver(() => { init(); update() }); resizeObs.observe(containerRef.value) })
onBeforeUnmount(() => { resizeObs?.disconnect() })
watch(() => props.items, update, { deep: true })
</script>

<style scoped>
.chart-wrap { position: relative; }
.chart-container { width: 100%; height: 260px; }
.chart-legend { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 8px; }
.leg-item { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-dim); }
.leg-line { width: 16px; height: 3px; border-radius: 2px; }
.leg-dash { width: 16px; height: 0; border-top: 2px dashed; }
.leg-dot { width: 8px; height: 8px; border-radius: 50%; }
.d3-tooltip { display: none; position: absolute; background: rgba(26,29,39,0.95); border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; font-size: 11px; color: var(--text); pointer-events: none; z-index: 10; white-space: nowrap; }
</style>
