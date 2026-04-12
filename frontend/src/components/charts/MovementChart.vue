<template>
  <div class="chart-wrap">
    <div ref="containerRef" class="chart-container"></div>
    <div class="chart-legend">
      <template v-if="items.length === 1">
        <span class="leg-item"><span class="leg-bar" style="background:#60a5fa"></span>Movement</span>
        <span class="leg-item"><span class="leg-bar" style="background:#f87171"></span>High Activity</span>
        <span class="leg-item"><span class="leg-dash" style="border-color:#8b8fa3"></span>Average</span>
        <span class="leg-item"><span class="leg-zone" style="background:rgba(239,68,68,0.25)"></span>Restless</span>
        <span class="leg-item"><span class="leg-zone" style="background:rgba(45,212,191,0.2)"></span>Calm</span>
        <button class="stage-toggle" :class="{ active: showStages }" @click="toggleStages">
          <span class="stage-icon"></span>Sleep Stages
        </button>
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
import { STAGE_COLORS } from '../../utils/stageColors'

const props = defineProps({ items: { type: Array, default: () => [] } })

const containerRef = ref(null)
const tooltipEl = ref(null)
const showStages = ref(true)
const palette = ['#f87171','#60a5fa','#34d399','#a78bfa','#fbbf24','#f472b6','#38bdf8','#fb923c']
const stageColors = STAGE_COLORS

function toggleStages() { showStages.value = !showStages.value; update() }

const STRIP_H = 14
const M = { top: 16 + STRIP_H + 4, right: 16, bottom: 28, left: 44 }
let svg, g, rootG, xScale, yScale, gX, gY, resizeObs, w = 600, h = 260

function periodLabel(p) {
  const d = new Date(p.started_at)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + p.sleep_type
}

/** Find notable movement zones: most restless burst and calmest stretch */
function findNotableZones(series) {
  if (series.length < 3) return { points: [], zones: [] }
  const vals = series.map(d => d.v)
  const maxVal = d3.max(vals)
  const points = []
  const zones = []

  // Peak movement point
  const peakPt = series.find(d => d.v === maxVal)
  if (peakPt) points.push({ ...peakPt, label: `Peak ${peakPt.v.toFixed(3)}g`, type: 'peak' })

  // Find restless bursts — consecutive points above 75th percentile
  const p75 = d3.quantile([...vals].sort(d3.ascending), 0.75) || 0
  let burstStart = -1
  for (let i = 0; i <= series.length; i++) {
    const aboveThreshold = i < series.length && series[i].v > p75
    if (aboveThreshold && burstStart < 0) burstStart = i
    if (!aboveThreshold && burstStart >= 0) {
      if (i - burstStart >= 2) {
        zones.push({ start: series[burstStart].t, end: series[i - 1].t, type: 'restless' })
      }
      burstStart = -1
    }
  }

  // Find calmest stretch — longest run of points below 25th percentile
  const p25 = d3.quantile([...vals].sort(d3.ascending), 0.25) || 0
  let calmStart = -1, bestCalmLen = 0, bestCalmStart = -1, bestCalmEnd = -1
  for (let i = 0; i <= series.length; i++) {
    const belowThreshold = i < series.length && series[i].v <= p25
    if (belowThreshold && calmStart < 0) calmStart = i
    if (!belowThreshold && calmStart >= 0) {
      if (i - calmStart > bestCalmLen) {
        bestCalmLen = i - calmStart; bestCalmStart = calmStart; bestCalmEnd = i - 1
      }
      calmStart = -1
    }
  }
  if (bestCalmLen >= 3) {
    zones.push({ start: series[bestCalmStart].t, end: series[bestCalmEnd].t, type: 'calm' })
  }

  return { points, zones }
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

  // Clip path to prevent overflow when zoomed
  const clipId = 'mv-clip-' + Math.random().toString(36).slice(2, 8)
  svg.append('defs').append('clipPath').attr('id', clipId)
    .append('rect').attr('width', iw).attr('height', ih)

  // Stage strip at top
  svg.append('g').attr('class', 'stage-strip')
    .attr('transform', `translate(${M.left},${16})`)

  rootG = svg.append('g').attr('transform', `translate(${M.left},${M.top})`)
  g = rootG.append('g').attr('clip-path', `url(#${clipId})`)

  xScale = d3.scaleTime().range([0, iw])
  yScale = d3.scaleLinear().range([ih, 0])

  g.append('g').attr('class', 'grid')
  g.append('g').attr('class', 'stage-bg')
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
  const allData = props.items.flatMap(it => it.analysis.movement_series || [])
  if (!allData.length) return

  const tExtent = d3.extent(allData, d => d.t)
  const vExtent = d3.extent(allData, d => d.v)
  xScale.domain([new Date(tExtent[0]), new Date(tExtent[1])])
  yScale.domain([0, (vExtent[1] || 0.1) + 0.01]).nice()

  gX.call(d3.axisBottom(xS).ticks(6).tickFormat(d3.timeFormat('%H:%M'))).call(styleAxis)
  gY.call(d3.axisLeft(yScale).ticks(5).tickFormat(d => d.toFixed(2))).call(styleAxis)

  g.select('.grid').selectAll('line').remove()
  g.select('.grid').selectAll('line').data(yScale.ticks(5)).enter().append('line')
    .attr('x1', 0).attr('x2', iw).attr('y1', d => yScale(d)).attr('y2', d => yScale(d))
    .attr('stroke', 'rgba(255,255,255,0.05)')

  // Stage strip at top (uses its own x-scale spanning full stage series)
  const strip = svg.select('.stage-strip')
  strip.selectAll('*').remove()
  if (single && showStages.value) {
    const stages = props.items[0].analysis.sleep_stage_series || []
    if (stages.length) {
      const sorted = [...stages].sort((a, b) => a.t - b.t)
      const sExtent = d3.extent(sorted, d => d.t)
      const stripX = d3.scaleTime().domain([new Date(sExtent[0]), new Date(sExtent[1])]).range([0, iw])
      for (let i = 0; i < sorted.length; i++) {
        const s = sorted[i], nextT = sorted[i + 1]?.t || sExtent[1]
        const x1 = stripX(new Date(s.t)), x2 = stripX(new Date(nextT))
        strip.append('rect')
          .attr('x', Math.max(0, x1)).attr('width', Math.min(iw, x2) - Math.max(0, x1))
          .attr('y', 0).attr('height', STRIP_H)
          .attr('fill', stageColors[s.stage] || 'transparent')
          .attr('rx', 1)
      }
      strip.append('rect')
        .attr('x', 0).attr('y', 0).attr('width', iw).attr('height', STRIP_H)
        .attr('fill', 'none').attr('stroke', '#2a2e3d').attr('rx', 3)
    }
  }

  const maxPts = Math.max(300, iw)
  const dataLayer = g.select('.data-layer')
  dataLayer.selectAll('*').remove()

  if (single) {
    const raw = props.items[0].analysis.movement_series || []
    const data = downsample(raw, maxPts)
    // Bar chart
    data.forEach((d, i) => {
      const x1 = xS(new Date(d.t))
      const nextT = data[i + 1]?.t || d.t + 60000
      const x2 = xS(new Date(nextT))
      const bw = Math.max(1, x2 - x1)
      if (x2 > 0 && x1 < iw) {
        dataLayer.append('rect')
          .attr('x', Math.max(0, x1)).attr('width', Math.min(iw, x1 + bw) - Math.max(0, x1))
          .attr('y', yScale(d.v)).attr('height', Math.max(0, ih - yScale(d.v)))
          .attr('fill', d.v > 0.04 ? '#f87171' : '#60a5fa').attr('opacity', 0.7)
      }
    })
  } else {
    const line = d3.line().x(d => xS(new Date(d.t))).y(d => yScale(d.v)).curve(d3.curveMonotoneX)
    props.items.forEach((item, i) => {
      const raw = item.analysis.movement_series || []
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
      .text(`avg ${avgVal.toFixed(3)}g`)
  }

  // Notable zones & points
  const anomLayer = g.select('.anomaly-layer')
  anomLayer.selectAll('*').remove()
  if (single) {
    const raw = props.items[0].analysis.movement_series || []
    const { points, zones } = findNotableZones(raw)

    // Highlight zones as shaded bands (no text — colors speak for themselves)
    zones.forEach(z => {
      const x1 = xS(new Date(z.start)), x2 = xS(new Date(z.end))
      if (x2 < 0 || x1 > iw) return
      const clampX1 = Math.max(0, x1), clampX2 = Math.min(iw, x2)
      const isRestless = z.type === 'restless'
      anomLayer.append('rect')
        .attr('x', clampX1).attr('width', Math.max(2, clampX2 - clampX1))
        .attr('y', 0).attr('height', ih)
        .attr('fill', isRestless ? 'rgba(239,68,68,0.12)' : 'rgba(45,212,191,0.10)')
        .attr('rx', 3)
    })

    // Peak point marker — label on hover only
    points.forEach(n => {
      const cx = xS(new Date(n.t)), cy = yScale(n.v)
      if (cx < 0 || cx > iw) return
      const grp = anomLayer.append('g').attr('class', 'notable-point').style('cursor', 'pointer')
      grp.append('circle').attr('cx', cx).attr('cy', cy).attr('r', 8)
        .attr('fill', 'none').attr('stroke', '#fca5a5').attr('stroke-width', 1.5).attr('opacity', 0.5)
      grp.append('circle').attr('cx', cx).attr('cy', cy).attr('r', 4)
        .attr('fill', '#ef4444').attr('stroke', '#fff').attr('stroke-width', 0.8)
      const label = grp.append('g').attr('class', 'notable-label').style('opacity', 0).style('pointer-events', 'none')
      const txtY = cy - 16
      label.append('rect')
        .attr('x', cx - 34).attr('y', txtY - 10).attr('width', 68).attr('height', 16)
        .attr('fill', 'rgba(26,29,39,0.9)').attr('stroke', '#ef4444').attr('stroke-width', 0.5).attr('rx', 4)
      label.append('text')
        .attr('x', cx).attr('y', txtY)
        .attr('fill', '#ef4444').attr('font-size', '10px').attr('font-weight', '600')
        .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle').text(n.label)
      grp.append('circle').attr('cx', cx).attr('cy', cy).attr('r', 14)
        .attr('fill', 'transparent')
      grp.on('mouseenter', () => label.transition().duration(150).style('opacity', 1))
      grp.on('mouseleave', () => label.transition().duration(150).style('opacity', 0))
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
.leg-bar { width: 10px; height: 12px; border-radius: 2px; }
.leg-dash { width: 16px; height: 0; border-top: 2px dashed; }
.leg-dot { width: 8px; height: 8px; border-radius: 50%; }
.leg-zone { width: 14px; height: 12px; border-radius: 2px; }
.d3-tooltip { display: none; position: absolute; background: rgba(26,29,39,0.95); border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; font-size: 11px; color: var(--text); pointer-events: none; z-index: 10; white-space: nowrap; }
.stage-toggle { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--text-dim); background: transparent; border: 1px solid var(--border); border-radius: 6px; padding: 3px 10px; cursor: pointer; margin-left: auto; transition: all 0.2s; }
.stage-toggle:hover { border-color: var(--accent); color: var(--text); }
.stage-toggle.active { background: rgba(124,110,240,0.15); border-color: var(--accent); color: var(--accent); }
.stage-icon { width: 10px; height: 10px; border-radius: 2px; background: linear-gradient(135deg, #3b82f6 0%, #2dd4bf 50%, #e879f9 100%); }
</style>
